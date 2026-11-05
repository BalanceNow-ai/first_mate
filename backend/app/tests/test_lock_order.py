"""FM-05: one global lock order (D22) — barrier-controlled races on two PostgreSQL
connections. Each test parks transaction 1 between its first and second lock, starts
transaction 2 on another connection, then releases transaction 1. Under the old,
opposing orders this is a deadlock (PostgreSQL aborts one side); now both reach a
legitimate terminal outcome.

D22: Order → DiscountEntitlement → HelmDashDelivery → CrewPoints (several accounts in
ascending str(user_id)).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.core.errors import AppError
from app.database import async_session
from app.models.helm_dash import HelmDashDelivery
from app.models.loyalty import CrewPoints, DiscountEntitlement, PointsTransaction
from app.models.order import Order
from app.services import delivery, loyalty
from app.tests.conftest import create_product
from app.tests.test_commerce_support import add, idem, pay
from app.tests.test_loyalty_support import (
    delivery_for,
    grant_points,
    helm_dash_order,
    make_area,
    make_operator_profile,
    refund,
)
from app.tests.test_loyalty_support import pay as raise_order_paid

API = "/api/v1"
D = "/api/v1/dispatch"
SETTLE = 0.6  # time for transaction 2 to take (or queue for) its first lock


async def _ledger_consistent(user_id) -> int:
    async with async_session() as s:
        acct = (await s.execute(select(CrewPoints).where(CrewPoints.user_id == user_id))).scalar_one()
        total = (
            await s.execute(
                select(func.coalesce(func.sum(PointsTransaction.points), 0)).where(PointsTransaction.user_id == user_id)
            )
        ).scalar_one()
    assert total == acct.points_balance - acct.points_owed
    return acct.points_balance


async def test_payment_success_vs_void_of_its_discount(client, customer, monkeypatch):
    """Cycle A: payment holds order → entitlement and then needs the account;
    void used to take the account and then the entitlement."""
    await grant_points(customer.id, 1_000)
    ent = (await client.post(f"{API}/loyalty/redeem/discount", json={"points": 500}, headers=customer.headers)).json()
    product = await create_product(price_cents=10_000, stock_quantity=5, weight_grams=100)
    await add(client, customer, product, 1)
    body = {"delivery_type": "click_and_collect", "discount_entitlement_id": ent["id"]}
    order = (
        await client.post(f"{API}/orders/checkout", json=body, headers={**customer.headers, "Idempotency-Key": idem()})
    ).json()

    at_award, go = asyncio.Event(), asyncio.Event()
    original = loyalty.award_for_paid_order

    async def parked_award(db, o):
        at_award.set()  # transaction 1 holds the order and the consumed entitlement
        await go.wait()
        await original(db, o)

    monkeypatch.setattr(loyalty, "award_for_paid_order", parked_award)
    payment = asyncio.create_task(pay(client, customer, order["id"]))
    await asyncio.wait_for(at_award.wait(), 10)

    async def void():
        async with async_session() as s:
            try:
                await loyalty.void_entitlement(s, customer.id, ent["id"])
                await s.commit()
                return "voided"
            except AppError as exc:
                await s.rollback()
                return exc.code

    voiding = asyncio.create_task(void())
    await asyncio.sleep(SETTLE)
    go.set()
    paid, void_outcome = await asyncio.wait_for(asyncio.gather(payment, voiding), 15)

    assert paid["payment_status"] == "succeeded" and paid["order_status"] == "paid", paid
    assert void_outcome == "entitlement_not_voidable"  # it was consumed by the paid order
    async with async_session() as s:
        e = await s.get(DiscountEntitlement, ent["id"])
        o = await s.get(Order, order["id"])
    assert e.status == "consumed" and str(e.order_id) == order["id"] and o.status == "paid"
    assert await _ledger_consistent(customer.id) == 500 + 95  # 1,000 − 500 redeemed + 95 earned


async def test_refund_vs_operator_progressing_the_delivery(client, customer, dispatcher, operator, monkeypatch):
    """Cycle B: refund holds the order and then cancels the delivery; operator actions
    used to lock the delivery and then the order."""
    await make_area()
    await make_operator_profile(operator.id)
    order = await raise_order_paid(await helm_dash_order(customer.id))
    d = await delivery_for(order.id)
    r = await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 200, r.text
    assert (await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)).status_code == 200

    at_delivery, go = asyncio.Event(), asyncio.Event()
    original = delivery.cancel_for_refunded_order

    async def parked_cancel(db, o):
        at_delivery.set()  # transaction 1 holds the order
        await go.wait()
        await original(db, o)

    monkeypatch.setattr(delivery, "cancel_for_refunded_order", parked_cancel)
    refunding = asyncio.create_task(refund(order.id, order.total_cents))
    await asyncio.wait_for(at_delivery.wait(), 10)
    picking_up = asyncio.create_task(
        client.post(f"{D}/jobs/{d.id}/status", json={"status": "picked_up"}, headers=operator.headers)
    )
    await asyncio.sleep(SETTLE)
    go.set()
    refunded, picked = await asyncio.wait_for(asyncio.gather(refunding, picking_up), 15)

    assert refunded.payment_status == "refunded"
    assert picked.status_code == 409, picked.text  # the job was cancelled first
    async with async_session() as s:
        job = await s.get(HelmDashDelivery, d.id)
        o = await s.get(Order, order.id)
    assert job.status == "cancelled" and o.status == "refunded"
    assert await _ledger_consistent(customer.id) == 0


async def test_concurrent_refunds_in_one_crew_lock_accounts_in_one_order(customer, other_customer):
    """Two members' refunds both claw back the crew bonus (touching both accounts):
    each locks every account it may debit up front, in ascending id order."""
    from datetime import UTC, datetime

    from app.tests.test_loyalty_support import make_crew, paid_order

    await make_crew(customer.id, other_customer.id)
    paid_at = datetime(2026, 4, 10, 2, tzinfo=UTC)
    a = await paid_order(customer.id, subtotal_cents=300_000, paid_at=paid_at)
    b = await paid_order(other_customer.id, subtotal_cents=300_000, paid_at=paid_at)
    async with async_session() as s:
        await loyalty.calculate_monthly_multipliers(s, "2026-04")  # 6,000 spend → 3x
        await s.commit()
    await asyncio.wait_for(asyncio.gather(refund(a.id, a.total_cents), refund(b.id, b.total_cents)), 20)
    for user in (customer.id, other_customer.id):
        assert await _ledger_consistent(user) == 0
