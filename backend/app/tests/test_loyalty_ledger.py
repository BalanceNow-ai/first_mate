"""Points ledger: earning once per paid order, refunds, shortfalls, bonuses, tiers."""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session
from app.models.loyalty import DiscountEntitlement, PointsTransaction
from app.models.loyalty import CrewPoints
from app.models.ops import AuditLog
from app.models.order import Order
from app.services import loyalty
from app.tests.test_loyalty_support import (
    balance,
    grant_points,
    make_order,
    paid_order,
    pay,
    refund,
    replay_refund_event,
)

P = "/api/v1/loyalty"


async def _ledger(user_id):
    async with async_session() as s:
        return list(
            (
                await s.execute(
                    select(PointsTransaction)
                    .where(PointsTransaction.user_id == user_id)
                    .order_by(PointsTransaction.created_at)
                )
            ).scalars()
        )


async def test_award_exactly_once_excluding_shipping(client, customer):
    # $123.45 subtotal - $10 discount + $9 shipping => eligible $113.45 => 113 CP
    order = await make_order(customer.id, subtotal_cents=12_345, discount_cents=1_000, shipping_cents=900)
    await pay(order)
    async with async_session() as s:  # second, direct call is a no-op
        await loyalty.award_for_paid_order(s, await s.get(Order, order.id))
        await s.commit()
    rows = await _ledger(customer.id)
    assert [(r.kind, r.points, r.balance_after, r.eligible_spend_cents) for r in rows] == [("earn", 113, 113, 11_345)]
    assert rows[0].idempotency_key == f"earn:{order.id}"
    body = (await client.get(f"{P}/points", headers=customer.headers)).json()
    assert body["points_balance"] == 113 and body["lifetime_earned"] == 113
    assert body["points_value_cents"] == 113 and body["tier"] == "deckhand" and body["tier_is_display_only"] is True
    page = (await client.get(f"{P}/transactions", headers=customer.headers)).json()
    assert page["total"] == 1 and page["items"][0]["kind"] == "earn"


async def test_concurrent_duplicate_award_is_single(customer):
    order = await make_order(customer.id, subtotal_cents=5_000)

    async def award():
        async with async_session() as s:
            await loyalty.award_for_paid_order(s, await s.get(Order, order.id))
            await s.commit()

    await asyncio.gather(*(award() for _ in range(5)))
    assert await balance(customer.id) == 50
    assert len(await _ledger(customer.id)) == 1


async def test_unpaid_orders_never_earn(client, customer):
    for status in ("unpaid", "processing", "requires_action", "failed"):
        order = await make_order(customer.id, subtotal_cents=90_000, payment_status=status, status="pending_payment")
        async with async_session() as s:
            await loyalty.award_for_paid_order(s, await s.get(Order, order.id))
            await s.commit()
    assert await _ledger(customer.id) == []
    body = (await client.get(f"{P}/points", headers=customer.headers)).json()
    assert body["points_balance"] == 0 and body["trailing_12_month_spend_cents"] == 0
    mult = (await client.get(f"{P}/multiplier", headers=customer.headers)).json()
    assert mult["crew_spend_cents"] == 0


async def test_partial_then_full_refund_reversal_is_idempotent(customer):
    order = await paid_order(customer.id, subtotal_cents=20_000)  # 200 CP, total $200
    assert await balance(customer.id) == 200
    await refund(order.id, 5_000)  # 25% -> reverse 50
    await replay_refund_event(order.id, 5_000)  # duplicate webhook
    assert await balance(customer.id) == 150
    await refund(order.id, 15_000)  # cumulative 100% -> reverse remaining 150
    await replay_refund_event(order.id, 15_000)
    assert await balance(customer.id) == 0
    rows = await _ledger(customer.id)
    assert [(r.kind, r.points) for r in rows] == [("earn", 200), ("earn_reversal", -50), ("earn_reversal", -150)]
    assert all(r.period == rows[0].period for r in rows)


async def test_partial_refund_with_shipping_uses_order_total_share(customer):
    # subtotal $90 + $10 shipping = $100 total; 90 CP. Refund $50 (50% of total) -> 45 CP.
    order = await paid_order(customer.id, subtotal_cents=9_000, shipping_cents=1_000)
    await refund(order.id, 5_000)
    assert await balance(customer.id) == 45
    async with async_session() as s:
        o = await s.get(Order, order.id)
        assert o.status == "paid"  # a partial refund is not a cancellation


async def test_refund_after_points_spent_records_shortfall(client, customer):
    order = await paid_order(customer.id, subtotal_cents=30_000)  # 300 CP
    r = await client.post(f"{P}/redeem/discount", json={"points": 200}, headers=customer.headers)
    assert r.status_code == 201
    assert await balance(customer.id) == 100
    await refund(order.id, 30_000)  # full refund: 300 to reverse, only 100 available
    await replay_refund_event(order.id, 30_000)
    assert await balance(customer.id) == 0
    rows = await _ledger(customer.id)
    reversal = [r for r in rows if r.kind == "earn_reversal"]
    # One full reversal row; the 200 CP already redeemed become points owed (settled
    # from future credits), so sum(ledger) == balance - owed.
    assert len(reversal) == 1 and reversal[0].points == -300
    assert "200 CP had already been redeemed" in reversal[0].description
    async with async_session() as s:
        acct = (await s.execute(select(CrewPoints).where(CrewPoints.user_id == customer.id))).scalar_one()
        audits = list((await s.execute(select(AuditLog).where(AuditLog.action == "points_owed"))).scalars())
    assert acct.points_owed == 200
    assert len(audits) == 1 and audits[0].detail["owed"] == 200
    assert sum(r.points for r in rows) == acct.points_balance - acct.points_owed


async def test_profile_verification_bonus_once_per_request(customer):
    req = uuid.uuid4()
    for _ in range(3):
        async with async_session() as s:
            await loyalty.award_profile_verification_bonus(s, customer.id, req)
            await s.commit()
    assert await balance(customer.id) == 1000
    async with async_session() as s:
        await loyalty.award_profile_verification_bonus(s, customer.id, uuid.uuid4())
        await s.commit()
    assert await balance(customer.id) == 2000


async def test_tier_is_display_only_and_from_paid_spend(client, customer):
    await paid_order(customer.id, subtotal_cents=210_000)  # $2,100 -> skipper
    await make_order(customer.id, subtotal_cents=900_000, payment_status="unpaid", status="pending_payment")
    body = (await client.get(f"{P}/points", headers=customer.headers)).json()
    assert body["tier"] == "skipper"
    assert body["next_tier"] == "captain" and body["next_tier_threshold_cents"] == 500_000
    async with async_session() as s:
        ents = list((await s.execute(select(DiscountEntitlement))).scalars())
    assert ents == []  # a tier never creates a cashback/discount entitlement


async def test_balance_never_negative_on_direct_debit(customer):
    await grant_points(customer.id, 100)
    async with async_session() as s:
        try:
            await loyalty.apply(s, user_id=customer.id, kind="adjustment", points=-101, idempotency_key="x")
        except loyalty.InsufficientPointsError:
            pass
        else:  # pragma: no cover
            raise AssertionError("debit beyond balance was allowed")


def test_nz_period_boundaries():
    # 2026-03-31T11:30Z is 2026-04-01 00:30 NZDT.
    assert loyalty.period_of(datetime(2026, 3, 31, 11, 30, tzinfo=UTC)) == "2026-04"
    assert loyalty.period_of(datetime(2026, 3, 31, 10, 59, tzinfo=UTC)) == "2026-03"
    start, end = loyalty.period_bounds("2026-04")
    assert start == datetime(2026, 3, 31, 11, 0, tzinfo=UTC)
    assert end == datetime(2026, 4, 30, 12, 0, tzinfo=UTC)  # NZST after DST ends
    assert loyalty.previous_period(datetime(2026, 1, 5, tzinfo=UTC)) == "2025-12"
