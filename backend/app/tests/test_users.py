"""Tests for the User Profile API."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_get_profile(client: AsyncClient, test_user):
    """Test retrieving the current user's profile."""
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "skipper@helm.co.nz"
    assert data["full_name"] == "Test Skipper"


@pytest.mark.asyncio
async def test_update_profile_full_name(client: AsyncClient, test_user):
    """Test updating the user's full name."""
    response = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "Captain Hook"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Captain Hook"
    assert data["email"] == "skipper@helm.co.nz"


@pytest.mark.asyncio
async def test_update_profile_phone(client: AsyncClient, test_user):
    """Test updating the user's phone number."""
    response = await client.patch(
        "/api/v1/users/me",
        json={"phone": "+64210001234"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["phone"] == "+64210001234"


@pytest.mark.asyncio
async def test_update_profile_partial(client: AsyncClient, test_user):
    """Only specified fields should be updated."""
    # Set phone first
    await client.patch("/api/v1/users/me", json={"phone": "+64211111111"})

    # Update only full_name, phone should remain
    response = await client.patch(
        "/api/v1/users/me",
        json={"full_name": "New Name"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "New Name"
    assert data["phone"] == "+64211111111"


@pytest.mark.asyncio
async def test_list_orders_empty(client: AsyncClient, test_user):
    """Test listing orders when there are none."""
    response = await client.get("/api/v1/orders/")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_orders_with_order(client: AsyncClient, test_user, test_product):
    """Test listing orders returns created orders."""
    # Add to cart
    await client.post("/api/v1/cart/items", json={
        "product_id": str(test_product.id),
        "quantity": 1,
    })

    # Create order
    order_resp = await client.post("/api/v1/orders/", json={
        "delivery_type": "courier",
    })
    assert order_resp.status_code == 201

    # List orders
    response = await client.get("/api/v1/orders/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "pending"
    assert data[0]["delivery_type"] == "courier"


@pytest.mark.asyncio
async def test_list_orders_ordered_by_date(
    client: AsyncClient, test_user, test_product, db_session: AsyncSession
):
    """Orders should be returned newest first."""
    # Create two orders by adding to cart and ordering twice
    for _ in range(2):
        # Re-stock
        test_product.stock_quantity = 50
        await db_session.commit()

        await client.post("/api/v1/cart/items", json={
            "product_id": str(test_product.id),
            "quantity": 1,
        })
        await client.post("/api/v1/orders/", json={"delivery_type": "courier"})

    response = await client.get("/api/v1/orders/")
    data = response.json()
    assert len(data) == 2
    # Most recent first
    if data[0]["created_at"] and data[1]["created_at"]:
        assert data[0]["created_at"] >= data[1]["created_at"]
