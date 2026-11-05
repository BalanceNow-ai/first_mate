"""Payment provider adapters.

* ``stripe`` — PaymentIntents (card only, NZD). Card data never reaches this server:
  the client confirms the intent with Stripe using the returned ``client_secret``.
* ``local`` — an explicitly labelled test-mode substitute, refused outside
  development/test. It issues ``pi_local_<hex>`` intents; its outcomes are delivered as
  Stripe-format *signed* events through the same webhook verification and processing
  code as Stripe (see ``app.services.payments``).
* ``disabled`` — every payment operation answers 503 ``payments_unavailable``.

Provider exception text is never returned or logged; only the exception type and
our own identifiers are logged.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import stripe

from app.config import get_settings
from app.core.errors import AppError
from app.models.order import Order

logger = logging.getLogger(__name__)

CURRENCY = "nzd"


def payments_unavailable() -> AppError:
    return AppError(503, "payments_unavailable", "Payments are not available right now")


def provider_error() -> AppError:
    return AppError(
        502,
        "payment_provider_error",
        "The payment provider could not be reached. Please try again.",
    )


@dataclass
class IntentInfo:
    provider: str
    payment_intent_id: str
    client_secret: str
    status: str
    amount_cents: int
    currency: str = CURRENCY


@dataclass
class RefundInfo:
    provider: str
    refund_id: str
    status: str


class PaymentProvider:
    name: str
    test_mode: bool = False

    @property
    def webhook_secret(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def publishable_key(self) -> str | None:
        return None

    async def ensure_intent(self, order: Order) -> IntentInfo:  # pragma: no cover - interface
        raise NotImplementedError

    async def cancel_intent(self, order: Order) -> str:  # pragma: no cover - interface
        """Cancel the order's intent. Returns the intent's resulting status
        (``canceled``, ``succeeded``, ``processing`` ...)."""
        raise NotImplementedError


# --------------------------------------------------------------------------- Stripe
def _get(obj: Any, key: str, default: Any = None) -> Any:
    try:
        value = obj[key]
    except (KeyError, TypeError, AttributeError):
        return default
    return default if value is None else value


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def webhook_secret(self) -> str:
        return self.settings.stripe_webhook_secret

    @property
    def publishable_key(self) -> str | None:
        return self.settings.stripe_publishable_key or None

    async def _call(self, fn, *args, op: str, order_id: uuid.UUID, **kwargs):
        try:
            return await asyncio.to_thread(
                fn, *args, api_key=self.settings.stripe_secret_key, **kwargs
            )
        except stripe.StripeError as exc:
            logger.warning("Stripe %s failed for order %s (%s)", op, order_id, type(exc).__name__)
            raise

    async def ensure_intent(self, order: Order) -> IntentInfo:
        try:
            if order.payment_intent_id:
                pi = await self._call(
                    stripe.PaymentIntent.retrieve,
                    order.payment_intent_id,
                    op="retrieve",
                    order_id=order.id,
                )
            else:
                pi = await self._call(
                    stripe.PaymentIntent.create,
                    op="create",
                    order_id=order.id,
                    amount=order.total_cents,
                    currency=CURRENCY,
                    payment_method_types=["card"],
                    metadata={
                        "order_id": str(order.id),
                        "user_id": str(order.user_id),
                        "order_number": order.order_number,
                    },
                    idempotency_key=f"order:{order.id}:pi",
                )
        except stripe.StripeError:
            raise provider_error() from None
        status = _get(pi, "status", "")
        if status == "succeeded":
            raise AppError(
                409,
                "payment_already_succeeded",
                "This order has already been paid; confirmation is on its way",
            )
        if status == "canceled":
            raise AppError(
                409,
                "payment_intent_canceled",
                "This payment was cancelled. Please check out again.",
            )
        if (
            _get(pi, "amount") != order.total_cents
            or str(_get(pi, "currency", "")).lower() != CURRENCY
        ):
            logger.error(
                "Stripe intent for order %s does not match the order amount/currency", order.id
            )
            raise AppError(
                409,
                "payment_intent_mismatch",
                "This payment cannot be completed. Please contact us.",
            )
        order.payment_intent_id = _get(pi, "id")
        return IntentInfo(
            provider=self.name,
            payment_intent_id=order.payment_intent_id,
            client_secret=_get(pi, "client_secret", ""),
            status=status,
            amount_cents=order.total_cents,
        )

    async def cancel_intent(self, order: Order) -> str:
        if not order.payment_intent_id:
            return "canceled"
        try:
            pi = await self._call(
                stripe.PaymentIntent.cancel,
                order.payment_intent_id,
                op="cancel",
                order_id=order.id,
                idempotency_key=f"order:{order.id}:cancel",
            )
            return _get(pi, "status", "canceled")
        except stripe.InvalidRequestError:
            # e.g. already succeeded / processing: find out which.
            try:
                pi = await self._call(
                    stripe.PaymentIntent.retrieve,
                    order.payment_intent_id,
                    op="retrieve",
                    order_id=order.id,
                )
            except stripe.StripeError:
                raise provider_error() from None
            return _get(pi, "status", "unknown")
        except stripe.StripeError:
            raise provider_error() from None

    async def refund(self, order: Order, amount_cents: int) -> RefundInfo:
        try:
            refund = await self._call(
                stripe.Refund.create,
                op="refund",
                order_id=order.id,
                payment_intent=order.payment_intent_id,
                amount=amount_cents,
                reason="requested_by_customer",
                metadata={"order_id": str(order.id), "order_number": order.order_number},
                # Repeating the same request (double click / retry) cannot refund twice.
                idempotency_key=f"order:{order.id}:refund:{order.refunded_cents}:{amount_cents}",
            )
        except stripe.StripeError:
            raise provider_error() from None
        return RefundInfo(
            provider=self.name,
            refund_id=_get(refund, "id", ""),
            status=_get(refund, "status", "pending"),
        )


# --------------------------------------------------------------------------- local
class LocalProvider(PaymentProvider):
    """Test-mode substitute (development/test only). Nothing here is a real payment."""

    name = "local"
    test_mode = True

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def webhook_secret(self) -> str:
        return self.settings.local_payment_webhook_secret

    def client_secret(self, payment_intent_id: str) -> str:
        mac = hmac.new(
            self.webhook_secret.encode(), payment_intent_id.encode(), hashlib.sha256
        ).hexdigest()
        return f"{payment_intent_id}_secret_{mac[:24]}"

    async def ensure_intent(self, order: Order) -> IntentInfo:
        if not order.payment_intent_id:
            order.payment_intent_id = f"pi_local_{uuid.uuid4().hex}"
        status = {
            "requires_action": "requires_action",
            "processing": "processing",
        }.get(order.payment_status, "requires_payment_method")
        return IntentInfo(
            provider=self.name,
            payment_intent_id=order.payment_intent_id,
            client_secret=self.client_secret(order.payment_intent_id),
            status=status,
            amount_cents=order.total_cents,
        )

    async def cancel_intent(self, order: Order) -> str:
        return "canceled"


def get_provider(name: str | None = None) -> PaymentProvider:
    """The configured provider (or ``name``), refusing anything that is not usable."""
    settings = get_settings()
    name = name or settings.payment_provider
    if name != settings.payment_provider or not settings.payments_available:
        raise payments_unavailable()
    if name == "stripe":
        return StripeProvider()
    if name == "local" and settings.is_local:
        return LocalProvider()
    raise payments_unavailable()
