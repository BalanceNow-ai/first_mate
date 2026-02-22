"""Tests for the Shopping Cart API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_empty_cart(client: AsyncClient, test_user):
    """Test getting an empty cart."""
    response = await client.get("/api/v1/cart/")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["subtotal"] == 0
    assert data["item_count"] == 0


@pytest.mark.asyncio
async def test_add_to_cart(client: AsyncClient, test_user, test_product):
    """Test adding a product to the cart."""
    response = await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(test_product.id), "quantity": 2},
    )
    assert response.status_code == 201

    # Verify cart contents
    response = await client.get("/api/v1/cart/")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["quantity"] == 2
    assert data["item_count"] == 2


@pytest.mark.asyncio
async def test_add_duplicate_increments_quantity(client: AsyncClient, test_user, test_product):
    """Test that adding an existing product increments quantity."""
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(test_product.id), "quantity": 1},
    )
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(test_product.id), "quantity": 2},
    )

    response = await client.get("/api/v1/cart/")
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["quantity"] == 3


@pytest.mark.asyncio
async def test_clear_cart(client: AsyncClient, test_user, test_product):
    """Test clearing the entire cart."""
    await client.post(
        "/api/v1/cart/items",
        json={"product_id": str(test_product.id), "quantity": 1},
    )
    response = await client.delete("/api/v1/cart/")
    assert response.status_code == 204

    response = await client.get("/api/v1/cart/")
    data = response.json()
    assert data["items"] == []
