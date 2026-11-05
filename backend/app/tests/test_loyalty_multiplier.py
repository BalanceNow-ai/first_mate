"""Monthly crew multiplier: spec tiers, NZ month boundaries, idempotent reruns."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.database import async_session
from app.models.loyalty import PointsTransaction
from app.services import loyalty
from app.tasks import loyalty as loyalty_tasks
from app.tests.conftest import create_actor
from app.tests.test_loyalty_support import make_crew, make_order, paid_order, refund

P = "/api/v1/loyalty"


@pytest.mark.parametrize(
    ("spend", "mult"),
    [
        (0, 1.0),
        (49_999, 1.0),
        (50_000, 1.25),
        (99_999, 1.25),
        (100_000, 1.5),
        (199_999, 1.5),
        (200_000, 2.0),
        (499_999, 2.0),
        (500_000, 3.0),
        (10_000_000, 3.0),
    ],
)
def test_multiplier_table(spend, mult):
    assert loyalty.multiplier_for(spend) == mult


async def _bonuses(period=None):
    async with async_session() as s:
        q = select(PointsTransaction).where(PointsTransaction.kind == "monthly_bonus")
        if period:
            q = q.where(PointsTransaction.period == period)
        return {(r.user_id, r.period): r.points for r in (await s.execute(q)).scalars()}


async def test_bonus_by_tier_and_nz_month_boundary(customer, other_customer):
    team = await make_crew(customer.id, other_customer.id)
    # 2026-03-31T11:30Z is already April in Pacific/Auckland.
    await paid_order(customer.id, subtotal_cents=30_000, paid_at=datetime(2026, 3, 31, 11, 30, tzinfo=UTC))
    await paid_order(other_customer.id, subtotal_cents=25_000, paid_at=datetime(2026, 4, 10, 2, 0, tzinfo=UTC))
    # March (NZ): $1,000 by the captain alone.
    await paid_order(customer.id, subtotal_cents=100_000, paid_at=datetime(2026, 3, 31, 10, 30, tzinfo=UTC))
    # An unpaid April order must not lift the crew into a higher tier.
    await make_order(
        other_customer.id,
        subtotal_cents=900_000,
        payment_status="unpaid",
        status="pending_payment",
        paid_at=datetime(2026, 4, 11, tzinfo=UTC),
    )

    async with async_session() as s:
        april = await loyalty.calculate_monthly_multipliers(s, "2026-04")
        march = await loyalty.calculate_monthly_multipliers(s, "2026-03")
        await s.commit()
    assert april == {"period": "2026-04", "crews": 1, "bonuses_awarded": 2, "points_awarded": 75 + 62}
    assert march["points_awarded"] == 500
    bonuses = await _bonuses()
    # April: $550 -> 1.25x. 300 * 0.25 = 75; 250 * 0.25 = 62.5 -> 62.
    assert bonuses[(customer.id, "2026-04")] == 75
    assert bonuses[(other_customer.id, "2026-04")] == 62
    # March: $1,000 -> 1.5x on the captain's 1,000 base points.
    assert bonuses[(customer.id, "2026-03")] == 500
    async with async_session() as s:
        keys = {
            r.idempotency_key
            for r in (
                await s.execute(select(PointsTransaction).where(PointsTransaction.kind == "monthly_bonus"))
            ).scalars()
        }
    assert f"bonus:{team}:{customer.id}:2026-04" in keys


async def test_rerun_via_celery_task_is_idempotent(customer, other_customer):
    await make_crew(customer.id, other_customer.id)
    when = datetime(2026, 6, 15, tzinfo=UTC)
    await paid_order(customer.id, subtotal_cents=150_000, paid_at=when)
    await paid_order(other_customer.id, subtotal_cents=60_000, paid_at=when)  # $2,100 -> 2.0x
    first = await asyncio.to_thread(loyalty_tasks.calculate_monthly_multipliers.run, "2026-06")
    second = await asyncio.to_thread(loyalty_tasks.calculate_monthly_multipliers.run, "2026-06")
    assert first["points_awarded"] == 1500 + 600
    assert second["bonuses_awarded"] == 0 and second["points_awarded"] == 0
    assert await _bonuses("2026-06") == {(customer.id, "2026-06"): 1500, (other_customer.id, "2026-06"): 600}


async def test_solo_crew_and_no_crew_earn_no_multiplier(customer, other_customer):
    await make_crew(customer.id)  # one member only
    when = datetime(2026, 7, 2, tzinfo=UTC)
    await paid_order(customer.id, subtotal_cents=600_000, paid_at=when)
    await paid_order(other_customer.id, subtotal_cents=600_000, paid_at=when)  # not in a crew
    async with async_session() as s:
        summary = await loyalty.calculate_monthly_multipliers(s, "2026-07")
        await s.commit()
    assert summary["bonuses_awarded"] == 0
    assert await _bonuses() == {}


async def test_refund_reduces_crew_spend_and_bonus_base(customer, other_customer):
    await make_crew(customer.id, other_customer.id)
    when = datetime(2026, 8, 3, tzinfo=UTC)
    big = await paid_order(customer.id, subtotal_cents=40_000, paid_at=when)
    await paid_order(other_customer.id, subtotal_cents=20_000, paid_at=when)  # $600 -> 1.25x
    await refund(big.id, 20_000)  # captain's net $200 -> crew $400 -> 1.0x
    async with async_session() as s:
        summary = await loyalty.calculate_monthly_multipliers(s, "2026-08")
        await s.commit()
    assert summary["points_awarded"] == 0


async def test_default_period_is_previous_nz_month():
    assert loyalty.previous_period(datetime(2026, 11, 30, 11, 30, tzinfo=UTC)) == "2026-11"  # Dec 1 00:30 NZDT


async def test_multiplier_progress_endpoint(client, customer):
    other = await create_actor("customer")
    await make_crew(customer.id, other.id)
    await paid_order(customer.id, subtotal_cents=45_000)
    await paid_order(other.id, subtotal_cents=10_000)
    await make_order(other.id, subtotal_cents=500_000, payment_status="unpaid", status="pending_payment")
    body = (await client.get(f"{P}/multiplier", headers=customer.headers)).json()
    assert body["crew_spend_cents"] == 55_000
    assert body["member_count"] == 2 and body["eligible_for_multiplier"] is True
    assert body["current_multiplier"] == 1.25
    assert body["next_threshold_cents"] == 100_000 and body["next_multiplier"] == 1.5
    assert body["remaining_to_next_cents"] == 45_000
    assert body["period"] == loyalty.current_period()


async def test_admin_can_run_multipliers_customer_cannot(client, customer, admin):
    r = await client.post(f"{P}/admin/multipliers/run", json={"period": "2026-01"}, headers=customer.headers)
    assert r.status_code == 403
    r = await client.post(f"{P}/admin/multipliers/run", json={"period": "2026-01"}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["period"] == "2026-01"
