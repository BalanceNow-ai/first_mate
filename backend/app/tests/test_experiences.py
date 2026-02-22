"""Tests for the Signature Experiences endpoint and redemption validation."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loyalty import CrewPoints
from app.routers.loyalty import DEFAULT_EXPERIENCES
from app.schemas.loyalty import SignatureExperience
from app.tests.conftest import TEST_USER_ID


@pytest.mark.asyncio
async def test_get_experiences_returns_defaults(client: AsyncClient):
    """When Strapi is unavailable, default experiences are returned."""
    response = await client.get("/api/v1/loyalty/experiences")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    assert data[0]["title"] == "Harbour Cruise"
    assert data[1]["title"] == "Fishing Charter"
    assert data[2]["title"] == "Marine Detailing"


@pytest.mark.asyncio
async def test_get_experiences_has_required_fields(client: AsyncClient):
    """Each experience should have id, title, description, cost_cp."""
    response = await client.get("/api/v1/loyalty/experiences")
    assert response.status_code == 200
    data = response.json()
    for exp in data:
        assert "id" in exp
        assert "title" in exp
        assert "description" in exp
        assert "cost_cp" in exp
        assert exp["cost_cp"] > 0


@pytest.mark.asyncio
async def test_get_experiences_from_strapi(client: AsyncClient):
    """When Strapi responds, its data should be returned."""
    strapi_experiences = [
        SignatureExperience(
            id="1",
            title="Whale Watching",
            description="See whales in the Kaikoura coast",
            cost_cp=12000,
            location="Kaikoura",
            duration_hours=5.0,
            available=True,
        )
    ]

    with patch(
        "app.routers.loyalty._fetch_experiences_from_strapi",
        new_callable=AsyncMock,
        return_value=strapi_experiences,
    ):
        response = await client.get("/api/v1/loyalty/experiences")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Whale Watching"
        assert data[0]["cost_cp"] == 12000


@pytest.mark.asyncio
async def test_redeem_experience_requires_id(client: AsyncClient, db_session: AsyncSession, test_user):
    """Redemption type 'experience' requires experience_id."""
    # Create points balance
    points = CrewPoints(user_id=TEST_USER_ID, points_balance=10000, tier="bosun")
    db_session.add(points)
    await db_session.commit()

    response = await client.post(
        "/api/v1/loyalty/points/redeem",
        json={"points": 5000, "redemption_type": "experience"},
    )
    assert response.status_code == 400
    assert "experience_id is required" in response.json()["detail"]


@pytest.mark.asyncio
async def test_redeem_experience_not_found(client: AsyncClient, db_session: AsyncSession, test_user):
    """Redemption should fail if experience ID is not in the catalogue."""
    points = CrewPoints(user_id=TEST_USER_ID, points_balance=10000, tier="bosun")
    db_session.add(points)
    await db_session.commit()

    fake_id = str(uuid.uuid4())
    response = await client.post(
        "/api/v1/loyalty/points/redeem",
        json={
            "points": 5000,
            "redemption_type": "experience",
            "experience_id": fake_id,
        },
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_redeem_experience_insufficient_points(client: AsyncClient, db_session: AsyncSession, test_user):
    """Redemption should fail when user doesn't have enough points for the experience cost."""
    points = CrewPoints(user_id=TEST_USER_ID, points_balance=100, tier="deckhand")
    db_session.add(points)
    await db_session.commit()

    # Use the default Harbour Cruise (5000 CP)
    response = await client.post(
        "/api/v1/loyalty/points/redeem",
        json={
            "points": 100,
            "redemption_type": "experience",
            "experience_id": "exp-harbour-cruise",
        },
    )
    assert response.status_code == 400
    assert "Insufficient points" in response.json()["detail"]


@pytest.mark.asyncio
async def test_redeem_experience_success(client: AsyncClient, db_session: AsyncSession, test_user):
    """Successful experience redemption deducts cost_cp from balance."""
    points = CrewPoints(user_id=TEST_USER_ID, points_balance=20000, tier="captain")
    db_session.add(points)
    await db_session.commit()

    response = await client.post(
        "/api/v1/loyalty/points/redeem",
        json={
            "points": 5000,
            "redemption_type": "experience",
            "experience_id": "exp-harbour-cruise",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["redeemed_points"] == 5000
    assert data["experience_id"] == "exp-harbour-cruise"
    assert data["experience_title"] == "Harbour Cruise"
    assert data["remaining_balance"] == 15000


@pytest.mark.asyncio
async def test_redeem_product_discount_still_works(client: AsyncClient, db_session: AsyncSession, test_user):
    """Product discount redemption should still work correctly."""
    points = CrewPoints(user_id=TEST_USER_ID, points_balance=1000, tier="crew")
    db_session.add(points)
    await db_session.commit()

    response = await client.post(
        "/api/v1/loyalty/points/redeem",
        json={"points": 500, "redemption_type": "product_discount"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["redeemed_points"] == 500
    assert data["discount_nzd"] == 5.0
    assert data["remaining_balance"] == 500
