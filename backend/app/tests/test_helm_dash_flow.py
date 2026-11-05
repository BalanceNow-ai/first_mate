"""Helm Dash: job creation from paid orders, dispatch -> operator -> delivered, order
status sync, payouts, reported (never fabricated) positions and access isolation."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.cli.__main__ import main as cli_main
from app.config import get_settings
from app.database import async_session, utcnow
from app.models.helm_dash import DeliveryStatusEvent, HelmDashDelivery, OperatorPayout
from app.models.notifications import NotificationOutbox
from app.models.order import Order
from app.services import delivery as delivery_service
from app.tests.conftest import create_actor
from app.tests.test_loyalty_support import (
    delivery_for,
    helm_dash_order,
    make_area,
    make_operator_profile,
    make_order,
    paid_order,
    pay,
)

D = "/api/v1/dispatch"
H = "/api/v1/helm-dash"


async def _setup(operator):
    await make_area()
    await make_operator_profile(operator.id)


async def _paid_helm_dash(customer):
    order = await pay(await helm_dash_order(customer.id))
    d = await delivery_for(order.id)
    assert d is not None
    return order, d


def _now_iso(delta: timedelta = timedelta()) -> str:
    return (utcnow() + delta).isoformat()


async def test_create_for_paid_order_idempotent_and_helm_dash_only(customer):
    await make_area()
    order, d = await _paid_helm_dash(customer)
    assert d.status == "awaiting_dispatch" and d.delivery_fee_cents == 4900
    assert float(d.nautical_miles) == 3.0 and d.estimated_delivery_minutes == 35 and d.area_id == "hauraki-gulf"
    assert d.delivery_coordinates == {"lat": -36.80, "lng": 174.95}
    assert d.delivery_location_name == "Rangitoto Channel mooring"
    assert d.pickup_location["lat"] == get_settings().warehouse_lat
    async with async_session() as s:  # repeated event delivery
        await delivery_service.create_for_paid_order(s, await s.get(Order, order.id))
        await s.commit()
        rows = list((await s.execute(select(HelmDashDelivery))).scalars())
        events = list((await s.execute(select(DeliveryStatusEvent))).scalars())
    assert len(rows) == 1 and [(e.from_status, e.to_status) for e in events] == [(None, "awaiting_dispatch")]
    courier = await paid_order(customer.id, delivery_type="courier")
    assert await delivery_for(courier.id) is None
    pending = await make_order(
        customer.id,
        payment_status="unpaid",
        status="pending_payment",
        delivery_type="helm_dash",
        helm_dash_coordinates={"lat": -36.8, "lng": 174.9},
    )
    async with async_session() as s:
        await delivery_service.create_for_paid_order(s, await s.get(Order, pending.id))
        await s.commit()
    assert await delivery_for(pending.id) is None


async def test_full_dispatch_flow(client, customer, dispatcher, operator, admin):
    await _setup(operator)
    order, d = await _paid_helm_dash(customer)
    # Customer view before any report: no fabricated position.
    t = (await client.get(f"{H}/deliveries/{d.id}", headers=customer.headers)).json()
    assert t["status"] == "awaiting_dispatch" and t["latest_location"] is None
    assert t["order_number"] == order.order_number and t["delivery_fee_cents"] == 4900

    listing = (
        await client.get(f"{D}/deliveries", params={"status": "awaiting_dispatch"}, headers=dispatcher.headers)
    ).json()
    assert [x["id"] for x in listing] == [str(d.id)]
    ops = (await client.get(f"{D}/operators", params={"area_id": "hauraki-gulf"}, headers=dispatcher.headers)).json()
    assert [o["user_id"] for o in ops] == [str(operator.id)] and ops[0]["certification_verified"] is False

    r = await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "assigned" and r.json()["operator_name"] == "Skipper Sam"

    # Positions are refused until the operator accepts.
    loc = {"lat": -36.83, "lng": 174.80, "recorded_at": _now_iso(), "speed_knots": 18.5}
    r = await client.post(f"{D}/jobs/{d.id}/location", json=loc, headers=operator.headers)
    assert r.status_code == 409 and r.json()["code"] == "not_trackable"

    jobs = (await client.get(f"{D}/jobs", headers=operator.headers)).json()
    assert [j["id"] for j in jobs] == [str(d.id)]
    assert (await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)).json()["status"] == "accepted"
    t = (await client.get(f"{H}/deliveries/{d.id}", headers=customer.headers)).json()
    assert t["latest_location"] is None and t["location_message"] == "Awaiting first position report"

    r = await client.post(f"{D}/jobs/{d.id}/location", json=loc, headers=operator.headers)
    assert r.status_code == 201, r.text
    t = (await client.get(f"{H}/deliveries/{d.id}", headers=customer.headers)).json()
    pos = t["latest_location"]
    assert (pos["lat"], pos["lng"], pos["source"], pos["is_simulated"]) == (-36.83, 174.80, "operator_device", False)
    assert (
        pos["age_seconds"] >= 0
        and t["operator_display_name"] == "Skipper Sam"
        and t["operator_vessel_name"] == "Dash One"
    )

    # Skipping a step is refused by the transition table.
    r = await client.post(f"{D}/jobs/{d.id}/status", json={"status": "delivered"}, headers=operator.headers)
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"

    assert (
        await client.post(f"{D}/jobs/{d.id}/status", json={"status": "picked_up"}, headers=operator.headers)
    ).status_code == 200
    async with async_session() as s:
        assert (await s.get(Order, order.id)).status == "dispatched"
    assert (
        await client.post(f"{D}/jobs/{d.id}/status", json={"status": "en_route"}, headers=operator.headers)
    ).status_code == 200
    r = await client.post(f"{D}/jobs/{d.id}/status", json={"status": "delivered"}, headers=operator.headers)
    assert r.status_code == 200 and r.json()["delivered_at"] is not None
    async with async_session() as s:
        assert (await s.get(Order, order.id)).status == "delivered"
        payout = (await s.execute(select(OperatorPayout))).scalar_one()
        events = list(
            (
                await s.execute(
                    select(DeliveryStatusEvent)
                    .where(DeliveryStatusEvent.delivery_id == d.id)
                    .order_by(DeliveryStatusEvent.created_at)
                )
            ).scalars()
        )
        notes = list(
            (
                await s.execute(select(NotificationOutbox).where(NotificationOutbox.template == "helm_dash_status"))
            ).scalars()
        )
        order_status_notes = list(
            (
                await s.execute(select(NotificationOutbox).where(NotificationOutbox.template == "order_status_changed"))
            ).scalars()
        )
    assert (payout.status, payout.amount_cents, payout.share_bps, payout.gross_fee_cents) == (
        "rate_unconfigured",
        None,
        None,
        4900,
    )
    assert [e.to_status for e in events] == [
        "awaiting_dispatch",
        "assigned",
        "accepted",
        "picked_up",
        "en_route",
        "delivered",
    ]
    assert {n.payload["status"] for n in notes} == {"assigned", "accepted", "picked_up", "en_route", "delivered"}
    assert order_status_notes == []  # Helm Dash notifications cover the order
    t = (await client.get(f"{H}/deliveries/{d.id}", headers=customer.headers)).json()
    assert [x["status"] for x in t["timeline"]][-1] == "delivered"
    # Payout approval of an unconfigured rate is refused; nothing is paid.
    r = await client.post(f"{D}/payouts/{payout.id}/approve", headers=admin.headers)
    assert r.status_code == 409 and r.json()["code"] == "rate_unconfigured"
    # Positions after delivery are refused.
    r = await client.post(
        f"{D}/jobs/{d.id}/location", json={**loc, "recorded_at": _now_iso()}, headers=operator.headers
    )
    assert r.status_code == 409


async def test_location_stale_future_and_validation(client, customer, dispatcher, operator):
    await _setup(operator)
    _, d = await _paid_helm_dash(customer)
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)
    base = {"lat": -36.83, "lng": 174.80}
    r = await client.post(
        f"{D}/jobs/{d.id}/location",
        json={**base, "recorded_at": _now_iso(timedelta(minutes=-11))},
        headers=operator.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "location_stale"
    r = await client.post(
        f"{D}/jobs/{d.id}/location",
        json={**base, "recorded_at": _now_iso(timedelta(minutes=5))},
        headers=operator.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "location_in_future"
    r = await client.post(
        f"{D}/jobs/{d.id}/location", json={"lat": 95, "lng": 0, "recorded_at": _now_iso()}, headers=operator.headers
    )
    assert r.status_code == 422
    r = await client.post(
        f"{D}/jobs/{d.id}/location",
        json={**base, "recorded_at": _now_iso(), "source": "simulated"},
        headers=operator.headers,
    )
    assert r.status_code == 422  # clients cannot choose the source
    t = (await client.get(f"{H}/deliveries/{d.id}", headers=customer.headers)).json()
    assert t["latest_location"] is None


async def test_operator_isolation_and_customer_cannot_dispatch(client, customer, other_customer, dispatcher, operator):
    await _setup(operator)
    other_op = await create_actor("operator")
    await make_operator_profile(other_op.id, name="Other Skipper")
    _, d = await _paid_helm_dash(customer)
    # Customers / operators cannot use dispatcher endpoints.
    for actor in (customer, operator):
        r = await client.post(
            f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=actor.headers
        )
        assert r.status_code == 403
        assert (await client.get(f"{D}/deliveries", headers=actor.headers)).status_code == 403
    # Customers cannot use operator endpoints.
    assert (await client.get(f"{D}/jobs", headers=customer.headers)).status_code == 403
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    # Another operator cannot see or move this job.
    assert (await client.get(f"{D}/jobs", headers=other_op.headers)).json() == []
    assert (await client.get(f"{D}/jobs/{d.id}", headers=other_op.headers)).status_code == 404
    assert (await client.post(f"{D}/jobs/{d.id}/accept", headers=other_op.headers)).status_code == 404
    assert (await client.post(f"{D}/jobs/{d.id}/decline", json={}, headers=other_op.headers)).status_code == 404
    r = await client.post(
        f"{D}/jobs/{d.id}/location",
        json={"lat": -36.8, "lng": 174.8, "recorded_at": _now_iso()},
        headers=other_op.headers,
    )
    assert r.status_code == 404
    # Other customers cannot track it.
    assert (await client.get(f"{H}/deliveries/{d.id}", headers=other_customer.headers)).status_code == 404
    assert (await client.get(f"{H}/deliveries", headers=other_customer.headers)).json() == []


async def test_assignment_rules_decline_and_cancel(client, customer, dispatcher, operator):
    await _setup(operator)
    await make_area("bay-of-islands")
    far = await create_actor("operator")
    await make_operator_profile(far.id, area_id="bay-of-islands")
    inactive = await create_actor("operator")
    await make_operator_profile(inactive.id, active=False)
    _, d = await _paid_helm_dash(customer)
    r = await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(inactive.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "operator_not_active"
    r = await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(far.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "operator_wrong_area"
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    r = await client.post(f"{D}/jobs/{d.id}/decline", json={"reason": "Engine issue"}, headers=operator.headers)
    assert r.status_code == 200 and r.json()["status"] == "awaiting_dispatch" and r.json()["operator_id"] is None
    assert (await client.get(f"{D}/jobs", headers=operator.headers)).json() == []
    # Reassign, accept, then the dispatcher cancels before pickup.
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)
    r = await client.post(
        f"{D}/deliveries/{d.id}/cancel", json={"reason": "Customer request"}, headers=dispatcher.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    r = await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    assert r.status_code == 409
    detail = (await client.get(f"{D}/deliveries/{d.id}", headers=dispatcher.headers)).json()
    assert [e["to_status"] for e in detail["events"]] == [
        "awaiting_dispatch",
        "assigned",
        "awaiting_dispatch",
        "assigned",
        "accepted",
        "cancelled",
    ]


async def test_operator_failure_path(client, customer, dispatcher, operator):
    await _setup(operator)
    order, d = await _paid_helm_dash(customer)
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)
    await client.post(f"{D}/jobs/{d.id}/status", json={"status": "picked_up"}, headers=operator.headers)
    r = await client.post(
        f"{D}/jobs/{d.id}/status", json={"status": "failed", "note": "Weather"}, headers=operator.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "failed"
    async with async_session() as s:
        assert (await s.get(Order, order.id)).status == "dispatched"
        assert list((await s.execute(select(OperatorPayout))).scalars()) == []
    r = await client.post(f"{D}/jobs/{d.id}/status", json={"status": "bogus"}, headers=operator.headers)
    assert r.status_code == 422


async def test_payout_with_configured_share_and_reconciliation(
    client, customer, dispatcher, operator, admin, monkeypatch
):
    monkeypatch.setattr(get_settings(), "helm_dash_operator_share_bps", 2000)
    await _setup(operator)
    _, d = await _paid_helm_dash(customer)
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)
    for st in ("picked_up", "en_route", "delivered"):
        assert (
            await client.post(f"{D}/jobs/{d.id}/status", json={"status": st}, headers=operator.headers)
        ).status_code == 200
    payouts = (await client.get(f"{D}/payouts", headers=admin.headers)).json()
    assert len(payouts) == 1 and payouts[0]["status"] == "pending_review" and payouts[0]["amount_cents"] == 980
    assert (await client.get(f"{D}/payouts", headers=dispatcher.headers)).status_code == 403
    r = await client.post(f"{D}/payouts/{payouts[0]['id']}/approve", headers=admin.headers)
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["paid_at"] is None
    assert (await client.post(f"{D}/payouts/{payouts[0]['id']}/approve", headers=admin.headers)).status_code == 409
    rec = (await client.get(f"{D}/reconciliation", headers=admin.headers)).json()
    assert rec["delivered_count"] == 1 and rec["delivery_fees_cents"] == 4900 and rec["live_payouts_enabled"] is False
    assert rec["payouts_by_status"] == [
        {"status": "approved", "count": 1, "amount_cents": 980, "gross_fee_cents": 4900}
    ]


async def test_simulated_positions_are_labelled(client, customer, dispatcher, operator):
    await _setup(operator)
    _, d = await _paid_helm_dash(customer)
    await client.post(
        f"{D}/deliveries/{d.id}/assign", json={"operator_id": str(operator.id)}, headers=dispatcher.headers
    )
    # Not yet accepted: the simulator refuses.
    assert await asyncio.to_thread(cli_main, ["simulate-delivery", str(d.id), "--steps", "2", "--interval", "0"]) == 1
    await client.post(f"{D}/jobs/{d.id}/accept", headers=operator.headers)
    assert await asyncio.to_thread(cli_main, ["simulate-delivery", str(d.id), "--steps", "2", "--interval", "0"]) == 0
    pos = (await client.get(f"{H}/deliveries/{d.id}", headers=customer.headers)).json()["latest_location"]
    assert pos["source"] == "simulated" and pos["is_simulated"] is True
    assert "simulation" in pos["source_label"].lower()
    assert (pos["lat"], pos["lng"]) == (-36.80, 174.95)  # final step reaches the destination
