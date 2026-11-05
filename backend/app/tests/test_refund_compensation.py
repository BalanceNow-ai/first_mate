"""FM-03: a full refund returns the points spent on the order's discount exactly once,
independently of whether (or how much) earned-point reversal remains.

Everything goes through checkout, the local TEST-MODE payment and *signed*
``charge.refunded`` webhook events (cumulative ``amount_refunded``), on PostgreSQL.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import func, select

from app.database import async_session
from app.models.loyalty import CrewPoints, DiscountEntitlement, PointsTransaction
from app.tests.conftest import create_product
from app.tests.test_commerce_support import add, idem, pay, post_event, refund_event
from app.tests.test_loyalty_support import grant_points

API = "/api/v1"


async def _ledger(user_id) -> dict:
    async with async_session() as s:
        acct = (await s.execute(select(CrewPoints).where(CrewPoints.user_id == user_id))).scalar_one()
        total = (
            await s.execute(
                select(func.coalesce(func.sum(PointsTransaction.points), 0)).where(PointsTransaction.user_id == user_id)
            )
        ).scalar_one()
        kinds = [
            (r.kind, r.points)
            for r in (
                await s.execute(
                    select(PointsTransaction)
                    .where(PointsTransaction.user_id == user_id)
                    .order_by(PointsTransaction.created_at, PointsTransaction.id)
                )
            ).scalars()
        ]
    assert total == acct.points_balance - acct.points_owed, "ledger invariant"
    return {"balance": acct.points_balance, "owed": acct.points_owed, "kinds": kinds}


async def _discounted_paid_order(client, customer, *, price_cents: int, discount_points: int) -> dict:
    await grant_points(customer.id, discount_points)
    ent = await client.post(
        f"{API}/loyalty/redeem/discount", json={"points": discount_points}, headers=customer.headers
    )
    assert ent.status_code == 201, ent.text
    product = await create_product(price_cents=price_cents, stock_quantity=5, weight_grams=100)
    await add(client, customer, product, 1)
    body = {"delivery_type": "click_and_collect", "discount_entitlement_id": ent.json()["id"]}
    r = await client.post(f"{API}/orders/checkout", json=body, headers={**customer.headers, "Idempotency-Key": idem()})
    assert r.status_code == 201, r.text
    order = r.json()
    await pay(client, customer, order["id"])
    order = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert order["status"] == "paid" and order["payment_status"] == "succeeded", order
    return order


async def _refund_to(client, order: dict, cumulative_cents: int, event_id: str | None = None):
    r = await post_event(client, refund_event(order, cumulative_cents, event_id=event_id))
    assert r.status_code == 200, r.text


async def _entitlement(order: dict) -> DiscountEntitlement:
    async with async_session() as s:
        return (
            await s.execute(select(DiscountEntitlement).where(DiscountEntitlement.order_id == uuid.UUID(order["id"])))
        ).scalar_one()


async def test_full_refund_after_partial_refund_already_reversed_all_earned_points(client, customer):
    """Review FM-03 branch 2: $100 goods, $99 discount (9,900 CP), $1 paid → 1 CP."""
    order = await _discounted_paid_order(client, customer, price_cents=10_000, discount_points=9_900)
    assert order["total_cents"] == 100 and order["discount_cents"] == 9_900
    assert (await _ledger(customer.id))["balance"] == 1

    await _refund_to(client, order, 50)  # partial: ceil reverses the single earned point
    assert (await _ledger(customer.id))["balance"] == 0
    await _refund_to(client, order, 100)  # full: nothing left to reverse, discount still owed back
    ledger = await _ledger(customer.id)
    assert ledger["balance"] == 9_900 and ledger["owed"] == 0
    assert ledger["kinds"].count(("redemption_reversal", 9_900)) == 1
    ent = await _entitlement(order)
    assert ent.status == "consumed" and str(ent.order_id) == order["id"]

    # Replays: the same event, and a new event id with the same cumulative amount.
    event_id = f"evt_test_{uuid.uuid4().hex}"
    await _refund_to(client, order, 100, event_id=event_id)
    await _refund_to(client, order, 100, event_id=event_id)
    await _refund_to(client, order, 100)
    assert (await _ledger(customer.id))["balance"] == 9_900


async def test_full_refund_of_order_that_earned_no_points(client, customer):
    """Review FM-03 branch 1: net merchandise below $1 earns nothing; the discount is still returned."""
    order = await _discounted_paid_order(client, customer, price_cents=9_950, discount_points=9_900)
    assert order["total_cents"] == 50
    assert (await _ledger(customer.id))["balance"] == 0
    await _refund_to(client, order, 50)
    ledger = await _ledger(customer.id)
    assert ledger["balance"] == 9_900
    assert [k for k, _ in ledger["kinds"]].count("redemption_reversal") == 1
    assert not any(k == "earn" for k, _ in ledger["kinds"])


async def test_partial_refund_does_not_return_discount_points(client, customer):
    order = await _discounted_paid_order(client, customer, price_cents=20_000, discount_points=5_000)
    assert order["total_cents"] == 15_000
    await _refund_to(client, order, 7_500)
    ledger = await _ledger(customer.id)
    assert ledger["balance"] == 150 - 75
    assert not any(k == "redemption_reversal" for k, _ in ledger["kinds"])


async def test_full_refund_without_a_discount_returns_nothing_extra(client, customer):
    product = await create_product(price_cents=20_000, stock_quantity=5, weight_grams=100)
    await add(client, customer, product, 1)
    r = await client.post(
        f"{API}/orders/checkout",
        json={"delivery_type": "click_and_collect"},
        headers={**customer.headers, "Idempotency-Key": idem()},
    )
    order = r.json()
    await pay(client, customer, order["id"])
    order = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    await _refund_to(client, order, order["total_cents"])
    ledger = await _ledger(customer.id)
    assert ledger["balance"] == 0
    assert [k for k, _ in ledger["kinds"]] == ["earn", "earn_reversal"]


async def test_full_refund_racing_a_redemption_keeps_the_ledger_consistent(client, customer):
    order = await _discounted_paid_order(client, customer, price_cents=10_000, discount_points=9_900)
    await grant_points(customer.id, 1_000)  # balance 1,001

    refund_task = _refund_to(client, order, 100)
    redeem_task = client.post(f"{API}/loyalty/redeem/discount", json={"points": 1_000}, headers=customer.headers)
    _, redeemed = await asyncio.gather(refund_task, redeem_task)
    assert redeemed.status_code == 201, redeemed.text

    ledger = await _ledger(customer.id)
    # 1,001 + 9,900 returned − 1 earned point reversed − 1,000 redeemed, whatever the order.
    assert ledger["balance"] - ledger["owed"] == 9_900
    assert ledger["kinds"].count(("redemption_reversal", 9_900)) == 1


async def test_crew_bonus_recomputed_even_when_no_further_point_is_reversed(customer, other_customer):
    """A later partial refund can cross a crew tier without reversing another whole point
    (ceil rounding already took it); the bonus clawback must still run."""
    from datetime import UTC, datetime

    from app.services import loyalty
    from app.tests.test_loyalty_support import make_crew, paid_order, refund

    await make_crew(customer.id, other_customer.id)
    order = await paid_order(customer.id, subtotal_cents=500_001, paid_at=datetime(2026, 4, 10, 2, tzinfo=UTC))
    async with async_session() as s:
        await loyalty.calculate_monthly_multipliers(s, "2026-04")  # 3x: +10,000 CP
        await s.commit()
    await refund(order.id, 1)  # spend 5,000.00: still 3x; 1 point reversed (ceil)
    await refund(order.id, 1)  # spend 4,999.99: 2x; no further whole point to reverse

    async with async_session() as s:
        bonus = (
            await s.execute(
                select(func.sum(PointsTransaction.points)).where(
                    PointsTransaction.user_id == customer.id,
                    PointsTransaction.kind.in_(("monthly_bonus", "monthly_bonus_reversal")),
                )
            )
        ).scalar_one()
    assert bonus == 4_999  # (5,000 − 1 reversed) × (2 − 1)
    assert (await _ledger(customer.id))["balance"] == 4_999 + 4_999
