"""Regression tests for the independent review findings (each failed before its fix)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session
from app.models.helm_dash import OperatorPayout
from app.models.order import Order
from app.models.product import Product
from app.schemas.product import FitmentResult
from app.services import loyalty
from app.services.ai.grounding import apply_guard
from app.services.ai.tools import ProductRef, TurnRuntime
from app.services.rag.retrieval import RetrievedChunk
from app.tests.test_loyalty_support import (
    balance,
    delivery_for,
    helm_dash_order,
    make_area,
    make_crew,
    make_operator_profile,
    paid_order,
    pay,
    refund,
)

L = "/api/v1/loyalty"
D = "/api/v1/dispatch"


# ---------------------------------------------------------------- P1 monthly bonus kept after refund
async def test_p1_monthly_bonus_not_reversed_by_later_refund(customer, other_customer):
    await make_crew(customer.id, other_customer.id)
    paid = datetime(2026, 4, 10, 2, 0, tzinfo=UTC)
    order = await paid_order(customer.id, subtotal_cents=500_000, paid_at=paid)  # $5,000 -> 3x tier
    async with async_session() as s:
        summary = await loyalty.calculate_monthly_multipliers(s, "2026-04")
        await s.commit()
    assert summary["points_awarded"] == 10_000
    assert await balance(customer.id) == 15_000
    await refund(order.id, order.total_cents)  # full refund after the bonus run
    # Correct: a fully refunded order should leave no points from it (earn + bonus).
    assert await balance(customer.id) == 0, f"balance after full refund = {await balance(customer.id)}"


# ---------------------------------------------------------------- P2 refund shortfall + void
async def test_p2_spend_points_then_refund_then_void_keeps_points(client, customer):
    order = await paid_order(customer.id, subtotal_cents=100_000)  # 1000 CP
    assert await balance(customer.id) == 1000
    r = await client.post(f"{L}/redeem/discount", json={"points": 1000}, headers=customer.headers)
    assert r.status_code == 201, r.text
    ent_id = r.json()["id"]
    await refund(order.id, order.total_cents)  # shortfall: balance is 0, nothing reversed
    r = await client.post(f"{L}/entitlements/{ent_id}/void", headers=customer.headers)
    assert r.status_code == 200, r.text
    # Correct: points earned on a fully refunded order must not survive.
    assert await balance(customer.id) == 0, f"balance after refund+void = {await balance(customer.id)}"


# ---------------------------------------------------------------- P3 grounding fit-claim bypass
def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        title="Bilge guide",
        publisher=None,
        url=None,
        licence="test",
        is_synthetic=False,
        domain="maintenance",
        heading=None,
        content="Check the bilge pump every season.",
        similarity=0.9,
        applies_to={},
        applicability="general",
    )


def _runtime(product: Product, status: str) -> TurnRuntime:
    rt = TurnRuntime(db=None, user_id=uuid.uuid4(), vessel=None, profile=None)  # type: ignore[arg-type]
    rt.retrieved[1] = _chunk()
    rt.products[product.id] = ProductRef(
        product, FitmentResult(status=status, message="Fit is unknown — no verified rule", reasons=[])
    )
    return rt


def _product() -> Product:
    return Product(
        id=uuid.uuid4(),
        sku="SEAFLO-BP",
        name="Seaflo Bilge Pump",
        brand="Seaflo",
        price_cents=5000,
        stock_quantity=5,
        is_active=True,
        images=[],
        oem_part_numbers=[],
        fitment_scope="unspecified",
    )


def test_p3a_fit_claim_with_any_negation_word_survives():
    p = _product()
    text = "The Seaflo Bilge Pump fits your boat [1], although the old pump cannot be reused."
    out = apply_guard(text, _runtime(p, "unknown"), None)
    # The false claim is replaced by the real fitment status (and, with no cited
    # content left, the answer is no longer presented as grounded).
    assert "fits your boat" not in out.content, out.content
    assert out.status in ("grounded", "insufficient_evidence")


def test_p3b_fit_claim_with_partial_product_name_survives():
    p = _product()
    text = "The Seaflo pump is compatible with your boat [1]."
    out = apply_guard(text, _runtime(p, "unknown"), None)
    assert "compatible with your boat" not in out.content, out.content


def test_p3c_mismatch_product_claimed_fit():
    p = _product()
    text = "Seaflo Bilge Pump will work with your vessel [1]; no unknown issues."
    out = apply_guard(text, _runtime(p, "verified_mismatch"), None)
    assert "will work with your vessel" not in out.content, out.content


# ---------------------------------------------------------------- P4 deactivated operator keeps acting
async def test_p4_deactivated_operator_can_complete_delivery(client, customer, dispatcher, admin, operator):
    await make_area()
    await make_operator_profile(operator.id)
    order = await pay(await helm_dash_order(customer.id))
    d = await delivery_for(order.id)
    r = await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"{D}/operators/{operator.id}/deactivate", headers=admin.headers)
    assert r.status_code == 200, r.text
    statuses = []
    for st in ("picked_up", "en_route", "delivered"):
        r = await client.post(f"{D}/jobs/{d.id}/status", json={"status": st}, headers=operator.headers)
        statuses.append(r.status_code)
    async with async_session() as s:
        o = await s.get(Order, order.id)
        payouts = (await s.execute(select(OperatorPayout))).scalars().all()
    # Correct: a deactivated operator must not be able to progress / complete jobs.
    assert statuses[0] == 403, f"statuses={statuses} order={o.status} payouts={len(payouts)}"


# ---------------------------------------------------------------- P5 verification bonus farmable per request
async def test_p5_profile_bonus_repeatable_for_same_vessel(client, customer, admin, vessel):
    eq_url = f"/api/v1/vessels/{vessel.id}/equipment"
    await client.get("/api/v1/boat-db/equipment-categories")
    r = await client.post(eq_url, json={"category": "anchor_winch", "make": "Lewmar"}, headers=customer.headers)
    assert r.status_code == 201, r.text
    eq_id = r.json()["id"]
    for i in range(2):
        r = await client.post(f"{eq_url}/verification-requests", json={}, headers=customer.headers)
        assert r.status_code == 201, r.text
        r = await client.post(f"/api/v1/boat-db/verification-requests/{r.json()['id']}/approve", headers=admin.headers)
        assert r.status_code == 200, r.text
        # trivial owner edit resets the row to unverified so it can be resubmitted
        r = await client.patch(f"{eq_url}/{eq_id}", json={"notes": f"edit {i}"}, headers=customer.headers)
        assert r.status_code == 200, r.text
    # Correct (per docstring "once per approved profile"): 1000, not 2000
    assert await balance(customer.id) == 1000, f"balance={await balance(customer.id)}"


# ---------------------------------------------------------------- P6 unbounded int -> 500
async def test_p6_cost_cents_overflow_is_500(client, customer, vessel):
    r = await client.post(
        f"/api/v1/vessels/{vessel.id}/service-records",
        json={"service_type": "Oil", "performed_on": "2026-01-01", "cost_cents": 3_000_000_000},
        headers=customer.headers,
    )
    assert r.status_code == 422, (r.status_code, r.text)


def test_p3d_positive_product_claim_is_kept():
    p = _product()
    text = "Check the bilge pump every season [1]. The Seaflo Bilge Pump fits your boat [1]."
    out = apply_guard(text, _runtime(p, "verified_fit"), None)
    assert out.status == "grounded" and "The Seaflo Bilge Pump fits your boat" in out.content
    # The fit statement rests on central fitment, not on the passage: no citation on it.
    assert "every season [1]" in out.content and "fits your boat [1]" not in out.content
    # Without a supported passage claim, the verified product statement survives the
    # controlled insufficient-evidence reply (uncited); the answer is not "grounded".
    alone = apply_guard("The Seaflo Bilge Pump fits your boat [1].", _runtime(p, "verified_fit"), None)
    assert alone.status == "insufficient_evidence" and "Seaflo Bilge Pump fits your boat" in alone.content
    assert "[1]" not in alone.content and alone.actions == []
