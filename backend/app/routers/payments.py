"""Payment intents, the signed provider webhook and the local test-mode confirmation."""

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.rate_limit import rate_limit, user_rate_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.schemas.payment import (
    LocalConfirmRequest,
    LocalConfirmResponse,
    PaymentIntentRequest,
    PaymentIntentResponse,
    WebhookResponse,
)
from app.services import payments, webhooks

router = APIRouter(prefix="/payments", tags=["Payments"])

MAX_WEBHOOK_BYTES = 512 * 1024


@router.post(
    "/orders/{order_id}/intent",
    response_model=PaymentIntentResponse,
    dependencies=[
        Depends(user_rate_limit("payment_intent", lambda: get_settings().rate_limit_payment_intent_per_minute))
    ],
)
async def create_payment_intent(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    body: PaymentIntentRequest | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Create or recover the order's card PaymentIntent (idempotent). The client confirms
    it with Stripe using ``client_secret``; card data never reaches this server."""
    payments.ensure_card((body or PaymentIntentRequest()).payment_method)
    result = await payments.create_intent(db, user_id, order_id)
    await db.commit()
    return result


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    dependencies=[Depends(rate_limit("payment_webhook", lambda: get_settings().rate_limit_webhook_per_minute))],
)
async def payment_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="Stripe-Signature"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Signed provider events (Stripe format). Unsigned or wrongly signed requests are
    refused with 400; there is no unsigned path."""
    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_BYTES:
        raise AppError(413, "payload_too_large", "Event too large")
    result = await webhooks.verify_and_process(db, payload, stripe_signature)
    await db.commit()
    return result


@router.post(
    "/local/{payment_intent_id}/confirm",
    response_model=LocalConfirmResponse,
    dependencies=[
        Depends(user_rate_limit("payment_intent", lambda: get_settings().rate_limit_payment_intent_per_minute))
    ],
)
async def local_confirm(
    payment_intent_id: str,
    body: LocalConfirmRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """TEST MODE ONLY (local provider in development/test; 404 otherwise). Simulates the
    customer's card outcome by building a Stripe-format event, signing it with the local
    webhook secret and passing it through the same verification and processing as the
    real webhook. It never marks anything paid directly."""
    if not payments.local_mode_active():
        raise not_found("Payment")
    result = await payments.local_confirm(db, user_id, payment_intent_id, body.outcome)
    await db.commit()
    return result
