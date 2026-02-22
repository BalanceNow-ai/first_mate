"""Tests for the Vessel (My Vessel Garage) API."""

import pytest
from httpx import AsyncClient

from app.models.vessel import Vessel
from app.tests.conftest import TEST_USER_ID


@pytest.mark.asyncio
async def test_create_vessel(client: AsyncClient, test_user):
    """Test creating a new vessel."""
    response = await client.post(
        "/api/v1/vessels/",
        json={
            "nickname": "My Stabi",
            "make": "Stabicraft",
            "model": "2250 Ultracab",
            "year": 2022,
            "hull_type": "aluminium",
            "engine_make": "Yamaha",
            "engine_model": "F200XCA",
            "engine_hours": 150,
            "is_primary": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["nickname"] == "My Stabi"
    assert data["make"] == "Stabicraft"
    assert data["model"] == "2250 Ultracab"
    assert data["year"] == 2022
    assert data["engine_make"] == "Yamaha"
    assert data["is_primary"] is True


@pytest.mark.asyncio
async def test_list_vessels(client: AsyncClient, test_user, test_vessel):
    """Test listing all vessels in the user's garage."""
    response = await client.get("/api/v1/vessels/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["nickname"] == "My Stabi"


@pytest.mark.asyncio
async def test_get_vessel(client: AsyncClient, test_user, test_vessel):
    """Test getting a specific vessel."""
    response = await client.get(f"/api/v1/vessels/{test_vessel.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["nickname"] == "My Stabi"
    assert data["make"] == "Stabicraft"


@pytest.mark.asyncio
async def test_update_vessel(client: AsyncClient, test_user, test_vessel):
    """Test updating a vessel."""
    response = await client.patch(
        f"/api/v1/vessels/{test_vessel.id}",
        json={"engine_hours": 200, "nickname": "The Beast"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["engine_hours"] == 200
    assert data["nickname"] == "The Beast"


@pytest.mark.asyncio
async def test_delete_vessel(client: AsyncClient, test_user, test_vessel):
    """Test deleting a vessel."""
    response = await client.delete(f"/api/v1/vessels/{test_vessel.id}")
    assert response.status_code == 204

    # Verify it's gone
    response = await client.get(f"/api/v1/vessels/{test_vessel.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_nickname_is_required(client: AsyncClient, test_user):
    """Test that nickname is a required field."""
    response = await client.post(
        "/api/v1/vessels/",
        json={
            "make": "Stabicraft",
            "model": "2250 Ultracab",
            "year": 2022,
        },
    )
    assert response.status_code == 422  # Validation error


@pytest.mark.asyncio
async def test_vessel_not_found(client: AsyncClient, test_user):
    """Test getting a non-existent vessel returns 404."""
    import uuid

    response = await client.get(f"/api/v1/vessels/{uuid.uuid4()}")
    assert response.status_code == 404
