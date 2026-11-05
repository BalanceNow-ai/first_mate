"""Release path (expiry / cancel), late payments, refunds and staff order actions."""

import uuid
import asyncio

from app.config import get_settings
from app.database import async_session
from app.services.reservations import release_expired
from app.tasks.commerce import release_expired_reservations
from app.tests.conftest import create_product
from app.tests.test_commerce_support import (
    API,
    EventSpy,
    add,
    cart_quantities,
    checkout,
    courier_checkout,
    db_order,
    entitlement,
    expire_order,
    intent,
    paid_order,
    pay,
    pi_event,
    placed_order,
    post_event,
    refund_event,
    reservation_statuses,
    seed_entitlement,
    stock,
)


async def _run_expiry() -> int:
    async with async_session() as s:
        n = await release_expired(s)
        await s.commit()
        return n


async def test_expiry_restores_stock_cart_and_entitlement_exactly_once(
    client, customer, monkeypatch
):
    released = EventSpy(monkeypatch, "order_released")
    p = await create_product(stock_quantity=5, price_cents=3000)
    await add(client, customer, p, 2)
    ent = await seed_entitlement(customer.id, 700)
    order = (
        await checkout(
            client,
            customer,
            {"delivery_type": "click_and_collect", "discount_entitlement_id": str(ent.id)},
        )
    ).json()
    assert await stock(p.id) == 3
    assert await _run_expiry() == 0  # not yet expired
    await expire_order(order["id"])
    # The customer kept browsing: the restored lines merge with the current cart.
    await add(client, customer, p, 1)

    assert await _run_expiry() == 1
    assert await _run_expiry() == 0  # second run: nothing more happens
    # The real Celery task function (own event loop + engine) is also a no-op now.
    assert await asyncio.to_thread(release_expired_reservations) == "released 0"

    assert await stock(p.id) == 5
    assert await reservation_statuses(order["id"]) == ["released"]
    assert await cart_quantities(customer.id) == {p.id: 3}
    ent_row = await entitlement(ent.id)
    assert ent_row.status == "issued" and ent_row.order_id is None
    row = await db_order(order["id"])
    assert (
        row.status == "expired" and row.cancel_reason == "reservation_expired" and row.cancelled_at
    )
    assert len(released.calls) == 1
    detail = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert detail["can_cancel"] is False and detail["can_retry_payment"] is False
    r = await intent(client, customer, order["id"])
    assert r.status_code == 409 and r.json()["code"] == "order_not_payable"
    # The released discount can be used again.
    r = await checkout(
        client,
        customer,
        {"delivery_type": "click_and_collect", "discount_entitlement_id": str(ent.id)},
    )
    assert r.status_code == 201, r.text


async def test_celery_task_releases_expired_orders(client, customer):
    p = await create_product(stock_quantity=2)
    order = await placed_order(client, customer, p, 2)
    await expire_order(order["id"])
    assert await asyncio.to_thread(release_expired_reservations) == "released 1"
    assert await stock(p.id) == 2
    assert (await db_order(order["id"])).status == "expired"


async def test_cli_release_command(client, customer, capsys):
    from app.cli.__main__ import main

    p = await create_product(stock_quantity=1)
    order = await placed_order(client, customer, p)
    await expire_order(order["id"])
    assert await asyncio.to_thread(main, ["release-expired-reservations"]) == 0
    assert "released 1" in capsys.readouterr().out
    assert await stock(p.id) == 1


async def test_cart_restore_is_capped(client, customer):
    p = await create_product(stock_quantity=200)
    order = await placed_order(client, customer, p, 60)
    await add(client, customer, p, 60)
    await expire_order(order["id"])
    assert await _run_expiry() == 1
    assert await cart_quantities(customer.id) == {p.id: 99}


async def test_processing_payments_get_a_grace_window(client, customer):
    p = await create_product(stock_quantity=1)
    order = await placed_order(client, customer, p)
    await pay(client, customer, order["id"], "processing")
    await expire_order(order["id"], minutes=1)
    assert await _run_expiry() == 0
    assert (await db_order(order["id"])).status == "pending_payment"
    await expire_order(order["id"], minutes=get_settings().payment_processing_grace_minutes + 1)
    assert await _run_expiry() == 1
    assert (await db_order(order["id"])).status == "expired"


async def test_customer_cancel_releases_once(client, customer, other_customer):
    p = await create_product(stock_quantity=3)
    order = await placed_order(client, customer, p, 2)
    r = await client.post(f"{API}/orders/{order['id']}/cancel", headers=other_customer.headers)
    assert r.status_code == 404
    r = await client.post(f"{API}/orders/{order['id']}/cancel", headers=customer.headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "cancelled" and r.json()["cancel_reason"] == "customer_cancelled"
    assert await stock(p.id) == 3
    assert await cart_quantities(customer.id) == {p.id: 2}
    r = await client.post(f"{API}/orders/{order['id']}/cancel", headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "order_not_cancellable"
    assert await stock(p.id) == 3
    assert await _run_expiry() == 0


async def test_provider_canceled_event_releases(client, customer):
    p = await create_product(stock_quantity=1)
    order = await placed_order(client, customer, p)
    order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
    r = await post_event(client, pi_event(order, "payment_intent.canceled"))
    assert r.json()["outcome"] == "applied"
    row = await db_order(order["id"])
    assert row.status == "cancelled" and row.cancel_reason == "payment_canceled"
    assert await stock(p.id) == 1
    r = await post_event(client, pi_event(order, "payment_intent.canceled"))
    assert r.json()["outcome"] == "stale"
    assert await stock(p.id) == 1


async def test_success_after_expiry_rereserves_when_possible(client, customer, monkeypatch):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=2)
    ent = await seed_entitlement(customer.id, 300)
    await add(client, customer, p, 2)
    order = (
        await checkout(
            client,
            customer,
            {"delivery_type": "click_and_collect", "discount_entitlement_id": str(ent.id)},
        )
    ).json()
    order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
    await expire_order(order["id"])
    assert await _run_expiry() == 1
    assert await cart_quantities(customer.id) == {p.id: 2}
    r = await post_event(client, pi_event(order))
    assert r.json()["outcome"] == "applied"
    row = await db_order(order["id"])
    assert row.status == "paid" and row.paid_at and row.cancel_reason is None
    assert await stock(p.id) == 0
    assert await reservation_statuses(order["id"]) == ["consumed"]
    assert (await entitlement(ent.id)).status == "consumed"
    assert await cart_quantities(customer.id) == {}  # restored lines removed again
    assert len(spy.calls) == 1


async def test_success_after_expiry_without_stock_needs_review(
    client, customer, other_customer, monkeypatch
):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=1)
    order = await placed_order(client, customer, p)
    order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
    await expire_order(order["id"])
    assert await _run_expiry() == 1
    # Someone else buys the released item.
    await placed_order(client, other_customer, p)
    assert await stock(p.id) == 0
    r = await post_event(client, pi_event(order))
    assert r.status_code == 200 and r.json()["outcome"] == "mismatch"
    row = await db_order(order["id"])
    assert row.status == "payment_review" and row.payment_status == "succeeded"
    assert row.review_reason == "paid after reservation released; refund required"
    assert await stock(p.id) == 0  # never negative
    assert await reservation_statuses(order["id"]) == ["released"]
    assert spy.calls == []


async def test_partial_then_full_refund_restocks_once_before_dispatch(
    client, customer, admin, monkeypatch
):
    refunds = EventSpy(monkeypatch, "order_refunded")
    p = await create_product(stock_quantity=5, price_cents=4000)
    order = await paid_order(client, customer, p, 2)  # 8000
    assert await stock(p.id) == 3

    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 3000, "reason": "damaged lid"},
        headers={**admin.headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 202, r.text
    assert (
        r.json()["event_outcome"] == "applied"
        and r.json()["payment_status"] == "partially_refunded"
    )
    assert r.json()["refunded_cents"] == 3000 and r.json()["order_status"] == "paid"
    assert await stock(p.id) == 3  # partial refunds never restock

    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 5001, "reason": "too much"},
        headers={**admin.headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 422 and r.json()["code"] == "refund_exceeds_remaining"
    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 5000, "reason": "cancelled"},
        headers={**admin.headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["payment_status"] == "refunded" and r.json()["order_status"] == "refunded"
    assert await stock(p.id) == 5
    assert await reservation_statuses(order["id"]) == ["restocked"]
    # A re-delivered cumulative refund event changes nothing.
    full = {**order, "payment_intent_id": order["payment_intent_id"]}
    r = await post_event(client, refund_event(full, 8000))
    assert r.json()["outcome"] == "stale"
    assert await stock(p.id) == 5
    assert refunds.calls and len(refunds.calls) == 2
    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 1, "reason": "again"},
        headers={**admin.headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 409


async def test_full_refund_after_dispatch_does_not_restock(client, customer, admin, dispatcher):
    p = await create_product(stock_quantity=2, weight_grams=800)
    await add(client, customer, p)
    order = (await courier_checkout(client, customer)).json()
    await pay(client, customer, order["id"])
    r = await client.patch(
        f"{API}/orders/{order['id']}/fulfilment",
        json={"status": "ready_for_dispatch"},
        headers=dispatcher.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{API}/orders/{order['id']}/fulfilment",
        json={"status": "dispatched", "tracking_number": "NZP123", "courier": "NZ Post"},
        headers=dispatcher.headers,
    )
    assert r.status_code == 200 and r.json()["tracking"]["tracking_number"] == "NZP123"
    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": order["total_cents"], "reason": "lost in transit"},
        headers={**admin.headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"},
    )
    assert r.status_code == 202
    row = await db_order(order["id"])
    assert row.payment_status == "refunded" and row.status == "dispatched"
    assert await stock(p.id) == 1
    assert await reservation_statuses(order["id"]) == ["consumed"]


async def test_customers_and_operators_cannot_fulfil_or_refund(
    client, customer, operator, dispatcher
):
    p = await create_product()
    order = await paid_order(client, customer, p)
    for actor in (customer, operator):
        r = await client.patch(
            f"{API}/orders/{order['id']}/fulfilment",
            json={"status": "collected"},
            headers=actor.headers,
        )
        assert r.status_code == 403
        r = await client.post(
            f"{API}/orders/{order['id']}/refund",
            json={"amount_cents": 100, "reason": "nope"},
            headers=actor.headers,
        )
        assert r.status_code == 403
        assert (
            await client.get(f"{API}/orders/admin/all", headers=actor.headers)
        ).status_code == 403
    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 100, "reason": "nope"},
        headers=dispatcher.headers,
    )
    assert r.status_code == 403  # refunds are admin-only
    # Clients cannot smuggle a status into checkout either.
    await add(client, customer, p)
    r = await checkout(client, customer, {"delivery_type": "click_and_collect", "status": "paid"})
    assert r.status_code == 422
    row = await db_order(order["id"])
    assert row.status == "paid" and row.refunded_cents == 0


async def test_fulfilment_follows_the_state_machine(client, customer, dispatcher):
    p = await create_product()
    unpaid = await placed_order(client, customer, p)
    r = await client.patch(
        f"{API}/orders/{unpaid['id']}/fulfilment",
        json={"status": "collected"},
        headers=dispatcher.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "order_not_paid"
    order = await paid_order(client, customer, p)
    r = await client.patch(
        f"{API}/orders/{order['id']}/fulfilment",
        json={"status": "dispatched"},
        headers=dispatcher.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"
    r = await client.patch(
        f"{API}/orders/{order['id']}/fulfilment",
        json={"status": "collected"},
        headers=dispatcher.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "collected"


async def test_order_access_is_owner_only(client, customer, other_customer, dispatcher):
    p = await create_product()
    order = await placed_order(client, customer, p)
    assert (
        await client.get(f"{API}/orders/{order['id']}", headers=other_customer.headers)
    ).status_code == 404
    assert (
        await client.get(f"{API}/orders/{order['id']}", headers=dispatcher.headers)
    ).status_code == 404
    assert (await intent(client, other_customer, order["id"])).status_code == 404
    mine = (await client.get(f"{API}/orders/", headers=customer.headers)).json()
    assert (
        mine["total"] == 1
        and mine["items"][0]["id"] == order["id"]
        and mine["items"][0]["item_count"] == 1
    )
    assert (await client.get(f"{API}/orders/", headers=other_customer.headers)).json()["total"] == 0
    staff = (
        await client.get(f"{API}/orders/admin/{order['id']}", headers=dispatcher.headers)
    ).json()
    assert staff["user_id"] == str(customer.id)


async def test_order_list_pagination_and_admin_filters(client, customer, admin):
    p = await create_product(stock_quantity=10)
    ids = [(await placed_order(client, customer, p))["id"] for _ in range(3)]
    await pay(client, customer, ids[0])
    page = (await client.get(f"{API}/orders/?page=1&page_size=2", headers=customer.headers)).json()
    assert page["total"] == 3 and len(page["items"]) == 2 and page["page_size"] == 2
    page2 = (await client.get(f"{API}/orders/?page=2&page_size=2", headers=customer.headers)).json()
    assert {o["id"] for o in page["items"] + page2["items"]} == set(ids)
    paid = (await client.get(f"{API}/orders/admin/all?status=paid", headers=admin.headers)).json()
    assert [o["id"] for o in paid["items"]] == [ids[0]]
    pending = (
        await client.get(
            f"{API}/orders/admin/all?payment_status=unpaid&delivery_type=click_and_collect",
            headers=admin.headers,
        )
    ).json()
    assert pending["total"] == 2
    number = (await db_order(ids[1])).order_number
    found = (
        await client.get(f"{API}/orders/admin/all?order_number={number}", headers=admin.headers)
    ).json()
    assert [o["id"] for o in found["items"]] == [ids[1]]
    r = await client.get(f"{API}/orders/admin/all?status=bogus", headers=admin.headers)
    assert r.status_code == 422


async def test_courier_shipment_local_contract_adapter(client, customer, dispatcher, monkeypatch):
    p = await create_product(weight_grams=500)
    await add(client, customer, p)
    order = (await courier_checkout(client, customer)).json()
    r = await client.post(f"{API}/orders/{order['id']}/shipment", headers=dispatcher.headers)
    assert r.status_code == 409 and r.json()["code"] == "order_not_ready"
    await pay(client, customer, order["id"])
    r = await client.post(f"{API}/orders/{order['id']}/shipment", headers=customer.headers)
    assert r.status_code == 403
    r = await client.post(f"{API}/orders/{order['id']}/shipment", headers=dispatcher.headers)
    assert r.status_code == 201, r.text
    shipment = r.json()
    assert shipment["is_test"] is True and shipment["tracking_number"].startswith("TEST-")
    assert shipment["provider"] == "local_contract"
    again = await client.post(f"{API}/orders/{order['id']}/shipment", headers=dispatcher.headers)
    assert again.status_code == 200 and again.json()["id"] == shipment["id"]
    detail = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert detail["tracking"] == {
        "tracking_number": shipment["tracking_number"],
        "courier": "local_contract",
        "shipment_status": "label_created",
        "is_test": True,
    }

    # Outside development/test there is no live booking.
    p2 = await create_product(weight_grams=500)
    await add(client, customer, p2)
    order2 = (await courier_checkout(client, customer)).json()
    await pay(client, customer, order2["id"])
    monkeypatch.setattr(get_settings(), "app_env", "production")
    r = await client.post(f"{API}/orders/{order2['id']}/shipment", headers=dispatcher.headers)
    assert r.status_code == 503 and r.json()["code"] == "courier_booking_unavailable"


async def test_click_and_collect_orders_have_no_courier_shipment(client, customer, dispatcher):
    p = await create_product()
    order = await paid_order(client, customer, p)
    r = await client.post(f"{API}/orders/{order['id']}/shipment", headers=dispatcher.headers)
    assert r.status_code == 409 and r.json()["code"] == "not_a_courier_order"


async def test_order_paid_fires_once_per_order_across_many_events(client, customer, monkeypatch):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=10)
    orders = [await placed_order(client, customer, p) for _ in range(2)]
    for o in orders:
        o.update((await intent(client, customer, o["id"])).json())
        event = pi_event(o)
        for _ in range(3):
            await post_event(client, event)
        await post_event(client, pi_event(o))
    assert sorted(map(str, spy.calls)) == sorted(o["order_id"] for o in orders)
    assert await stock(p.id) == 8
