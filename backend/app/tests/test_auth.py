"""Tests for authentication and authorization."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import TEST_USER_ID, TestSessionLocal
from app.models.user import User
from app.models.vessel import Vessel


OTHER_USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


@pytest.fixture
async def other_user_vessel(db_session: AsyncSession) -> Vessel:
    """Create a vessel owned by a different user."""
    other_user = User(
        id=OTHER_USER_ID,
        email="other@helm.co.nz",
        full_name="Other User",
    )
    db_session.add(other_user)
    await db_session.flush()

    vessel = Vessel(
        user_id=OTHER_USER_ID,
        nickname="Not My Boat",
        make="Rayglass",
        model="Legend 2500",
        year=2021,
        is_primary=True,
    )
    db_session.add(vessel)
    await db_session.commit()
    return vessel


@pytest.mark.asyncio
async def test_cannot_access_other_users_vessel(
    client: AsyncClient, test_user, other_user_vessel
):
    """Verify that a user cannot access vessels owned by another user.

    The authenticated user (TEST_USER_ID) should get a 404 when trying to
    access a vessel that belongs to OTHER_USER_ID, because the vessel query
    filters by both vessel_id AND user_id.
    """
    response = await client.get(f"/api/v1/vessels/{other_user_vessel.id}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Vessel not found"


@pytest.mark.asyncio
async def test_cannot_update_other_users_vessel(
    client: AsyncClient, test_user, other_user_vessel
):
    """Verify that a user cannot update another user's vessel."""
    response = await client.patch(
        f"/api/v1/vessels/{other_user_vessel.id}",
        json={"nickname": "Hijacked Boat"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_cannot_delete_other_users_vessel(
    client: AsyncClient, test_user, other_user_vessel
):
    """Verify that a user cannot delete another user's vessel."""
    response = await client.delete(f"/api/v1/vessels/{other_user_vessel.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_vessels_only_returns_own(
    client: AsyncClient, test_user, test_vessel, other_user_vessel
):
    """Verify that listing vessels only returns the authenticated user's vessels."""
    response = await client.get("/api/v1/vessels/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["nickname"] == "My Stabi"
    # Ensure the other user's vessel is not in the list
    vessel_ids = [v["id"] for v in data]
    assert str(other_user_vessel.id) not in vessel_ids


@pytest.mark.asyncio
async def test_request_without_token_returns_403():
    """Verify that a request without an Authorization header is rejected.

    We temporarily remove the mock auth override so the real HTTPBearer
    dependency runs, which rejects requests without a Bearer token.
    """
    from app.main import app
    from app.middleware.auth import get_current_user_id
    from app.database import get_db

    # Save and remove the mock override so real auth runs
    saved_override = app.dependency_overrides.pop(get_current_user_id, None)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as no_auth_client:
            response = await no_auth_client.get("/api/v1/vessels/")
            # HTTPBearer returns 403 (Not Authenticated) when no token is
            # provided, or 401 if the auth dependency itself raises it.
            assert response.status_code in (401, 403)
    finally:
        # Restore the mock so other tests are unaffected
        if saved_override:
            app.dependency_overrides[get_current_user_id] = saved_override
