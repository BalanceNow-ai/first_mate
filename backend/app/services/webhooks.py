"""Signed payment-provider events: verification and the payment state machine.

There is exactly one way an order becomes paid, refunded or provider-cancelled: a
Stripe-format event whose signature verifies against the configured secret
(``STRIPE_WEBHOOK_SECRET`` for Stripe, the local secret for the local test provider in
development/test). The local test endpoints build and sign such events and call
``verify_and_process`` exactly like the HTTP webhook does.

Every event is recorded once in ``payment_events`` (unique provider event id) before it
is applied, so a duplicate delivery is a no-op. Every effect is additionally guarded by
the order's current state and conditional updates, so out-of-order or repeated events
never repeat stock, discount or reward effects.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import stripe
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.database import utcnow
from app.models.order import Order, PaymentEvent
from app.services import entitlements, events, reservations
from app.services.payment_providers import CURRENCY, payments_unavailable

logger = logging.getLogger(__name__)

PAID_PAYMENT_STATUSES = ("succeeded", "partially_refunded", "refunded")
PRE_DISPATCH = ("paid", "ready_for_dispatch")
LATE_PAYMENT_REVIEW = "paid after reservation released; refund required"


@dataclass
class Outcome:
    outcome: str  # applied | ignored | stale | mismatch
    detail: str | None = None
    order: Order | None = None


def webhook_config() -> tuple[str, str]:
    """(provider name, signing secret) for the active provider."""
    s = get_settings()
    if s.payment_provider == "stripe" and s.stripe_webhook_secret:
        return "stripe", s.stripe_webhook_secret
    if s.payment_provider == "local" and s.is_local and s.local_payment_webhook_secret:
        return "local", s.local_payment_webhook_secret
    raise payments_unavailable()


async def verify_and_process(db: AsyncSession, payload: bytes, signature: str | None) -> dict:
    """Verify a Stripe-format signature, then record and apply the event."""
    provider, secret = webhook_config()
    if not signature:
        raise AppError(400, "missing_signature", "Missing Stripe-Signature header")
    try:
        stripe.Webhook.construct_event(payload, signature, secret)
    except (stripe.SignatureVerificationError, ValueError):
        raise AppError(400, "invalid_signature", "Invalid webhook signature") from None
    try:
        event = json.loads(payload)
    except ValueError:  # pragma: no cover - construct_event already parsed it
        raise AppError(400, "invalid_event", "Malformed event") from None
    return await process_event(db, provider, event)


def _summary(event_type: str, obj: dict) -> dict:
    err = obj.get("last_payment_error") or {}
    out = {
        "type": event_type,
        "object": obj.get("object"),
        "status": obj.get("status"),
        "amount": obj.get("amount"),
        "amount_received": obj.get("amount_received"),
        "amount_refunded": obj.get("amount_refunded"),
        "currency": obj.get("currency"),
        "decline_code": err.get("decline_code") if isinstance(err, dict) else None,
        "error_code": err.get("code") if isinstance(err, dict) else None,
    }
    return {k: v for k, v in out.items() if v is not None}


async def process_event(db: AsyncSession, provider: str, event: Any) -> dict:
    if not isinstance(event, dict):
        raise AppError(400, "invalid_event", "Malformed event")
    event_id = event.get("id")
    event_type = event.get("type")
    obj = (event.get("data") or {}).get("object") if isinstance(event.get("data"), dict) else None
    if (
        not isinstance(event_id, str)
        or not event_id.startswith("evt_")
        or event.get("object", "event") != "event"
        or not isinstance(event_type, str)
        or not isinstance(obj, dict)
        or not isinstance(obj.get("id"), str)
    ):
        raise AppError(400, "invalid_event", "Malformed event")
    pi_id = obj.get("id") if obj.get("object") == "payment_intent" else obj.get("payment_intent")

    row_id = (
        await db.execute(
            insert(PaymentEvent)
            .values(
                id=uuid.uuid4(),
                provider=provider,
                provider_event_id=event_id,
                event_type=event_type,
                payment_intent_id=pi_id if isinstance(pi_id, str) else None,
                outcome="processing",
                summary=_summary(event_type, obj),
            )
            .on_conflict_do_nothing(index_elements=[PaymentEvent.provider_event_id])
            .returning(PaymentEvent.id)
        )
    ).scalar_one_or_none()
    if row_id is None:
        logger.info("Payment event %s (%s) already received", event_id, event_type)
        return {"received": True, "event_id": event_id, "outcome": "duplicate"}

    handler = HANDLERS.get(event_type)
    if handler is None:
        outcome = Outcome("ignored", "event type not used")
    else:
        outcome = await handler(db, obj)
    await db.execute(
        update(PaymentEvent)
        .where(PaymentEvent.id == row_id)
        .values(
            outcome=outcome.outcome,
            detail=outcome.detail,
            order_id=outcome.order.id if outcome.order is not None else None,
        )
    )
    await db.flush()
    logger.info(
        "Payment event %s (%s) -> %s%s",
        event_id,
        event_type,
        outcome.outcome,
        f" order={outcome.order.id}" if outcome.order is not None else "",
    )
    return {"received": True, "event_id": event_id, "outcome": outcome.outcome}


# --------------------------------------------------------------------------- binding
async def lock_by_payment_intent(db: AsyncSession, pi_id: str) -> Order | None:
    return (
        await db.execute(
            select(Order)
            .where(Order.payment_intent_id == pi_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _bind_intent(db: AsyncSession, obj: dict) -> tuple[Order | None, str | None]:
    """Find the order a PaymentIntent belongs to: the intent id AND metadata.order_id
    must agree. Returns (order or None, problem or None)."""
    pi_id = obj["id"]
    metadata = obj.get("metadata") or {}
    meta_order = metadata.get("order_id") if isinstance(metadata, dict) else None
    order = await lock_by_payment_intent(db, pi_id)
    if order is not None:
        if meta_order != str(order.id):
            return order, "payment intent metadata does not match the order"
        return order, None
    try:
        oid = uuid.UUID(str(meta_order))
    except ValueError:
        return None, "no order for this payment intent"
    order = await reservations.lock_order(db, oid)
    if order is None:
        return None, "no order for this payment intent"
    if order.payment_intent_id is None and metadata.get("user_id") == str(order.user_id):
        # Our process created the intent but crashed before recording its id.
        order.payment_intent_id = pi_id
        return order, None
    return order, "payment intent is not the order's intent"


def _amount_problem(order: Order, obj: dict, *, received: bool) -> str | None:
    currency = str(obj.get("currency") or "").lower()
    if currency != CURRENCY:
        return f"currency {currency or 'missing'} does not match nzd"
    if obj.get("amount") != order.total_cents:
        return f"amount {obj.get('amount')} does not match order total {order.total_cents}"
    if received and obj.get("amount_received") not in (None, order.total_cents):
        received_amount = obj.get("amount_received")
        return f"amount_received {received_amount} does not match order total {order.total_cents}"
    return None


def _to_review(order: Order, reason: str) -> None:
    order.status = "payment_review"
    order.review_reason = reason
    logger.warning("Order %s moved to payment review", order.id)


# --------------------------------------------------------------------------- handlers
async def _mark_paid(db: AsyncSession, order: Order) -> None:
    order.status = "paid"
    order.payment_status = "succeeded"
    order.paid_at = utcnow()
    order.review_reason = None
    await db.flush()
    await events.order_paid(db, order)


async def on_succeeded(db: AsyncSession, obj: dict) -> Outcome:
    order, problem = await _bind_intent(db, obj)
    if order is None:
        return Outcome("ignored", problem)
    if problem:
        if order.paid_at is None and order.status in ("pending_payment", "expired", "cancelled"):
            order.payment_status = "succeeded"
            _to_review(order, f"payment received that could not be bound to this order: {problem}")
        return Outcome("mismatch", problem, order)
    if order.paid_at is not None or order.payment_status in PAID_PAYMENT_STATUSES:
        return Outcome("stale", "payment already applied", order)
    amount_problem = _amount_problem(order, obj, received=True)
    if amount_problem:
        if order.status in ("pending_payment", "expired", "cancelled"):
            order.payment_status = "succeeded"  # money was received; staff must resolve
            _to_review(order, f"payment amount mismatch: {amount_problem}")
        return Outcome("mismatch", amount_problem, order)

    if order.status == "pending_payment":
        expected = await reservations.reservation_count(db, order.id)
        consumed = await reservations.consume(db, order)
        if consumed != expected:
            order.payment_status = "succeeded"
            _to_review(order, "stock reservation was not held at payment")
            return Outcome("mismatch", "reservation not held", order)
        await entitlements.consume_for_order(db, order)
        await _mark_paid(db, order)
        return Outcome("applied", None, order)

    if order.status in ("expired", "cancelled"):
        # The reservation was released before the payment confirmed: try to take the
        # stock (and the discount) again; otherwise it must be refunded by staff.
        await reservations.load_items(db, order)
        sp = await db.begin_nested()
        try:
            ok = await reservations.rereserve_released(db, order) and await entitlements.reclaim_for_paid_order(
                db, order
            )
        except Exception:
            await sp.rollback()
            raise
        if ok:
            await sp.commit()
        else:
            await sp.rollback()
        if ok:
            await reservations.remove_from_cart(db, order)
            order.cancel_reason = None
            order.cancelled_at = None
            await _mark_paid(db, order)
            return Outcome("applied", "paid after release; stock re-reserved", order)
        order.payment_status = "succeeded"
        _to_review(order, LATE_PAYMENT_REVIEW)
        return Outcome("mismatch", LATE_PAYMENT_REVIEW, order)

    return Outcome("ignored", f"order is {order.status}", order)


def _status_event(new_payment_status: str):
    async def handler(db: AsyncSession, obj: dict) -> Outcome:
        order, problem = await _bind_intent(db, obj)
        if order is None:
            return Outcome("ignored", problem)
        if problem:
            return Outcome("mismatch", problem, order)
        amount_problem = _amount_problem(order, obj, received=False)
        if amount_problem:
            return Outcome("mismatch", amount_problem, order)
        if order.status != "pending_payment" or order.payment_status in PAID_PAYMENT_STATUSES:
            return Outcome("stale", f"order is {order.status}", order)
        order.payment_status = new_payment_status
        await db.flush()
        return Outcome("applied", None, order)

    return handler


async def on_canceled(db: AsyncSession, obj: dict) -> Outcome:
    order, problem = await _bind_intent(db, obj)
    if order is None:
        return Outcome("ignored", problem)
    if problem:
        return Outcome("mismatch", problem, order)
    if order.status != "pending_payment" or order.payment_status in PAID_PAYMENT_STATUSES:
        return Outcome("stale", f"order is {order.status}", order)
    released = await reservations.release_order(
        db, order, new_status="cancelled", reason="payment_canceled", cancel_provider=False
    )
    return Outcome("applied" if released else "stale", None, order)


async def on_charge_refunded(db: AsyncSession, obj: dict) -> Outcome:
    pi_id = obj.get("payment_intent")
    if not isinstance(pi_id, str):
        return Outcome("ignored", "charge has no payment intent")
    order = await lock_by_payment_intent(db, pi_id)
    if order is None:
        return Outcome("ignored", "no order for this payment intent")
    metadata = obj.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("order_id") not in (None, str(order.id)):
        return Outcome("mismatch", "charge metadata does not match the order", order)
    amount_problem = _amount_problem(order, obj, received=False)
    if amount_problem:
        return Outcome("mismatch", amount_problem, order)
    if order.payment_status not in PAID_PAYMENT_STATUSES:
        # The success event has not been processed yet. Refuse *without* recording the
        # event (the transaction rolls back) so the provider redelivers it later.
        raise AppError(409, "event_deferred", "Payment not yet recorded for this refund; retry later")
    cumulative = obj.get("amount_refunded")
    if not isinstance(cumulative, int) or cumulative < 0 or cumulative > order.total_cents:
        return Outcome("mismatch", "invalid amount_refunded", order)
    delta = cumulative - order.refunded_cents
    if delta <= 0:
        return Outcome("stale", "refund already recorded", order)

    order.refunded_cents = cumulative
    full = cumulative == order.total_cents
    order.payment_status = "refunded" if full else "partially_refunded"
    if full and order.status in PRE_DISPATCH:
        order.status = "refunded"
        await reservations.restock_consumed(db, order)
    elif full and order.status == "payment_review":
        order.status = "refunded"
        await reservations.release(db, order)  # any stock still held for it
        await entitlements.release_for_order(db, order)
    await db.flush()
    if order.paid_at is not None:
        await events.order_refunded(db, order, delta)
    return Outcome("applied", f"refunded {delta} cents (cumulative {cumulative})", order)


HANDLERS = {
    "payment_intent.succeeded": on_succeeded,
    "payment_intent.payment_failed": _status_event("failed"),
    "payment_intent.requires_action": _status_event("requires_action"),
    "payment_intent.processing": _status_event("processing"),
    "payment_intent.canceled": on_canceled,
    "charge.refunded": on_charge_refunded,
}
