"""Tests for the new product catalogue endpoints (categories, brands, on_sale filter)."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


@pytest.mark.asyncio
async def test_list_categories(client: AsyncClient, db_session: AsyncSession, test_product):
    """Should return distinct product categories."""
    response = await client.get("/api/v1/products/categories")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert "Engine Parts" in data


@pytest.mark.asyncio
async def test_list_categories_empty(client: AsyncClient, db_session: AsyncSession):
    """Should return empty list when no products exist."""
    response = await client.get("/api/v1/products/categories")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_brands(client: AsyncClient, db_session: AsyncSession, test_product):
    """Should return distinct product brands."""
    response = await client.get("/api/v1/products/brands")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert "Yamaha" in data


@pytest.mark.asyncio
async def test_list_brands_multiple(client: AsyncClient, db_session: AsyncSession, test_product):
    """Should return multiple brands when multiple exist."""
    # Add a second product with a different brand
    product2 = Product(
        sku="MER-PROP-001",
        name="Mercury Propeller",
        brand="Mercury",
        category="Propellers",
        price=350.00,
        stock_quantity=10,
    )
    db_session.add(product2)
    await db_session.commit()

    response = await client.get("/api/v1/products/brands")
    assert response.status_code == 200
    data = response.json()
    assert "Yamaha" in data
    assert "Mercury" in data


@pytest.mark.asyncio
async def test_on_sale_filter(client: AsyncClient, db_session: AsyncSession):
    """Should filter products that are on sale."""
    # Create a product on sale
    product_sale = Product(
        sku="SALE-001",
        name="Sale Anchor",
        brand="Test",
        category="Anchors",
        price=100.00,
        sale_price=79.95,
        stock_quantity=5,
    )
    # Create a product not on sale
    product_regular = Product(
        sku="REG-001",
        name="Regular Rope",
        brand="Test",
        category="Ropes",
        price=50.00,
        stock_quantity=20,
    )
    db_session.add_all([product_sale, product_regular])
    await db_session.commit()

    response = await client.get("/api/v1/products/", params={"on_sale": True})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Sale Anchor"
    assert data[0]["sale_price"] == 79.95
