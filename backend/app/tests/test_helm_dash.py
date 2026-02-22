"""Tests for the Helm Dash delivery API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_delivery_quote(client: AsyncClient):
    """Test getting a Helm Dash delivery quote."""
    response = await client.post(
        "/api/v1/helm-dash/quote",
        json={
            "delivery_lat": -36.8200,
            "delivery_lng": 174.8000,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["delivery_fee"] > 0
    assert data["estimated_minutes"] > 0
    assert data["nautical_miles"] > 0


@pytest.mark.asyncio
async def test_delivery_quote_nearby(client: AsyncClient):
    """Test that a nearby delivery has a lower fee."""
    # Near Westhaven Marina
    response = await client.post(
        "/api/v1/helm-dash/quote",
        json={
            "delivery_lat": -36.8420,
            "delivery_lng": 174.7550,
        },
    )
    data = response.json()
    assert data["nautical_miles"] < 1
    assert data["delivery_fee"] < 50  # Close to base fee


@pytest.mark.asyncio
async def test_delivery_quote_far(client: AsyncClient):
    """Test that a distant delivery has a higher fee."""
    # Waiheke Island
    response = await client.post(
        "/api/v1/helm-dash/quote",
        json={
            "delivery_lat": -36.7900,
            "delivery_lng": 175.0800,
        },
    )
    data = response.json()
    assert data["nautical_miles"] > 5
    assert data["delivery_fee"] > 50


@pytest.mark.asyncio
async def test_list_deliveries_empty(client: AsyncClient, test_user):
    """Test listing deliveries when none exist."""
    response = await client.get("/api/v1/helm-dash/deliveries")
    assert response.status_code == 200
    assert response.json() == []
