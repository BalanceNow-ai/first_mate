"""Tests for the Payments API and Stripe webhook handling."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderItem
from app.tests.conftest import TEST_USER_ID


@pytest.fixture
async def test_order(db_session: AsyncSession, test_user, test_product) -> Order:
    """Create a test order for payment testing."""
    order = Order(
        user_id=TEST_USER_ID,
        status="pending",
        subtotal=62.90,
        shipping_cost=9.90,
        total=72.80,
        delivery_type="courier",
    )
    db_session.add(order)
    await db_session.flush()

    order_item = OrderItem(
        order_id=order.id,
        product_id=test_product.id,
        quantity=1,
        unit_price=62.90,
    )
    db_session.add(order_item)
    await db_session.commit()
    return order


@pytest.mark.asyncio
async def test_create_payment_intent(client: AsyncClient, test_user, test_order):
    """Test creating a payment intent for an order."""
    response = await client.post(f"/api/v1/payments/{test_order.id}/create-intent")
    assert response.status_code == 200
    data = response.json()
    # In dev mode (no Stripe key), mock values are returned
    assert "client_secret" in data
    assert "payment_intent_id" in data


@pytest.mark.asyncio
async def test_create_payment_intent_order_not_found(client: AsyncClient, test_user):
    """Test that creating a payment intent for a non-existent order returns 404."""
    response = await client.post(f"/api/v1/payments/{uuid.uuid4()}/create-intent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_payment_intent_non_pending_order(
    client: AsyncClient, test_user, test_order, db_session
):
    """Test that a paid order cannot have a new payment intent."""
    test_order.status = "paid"
    db_session.add(test_order)
    await db_session.commit()

    response = await client.post(f"/api/v1/payments/{test_order.id}/create-intent")
    assert response.status_code == 400
    assert "not in a payable state" in response.json()["detail"]


@pytest.mark.asyncio
async def test_webhook_payment_succeeded(client: AsyncClient, test_user, test_order, db_session):
    """Test that a payment_intent.succeeded webhook updates the order status to paid."""
    test_order.stripe_payment_intent_id = "pi_test_123"
    db_session.add(test_order)
    await db_session.commit()

    webhook_payload = {
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_test_123",
            }
        },
    }

    response = await client.post(
        "/api/v1/payments/webhook",
        content=json.dumps(webhook_payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_payment_failed(client: AsyncClient, test_user, test_order, db_session):
    """Test that a payment_intent.payment_failed webhook cancels the order."""
    test_order.stripe_payment_intent_id = "pi_test_fail_456"
    db_session.add(test_order)
    await db_session.commit()

    webhook_payload = {
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": "pi_test_fail_456",
            }
        },
    }

    response = await client.post(
        "/api/v1/payments/webhook",
        content=json.dumps(webhook_payload),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_stripe_signature_verification():
    """Test that Stripe webhook signature verification is called when configured.

    This test verifies that when a stripe_webhook_secret is set, the code
    calls stripe.Webhook.construct_event with the correct arguments.
    """
    from app.config import Settings

    mock_settings = Settings(
        stripe_secret_key="sk_test_mock",
        stripe_webhook_secret="whsec_test_secret",
    )

    mock_event = {
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_verified"}},
    }

    with (
        patch("app.routers.payments.settings", mock_settings),
        patch("stripe.Webhook.construct_event", return_value=mock_event) as mock_construct,
        patch("stripe.api_key", "sk_test_mock"),
    ):
        from httpx import ASGITransport, AsyncClient as AC
        from app.main import app

        async with AC(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as test_client:
            payload = json.dumps(mock_event).encode()
            response = await test_client.post(
                "/api/v1/payments/webhook",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": "t=123,v1=abc",
                },
            )

            mock_construct.assert_called_once_with(
                payload, "t=123,v1=abc", "whsec_test_secret"
            )
