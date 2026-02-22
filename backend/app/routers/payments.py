"""Stripe payment processing router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.order import Order

router = APIRouter(prefix="/payments", tags=["Payments"])
settings = get_settings()


@router.post("/{order_id}/create-intent")
async def create_payment_intent(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a Stripe Payment Intent for an order.

    The frontend uses the returned client_secret to confirm payment
    via the Stripe SDK.
    """
    result = await db.execute(
        select(Order).where(Order.id == order_id, Order.user_id == user_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if order.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Order is not in a payable state",
        )

    try:
        import stripe

        stripe.api_key = settings.stripe_secret_key
        intent = stripe.PaymentIntent.create(
            amount=int(float(order.total) * 100),  # Stripe expects cents
            currency="nzd",
            metadata={"order_id": str(order.id), "user_id": str(user_id)},
            payment_method_types=["card"],
        )

        order.stripe_payment_intent_id = intent.id
        await db.flush()

        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
        }
    except ImportError:
        # Stripe not configured — return mock for development
        order.stripe_payment_intent_id = f"pi_mock_{order.id}"
        await db.flush()
        return {
            "client_secret": f"pi_mock_{order.id}_secret",
            "payment_intent_id": f"pi_mock_{order.id}",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Payment provider error: {e}",
        )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Handle Stripe webhook events.

    Processes payment_intent.succeeded, payment_intent.payment_failed,
    and charge.refunded events.
    """
    payload = await request.body()

    try:
        import stripe

        stripe.api_key = settings.stripe_secret_key

        if settings.stripe_webhook_secret:
            sig_header = request.headers.get("stripe-signature", "")
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.stripe_webhook_secret
            )
        else:
            import json

            event = json.loads(payload)
    except ImportError:
        import json

        event = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "payment_intent.succeeded":
        payment_intent_id = data.get("id")
        result = await db.execute(
            select(Order).where(Order.stripe_payment_intent_id == payment_intent_id)
        )
        order = result.scalar_one_or_none()
        if order:
            order.status = "paid"
            await db.flush()

    elif event_type == "payment_intent.payment_failed":
        payment_intent_id = data.get("id")
        result = await db.execute(
            select(Order).where(Order.stripe_payment_intent_id == payment_intent_id)
        )
        order = result.scalar_one_or_none()
        if order:
            order.status = "cancelled"
            await db.flush()

    elif event_type == "charge.refunded":
        payment_intent_id = data.get("payment_intent")
        result = await db.execute(
            select(Order).where(Order.stripe_payment_intent_id == payment_intent_id)
        )
        order = result.scalar_one_or_none()
        if order:
            order.status = "cancelled"
            await db.flush()

    return {"status": "ok"}
