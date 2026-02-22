"""Tests for the Voyage Checklist API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_generate_checklists(client: AsyncClient, test_user, test_vessel):
    """Test generating default voyage checklists for a vessel."""
    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    assert response.status_code == 201
    data = response.json()
    assert data["message"] == "Checklists generated"
    assert len(data["checklists"]) == 3

    tiers = {c["tier"] for c in data["checklists"]}
    assert "grab_and_go" in tiers
    assert "coastal_cruising" in tiers
    assert "offshore_passage" in tiers


@pytest.mark.asyncio
async def test_get_vessel_checklists(client: AsyncClient, test_user, test_vessel):
    """Test retrieving checklists for a vessel."""
    # Generate first
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")

    response = await client.get(f"/api/v1/checklists/vessel/{test_vessel.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3

    # Verify items exist
    grab_and_go = next(c for c in data if c["tier"] == "grab_and_go")
    assert len(grab_and_go["items"]) > 0


@pytest.mark.asyncio
async def test_duplicate_generate_fails(client: AsyncClient, test_user, test_vessel):
    """Test that generating checklists twice fails."""
    await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    response = await client.post(f"/api/v1/checklists/vessel/{test_vessel.id}/generate")
    assert response.status_code == 409
