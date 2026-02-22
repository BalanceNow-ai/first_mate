"""Tests for product images as list[str] instead of dict."""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


@pytest.mark.asyncio
async def test_product_with_image_list(client: AsyncClient, db_session: AsyncSession):
    """Products should accept and return images as a list of URL strings."""
    product = Product(
        sku="TEST-IMG-001",
        name="Multi-Image Product",
        category="Safety",
        price=99.99,
        stock_quantity=10,
        images=[
            "https://cdn.helmmarine.co.nz/products/img1.jpg",
            "https://cdn.helmmarine.co.nz/products/img2.jpg",
            "https://cdn.helmmarine.co.nz/products/img3.jpg",
        ],
    )
    db_session.add(product)
    await db_session.commit()

    response = await client.get(f"/api/v1/products/{product.id}")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["images"], list)
    assert len(data["images"]) == 3
    assert data["images"][0] == "https://cdn.helmmarine.co.nz/products/img1.jpg"


@pytest.mark.asyncio
async def test_product_with_no_images(client: AsyncClient, db_session: AsyncSession):
    """Products with no images should return null."""
    product = Product(
        sku="TEST-IMG-002",
        name="No Image Product",
        category="Electronics",
        price=49.99,
        stock_quantity=5,
    )
    db_session.add(product)
    await db_session.commit()

    response = await client.get(f"/api/v1/products/{product.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["images"] is None


@pytest.mark.asyncio
async def test_create_product_with_images(client: AsyncClient, db_session: AsyncSession):
    """Creating a product with images list should persist them."""
    response = await client.post(
        "/api/v1/products/",
        json={
            "sku": "TEST-IMG-003",
            "name": "Created With Images",
            "category": "Navigation",
            "price": 199.99,
            "images": [
                "https://cdn.helmmarine.co.nz/nav/img1.jpg",
                "https://cdn.helmmarine.co.nz/nav/img2.jpg",
            ],
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert isinstance(data["images"], list)
    assert len(data["images"]) == 2
