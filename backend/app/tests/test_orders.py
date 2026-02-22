"""Tests for the Orders API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_order_empty_cart(client: AsyncClient, test_user):
    """Test that creating an order with an empty cart fails."""
    response = await client.post(
        "/api/v1/orders/",
        json={"delivery_type": "courier", "shipping_address": {"city": "Auckland"}},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_order_from_cart(client: AsyncClient, test_user, test_product):
    """Test creating an order from cart items."""
    # Add item to cart
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(test_product.id), "quantity": 2},
    )

    # Create order
    response = await client.post(
        "/api/v1/orders/",
        json={
            "delivery_type": "courier",
            "shipping_address": {
                "street": "123 Marine Parade",
                "city": "Auckland",
                "postcode": "1010",
            },
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["delivery_type"] == "courier"
    assert len(data["items"]) == 1
    assert data["items"][0]["quantity"] == 2
    assert float(data["subtotal"]) == 125.80  # 62.90 * 2
    assert float(data["shipping_cost"]) == 9.90  # Under $150 threshold, shipping applies

    # Verify cart is now empty
    cart_response = await client.get("/api/v1/cart/")
    assert cart_response.json()["items"] == []


@pytest.mark.asyncio
async def test_list_orders(client: AsyncClient, test_user, test_product):
    """Test listing orders."""
    # Add item and create order
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(test_product.id), "quantity": 1},
    )
    await client.post(
        "/api/v1/orders/",
        json={"delivery_type": "courier"},
    )

    response = await client.get("/api/v1/orders/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
