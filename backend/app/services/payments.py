"""Payment intents, the local test-mode confirmation and staff refunds.

Nothing in this module marks an order paid or refunded directly. The local test
provider *builds and signs* Stripe-format events with ``LOCAL_PAYMENT_WEBHOOK_SECRET``
and hands them to ``webhooks.verify_and_process`` — the same function the HTTP webhook
uses — so test mode exercises the production verification and state machine.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.order import Order
from app.models.user import User
from app.services import audit, reservations, webhooks
from app.services.payment_providers import CURRENCY, StripeProvider, get_provider

LOCAL_OUTCOMES = ("succeed", "decline", "requires_action", "authenticate", "processing")


def ensure_card(payment_method: str) -> None:
    """Only card payments are offered; Afterpay / Laybuy are refused with the recorded reason."""
    if payment_method == "card":
        return
    from app.routers.system import AFTERPAY_REASON, LAYBUY_REASON

    reason = {"afterpay": AFTERPAY_REASON, "laybuy": LAYBUY_REASON}.get(
        payment_method.lower(), "Only card payments are available."
    )
    raise AppError(
        422, "payment_method_unavailable", reason, extra={"payment_method": payment_method[:32]}
    )


# --------------------------------------------------------------------------- intents
async def create_intent(db: AsyncSession, user_id: uuid.UUID, order_id: uuid.UUID) -> dict:
    """Create or recover the order's payment intent (idempotent)."""
    provider = get_provider()
    order = await reservations.lock_order(db, order_id, user_id=user_id)
    if order is None:
        raise not_found("Order")
    if order.payment_status in webhooks.PAID_PAYMENT_STATUSES or order.paid_at is not None:
        raise AppError(409, "order_already_paid", "This order has already been paid")
    if order.status != "pending_payment":
        raise AppError(409, "order_not_payable", f"This order is {order.status} and cannot be paid")
    if order.payment_provider != provider.name:
        raise AppError(
            409,
            "payment_provider_changed",
            "This order cannot be paid with the current payment provider",
        )
    if order.expires_at is not None and order.expires_at <= utcnow():
        raise AppError(409, "reservation_expired", "This order's stock reservation has expired")
    info = await provider.ensure_intent(order)
    await db.flush()
    return {
        "order_id": order.id,
        "provider": info.provider,
        "payment_intent_id": info.payment_intent_id,
        "client_secret": info.client_secret,
        "status": info.status,
        "amount_cents": info.amount_cents,
        "currency": "NZD",
        "publishable_key": provider.publishable_key
        if isinstance(provider, StripeProvider)
        else None,
        "test_mode": provider.test_mode,
        "expires_at": order.expires_at,
    }


# --------------------------------------------------------------------------- signing
def sign_payload(payload: str, secret: str, timestamp: int | None = None) -> str:
    """Stripe-format signature header: ``t=<ts>,v1=<hmac_sha256(secret, "ts.payload")>``."""
    t = int(timestamp if timestamp is not None else time.time())
    mac = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def build_event(event_type: str, obj: dict) -> dict:
    return {
        "id": f"evt_local_{uuid.uuid4().hex}",
        "object": "event",
        "created": int(time.time()),
        "livemode": False,
        "type": event_type,
        "data": {"object": obj},
    }


def order_metadata(order: Order) -> dict:
    return {
        "order_id": str(order.id),
        "user_id": str(order.user_id),
        "order_number": order.order_number,
    }


def payment_intent_object(order: Order, status: str, **extra) -> dict:
    return {
        "id": order.payment_intent_id,
        "object": "payment_intent",
        "amount": order.total_cents,
        "amount_received": order.total_cents if status == "succeeded" else 0,
        "currency": CURRENCY,
        "status": status,
        "payment_method_types": ["card"],
        "livemode": False,
        "metadata": order_metadata(order),
        **extra,
    }


def charge_object(order: Order, amount_refunded: int) -> dict:
    return {
        "id": f"ch_local_{order.id.hex}",
        "object": "charge",
        "amount": order.total_cents,
        "amount_captured": order.total_cents,
        "amount_refunded": amount_refunded,
        "currency": CURRENCY,
        "payment_intent": order.payment_intent_id,
        "refunded": amount_refunded == order.total_cents,
        "livemode": False,
        "metadata": order_metadata(order),
    }


async def deliver_local_event(db: AsyncSession, event: dict) -> dict:
    """Sign a local event and pass it through the real webhook verification."""
    payload = json.dumps(event, separators=(",", ":"))
    secret = get_settings().local_payment_webhook_secret
    return await webhooks.verify_and_process(db, payload.encode(), sign_payload(payload, secret))


def local_mode_active() -> bool:
    s = get_settings()
    return s.is_local and s.payment_provider == "local" and s.payments_available


# --------------------------------------------------------------------------- local confirm
async def local_confirm(
    db: AsyncSession, user_id: uuid.UUID, payment_intent_id: str, outcome: str
) -> dict:
    """Simulate the customer completing (or failing) a local test-mode payment."""
    if not local_mode_active():
        raise not_found("Payment")
    order = await webhooks.lock_by_payment_intent(db, payment_intent_id)
    if order is None or order.user_id != user_id or order.payment_provider != "local":
        raise not_found("Payment")
    if order.payment_status in webhooks.PAID_PAYMENT_STATUSES:
        raise AppError(409, "order_already_paid", "This order has already been paid")
    if order.status not in ("pending_payment", "expired"):
        raise AppError(409, "order_not_payable", f"This order is {order.status} and cannot be paid")
    if outcome == "succeed":
        event = build_event("payment_intent.succeeded", payment_intent_object(order, "succeeded"))
    elif outcome == "authenticate":
        if order.payment_status != "requires_action":
            raise AppError(409, "no_action_required", "This payment is not awaiting authentication")
        event = build_event("payment_intent.succeeded", payment_intent_object(order, "succeeded"))
    elif outcome == "decline":
        event = build_event(
            "payment_intent.payment_failed",
            payment_intent_object(
                order,
                "requires_payment_method",
                last_payment_error={
                    "type": "card_error",
                    "code": "card_declined",
                    "decline_code": "generic_decline",
                    "message": "Your card was declined. (test mode)",
                },
            ),
        )
    elif outcome == "requires_action":
        event = build_event(
            "payment_intent.requires_action",
            payment_intent_object(order, "requires_action", next_action={"type": "use_stripe_sdk"}),
        )
    elif outcome == "processing":
        event = build_event("payment_intent.processing", payment_intent_object(order, "processing"))
    else:  # pragma: no cover - schema restricts values
        raise AppError(422, "invalid_outcome", "Unknown outcome")
    result = await deliver_local_event(db, event)
    order = await reservations.lock_order(db, order.id)
    return {
        "test_mode": True,
        "outcome": outcome,
        "event_id": result["event_id"],
        "event_type": event["type"],
        "event_outcome": result["outcome"],
        "order_id": order.id,
        "order_status": order.status,
        "payment_status": order.payment_status,
    }


# --------------------------------------------------------------------------- refunds
async def request_refund(
    db: AsyncSession, actor: User, order_id: uuid.UUID, amount_cents: int, reason: str
) -> dict:
    """Ask the provider to refund. The order changes only when the provider's signed
    ``charge.refunded`` event is processed (immediately for the local provider)."""
    order = await reservations.lock_order(db, order_id)
    if order is None:
        raise not_found("Order")
    if (
        order.payment_status not in ("succeeded", "partially_refunded")
        or not order.payment_intent_id
    ):
        raise AppError(409, "order_not_refundable", "Only paid orders can be refunded")
    remaining = order.total_cents - order.refunded_cents
    if amount_cents > remaining:
        raise AppError(
            422,
            "refund_exceeds_remaining",
            "The refund is larger than the amount still refundable",
            extra={"refundable_cents": remaining},
        )
    provider = get_provider(order.payment_provider)
    await audit.record(
        db,
        actor.id,
        "order_refund_requested",
        "order",
        order.id,
        {"amount_cents": amount_cents, "reason": reason, "provider": provider.name},
    )
    if isinstance(provider, StripeProvider):
        info = await provider.refund(order, amount_cents)
        refund_id, status, event_outcome = info.refund_id, info.status, None
    else:
        event = build_event(
            "charge.refunded", charge_object(order, order.refunded_cents + amount_cents)
        )
        result = await deliver_local_event(db, event)
        refund_id, status, event_outcome = (
            f"re_local_{uuid.uuid4().hex[:24]}",
            "succeeded",
            result["outcome"],
        )
        order = await reservations.lock_order(db, order.id)
    await db.flush()
    return {
        "order_id": order.id,
        "provider": provider.name,
        "refund_id": refund_id,
        "status": status,
        "amount_cents": amount_cents,
        "currency": "NZD",
        "test_mode": provider.test_mode,
        "event_outcome": event_outcome,
        "refunded_cents": order.refunded_cents,
        "payment_status": order.payment_status,
        "order_status": order.status,
    }
