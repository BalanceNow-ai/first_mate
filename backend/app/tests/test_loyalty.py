"""Tests for the Crew Rewards loyalty API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_points_auto_creates(client: AsyncClient, test_user):
    """Test that getting points auto-creates a record for new users."""
    response = await client.get("/api/v1/loyalty/points")
    assert response.status_code == 200
    data = response.json()
    assert data["points_balance"] == 0
    assert data["tier"] == "deckhand"


@pytest.mark.asyncio
async def test_create_crew_team(client: AsyncClient, test_user):
    """Test creating a new crew team."""
    response = await client.post(
        "/api/v1/loyalty/teams",
        json={"name": "The Stabi Crew"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "The Stabi Crew"
    assert data["member_count"] == 1  # Creator is auto-added


@pytest.mark.asyncio
async def test_list_teams(client: AsyncClient, test_user):
    """Test listing the user's crew teams."""
    # Create a team first
    await client.post(
        "/api/v1/loyalty/teams",
        json={"name": "Weekend Warriors"},
    )

    response = await client.get("/api/v1/loyalty/teams")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Weekend Warriors"


@pytest.mark.asyncio
async def test_redeem_insufficient_points(client: AsyncClient, test_user):
    """Test that redeeming more points than available fails."""
    # First, get points (auto-creates with 0 balance)
    await client.get("/api/v1/loyalty/points")

    response = await client.post(
        "/api/v1/loyalty/points/redeem",
        json={"points": 1000, "redemption_type": "product_discount"},
    )
    assert response.status_code == 400
    assert "insufficient" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_multiplier(client: AsyncClient, test_user):
    """Test getting the current points multiplier."""
    response = await client.get("/api/v1/loyalty/multiplier")
    assert response.status_code == 200
    data = response.json()
    assert data["multiplier"] == 1.0  # Base rate with no spend
