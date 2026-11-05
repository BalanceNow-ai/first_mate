"""Follow-up tests for the review fixes (ledger invariant, refunds, delivery, invites, AI)."""

from sqlalchemy import func, select

from app.database import async_session
from app.models.loyalty import CrewPoints, PointsTransaction
from app.services import loyalty
from app.tests.test_loyalty_support import (
    balance,
    delivery_for,
    helm_dash_order,
    make_area,
    paid_order,
    pay,
    refund,
)

L = "/api/v1/loyalty"


async def _invariant(user_id) -> tuple[int, int, int]:
    async with async_session() as s:
        total = (
            await s.execute(
                select(func.coalesce(func.sum(PointsTransaction.points), 0)).where(PointsTransaction.user_id == user_id)
            )
        ).scalar_one()
        acct = (await s.execute(select(CrewPoints).where(CrewPoints.user_id == user_id))).scalar_one()
    return total, acct.points_balance, acct.points_owed


async def test_owed_points_settled_by_later_earnings_and_invariant_holds(client, customer):
    order = await paid_order(customer.id, subtotal_cents=100_000)  # 1000 CP
    r = await client.post(f"{L}/redeem/discount", json={"points": 1000}, headers=customer.headers)
    assert r.status_code == 201
    await refund(order.id, order.total_cents)
    total, bal, owed = await _invariant(customer.id)
    assert (bal, owed) == (0, 1000) and total == bal - owed
    pts = (await client.get(f"{L}/points", headers=customer.headers)).json()
    assert pts["points_owed"] == 1000
    await paid_order(customer.id, subtotal_cents=60_000)  # +600 earned, all goes to the debt
    total, bal, owed = await _invariant(customer.id)
    assert (bal, owed) == (0, 400) and total == bal - owed
    await paid_order(customer.id, subtotal_cents=50_000)  # +500: 400 settles, 100 spendable
    total, bal, owed = await _invariant(customer.id)
    assert (bal, owed) == (100, 0) and total == bal - owed
    # Replaying the refund event changes nothing.
    async with async_session() as s:
        from app.models.order import Order

        o = await s.get(Order, order.id)
        await loyalty.reverse_for_refund(s, o, 0)
        await s.commit()
    assert await _invariant(customer.id) == (100, 100, 0)


async def test_full_refund_returns_discount_points(client, customer):
    from app.models.loyalty import DiscountEntitlement

    await paid_order(customer.id, subtotal_cents=100_000)  # 1000 CP
    ent = (await client.post(f"{L}/redeem/discount", json={"points": 500}, headers=customer.headers)).json()
    order = await paid_order(customer.id, subtotal_cents=10_000, discount_cents=500)  # earns 95
    async with async_session() as s:
        e = await s.get(DiscountEntitlement, __import__("uuid").UUID(ent["id"]))
        e.status, e.order_id = "consumed", order.id
        from app.models.order import Order

        o = await s.get(Order, order.id)
        o.discount_entitlement_id = e.id
        await s.commit()
    before = await balance(customer.id)  # 500 + 95
    await refund(order.id, order.total_cents)
    assert await balance(customer.id) == before - 95 + 500
    total, bal, owed = await _invariant(customer.id)
    assert total == bal - owed


async def test_full_refund_cancels_undispatched_helm_dash_job(client, customer, dispatcher, operator):
    await make_area()
    order = await pay(await helm_dash_order(customer.id))
    d = await delivery_for(order.id)
    assert d.status == "awaiting_dispatch"
    await refund(order.id, order.total_cents)
    d = await delivery_for(order.id)
    assert d.status == "cancelled"
    r = await client.post(
        f"/api/v1/dispatch/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 409


async def test_crew_invites_are_capped_per_day(client, customer):
    r = await client.post(f"{L}/crews", json={"name": "Spam Test"}, headers=customer.headers)
    assert r.status_code == 201
    codes = []
    for i in range(22):
        r = await client.post(f"{L}/crews/mine/invites", json={"email": f"x{i}@example.test"}, headers=customer.headers)
        codes.append(r.status_code)
        if r.status_code == 201:
            await client.delete(f"{L}/crews/mine/invites/{r.json()['id']}", headers=customer.headers)
    assert codes[:20] == [201] * 20 and codes[20] == 429


async def test_ai_turn_holds_no_transaction_while_the_model_runs(client, customer, monkeypatch):
    from app.services.ai import agent
    from app.tests.conftest import create_vessel

    await create_vessel(customer.id)
    seen = []

    class Probe:
        name = "probe"
        mode = "local_extractive"

        async def answer(self, turn, runtime):
            seen.append(runtime.db.in_transaction())
            await runtime.dispatch("get_vessel_profile", {})
            seen.append(runtime.db.in_transaction())
            from app.services.ai.providers import Draft

            return Draft(content="I need more detail about your engine.")

    monkeypatch.setattr(agent, "get_llm_provider", lambda settings: Probe())
    r = await client.post("/api/v1/ai/chat", json={"message": "hello"}, headers=customer.headers)
    assert r.status_code == 200, r.text
    assert seen == [False, False]
