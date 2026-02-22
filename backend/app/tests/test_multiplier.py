"""Tests for the crew points multiplier calculation."""

import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loyalty import CrewTeam, CrewTeamMember
from app.models.order import Order
from app.tests.conftest import TEST_USER_ID


@pytest.mark.asyncio
async def test_multiplier_no_team_no_orders(client: AsyncClient, db_session: AsyncSession):
    """User with no team and no orders should get base 1.0 multiplier."""
    response = await client.get("/api/v1/loyalty/multiplier")
    assert response.status_code == 200
    data = response.json()
    assert data["multiplier"] == 1.0
    assert data["monthly_spend"] == 0.0


@pytest.mark.asyncio
async def test_multiplier_solo_with_orders(client: AsyncClient, db_session: AsyncSession, test_user):
    """User with no team but with orders should have solo spend counted."""
    # Create an order for this month
    order = Order(
        user_id=TEST_USER_ID,
        status="paid",
        subtotal=600.00,
        shipping_cost=10.00,
        total=610.00,
        created_at=datetime.utcnow(),
    )
    db_session.add(order)
    await db_session.commit()

    response = await client.get("/api/v1/loyalty/multiplier")
    assert response.status_code == 200
    data = response.json()
    assert data["monthly_spend"] == 610.0
    assert data["multiplier"] == 1.25  # $610 >= $500 tier


@pytest.mark.asyncio
async def test_multiplier_team_collective_spend(client: AsyncClient, db_session: AsyncSession, test_user):
    """Crew team with collective spend should get higher multiplier."""
    # Create a crew team
    team = CrewTeam(name="Ocean Crew", created_by=TEST_USER_ID)
    db_session.add(team)
    await db_session.flush()

    # Add the test user as a member
    member1 = CrewTeamMember(team_id=team.id, user_id=TEST_USER_ID)
    db_session.add(member1)

    # Add a second member
    member2_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    member2 = CrewTeamMember(team_id=team.id, user_id=member2_id)
    db_session.add(member2)
    await db_session.flush()

    # Create orders — user 1 spends $800, user 2 spends $700 = $1500 total
    order1 = Order(
        user_id=TEST_USER_ID,
        status="paid",
        subtotal=800.00,
        shipping_cost=0,
        total=800.00,
        created_at=datetime.utcnow(),
    )
    order2 = Order(
        user_id=member2_id,
        status="paid",
        subtotal=700.00,
        shipping_cost=0,
        total=700.00,
        created_at=datetime.utcnow(),
    )
    db_session.add_all([order1, order2])
    await db_session.commit()

    response = await client.get("/api/v1/loyalty/multiplier")
    assert response.status_code == 200
    data = response.json()
    assert data["monthly_spend"] == 1500.0
    assert data["multiplier"] == 1.5  # $1500 >= $1000 tier


@pytest.mark.asyncio
async def test_multiplier_cancelled_orders_excluded(client: AsyncClient, db_session: AsyncSession, test_user):
    """Cancelled orders should not count toward the monthly spend."""
    order = Order(
        user_id=TEST_USER_ID,
        status="cancelled",
        subtotal=5000.00,
        shipping_cost=0,
        total=5000.00,
        created_at=datetime.utcnow(),
    )
    db_session.add(order)
    await db_session.commit()

    response = await client.get("/api/v1/loyalty/multiplier")
    assert response.status_code == 200
    data = response.json()
    assert data["monthly_spend"] == 0.0
    assert data["multiplier"] == 1.0


@pytest.mark.asyncio
async def test_multiplier_top_tier(client: AsyncClient, db_session: AsyncSession, test_user):
    """$5000+ spend should get 3.0x multiplier."""
    # Create a crew team
    team = CrewTeam(name="Big Spenders", created_by=TEST_USER_ID)
    db_session.add(team)
    await db_session.flush()

    member = CrewTeamMember(team_id=team.id, user_id=TEST_USER_ID)
    db_session.add(member)

    order = Order(
        user_id=TEST_USER_ID,
        status="paid",
        subtotal=5500.00,
        shipping_cost=0,
        total=5500.00,
        created_at=datetime.utcnow(),
    )
    db_session.add(order)
    await db_session.commit()

    response = await client.get("/api/v1/loyalty/multiplier")
    assert response.status_code == 200
    data = response.json()
    assert data["monthly_spend"] == 5500.0
    assert data["multiplier"] == 3.0
