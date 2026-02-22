"""Tests for the Product catalogue API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_product(client: AsyncClient, test_user):
    """Test creating a new product."""
    response = await client.post(
        "/api/v1/products/",
        json={
            "sku": "TEST-SKU-001",
            "name": "Test Marine Product",
            "description": "A test product for testing",
            "brand": "TestBrand",
            "category": "Engine Parts",
            "sub_category": "Filters",
            "price": 29.90,
            "stock_quantity": 100,
            "weight_grams": 500,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["sku"] == "TEST-SKU-001"
    assert data["name"] == "Test Marine Product"
    assert data["price"] == 29.90


@pytest.mark.asyncio
async def test_list_products(client: AsyncClient, test_product):
    """Test listing products."""
    response = await client.get("/api/v1/products/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


@pytest.mark.asyncio
async def test_get_product(client: AsyncClient, test_product):
    """Test getting a single product."""
    response = await client.get(f"/api/v1/products/{test_product.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["sku"] == "YAM-OIL-10W30-4L"
    assert data["brand"] == "Yamaha"


@pytest.mark.asyncio
async def test_filter_products_by_category(client: AsyncClient, test_product):
    """Test filtering products by category."""
    response = await client.get("/api/v1/products/?category=Engine+Parts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(p["category"] == "Engine Parts" for p in data)


@pytest.mark.asyncio
async def test_filter_products_by_brand(client: AsyncClient, test_product):
    """Test filtering products by brand."""
    response = await client.get("/api/v1/products/?brand=Yamaha")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert all(p["brand"] == "Yamaha" for p in data)


@pytest.mark.asyncio
async def test_check_product_compatibility(client: AsyncClient, test_product, test_vessel):
    """Test checking product compatibility with a vessel."""
    response = await client.get(
        f"/api/v1/products/{test_product.id}/check-compatibility?vessel_id={test_vessel.id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_compatible"] is True
    assert "Fits" in data["message"]


@pytest.mark.asyncio
async def test_product_not_found(client: AsyncClient):
    """Test getting a non-existent product returns 404."""
    import uuid

    response = await client.get(f"/api/v1/products/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_products(client: AsyncClient, test_product):
    """Test searching products by name."""
    response = await client.get("/api/v1/products/?search=Yamalube")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
