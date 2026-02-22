"""Tests for the Shipping rates API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_calculate_shipping_rates(client: AsyncClient):
    """Test getting shipping rates from both providers."""
    response = await client.post(
        "/api/v1/shipping/rates",
        json={
            "destination_postcode": "1010",
            "weight_grams": 2000,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["rates"]) == 2
    assert data["cheapest"] is not None

    providers = {r["provider"] for r in data["rates"]}
    assert "nz_post" in providers
    assert "aramex" in providers


@pytest.mark.asyncio
async def test_shipping_rates_light_parcel(client: AsyncClient):
    """Test shipping rates for a light parcel (under 1kg)."""
    response = await client.post(
        "/api/v1/shipping/rates",
        json={
            "destination_postcode": "6011",
            "weight_grams": 500,
        },
    )
    assert response.status_code == 200
    data = response.json()
    # Light parcels should be cheaper
    for rate in data["rates"]:
        assert rate["price_nzd"] < 20.0


@pytest.mark.asyncio
async def test_shipping_rates_heavy_parcel(client: AsyncClient):
    """Test shipping rates for a heavy parcel (over 15kg)."""
    response = await client.post(
        "/api/v1/shipping/rates",
        json={
            "destination_postcode": "7610",
            "weight_grams": 20000,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cheapest"]["price_nzd"] > 0
