"""Checkout: server-computed totals, quote binding, idempotency and stock races."""

import asyncio

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update

from app.config import get_settings
from app.database import async_session
from app.main import app
from app.models.order import Order
from app.models.product import Product
from app.models.shipping import DeliveryQuote
from app.tests.conftest import create_actor, create_product
from app.tests.test_commerce_support import (
    ADDRESS,
    API,
    CONTACT,
    add,
    cart_quantities,
    checkout,
    courier_checkout,
    entitlement,
    expire_quote,
    idem,
    intent,
    pay,
    quote,
    reservation_statuses,
    seed_area,
    seed_entitlement,
    stock,
)


async def test_charged_total_is_sale_price_plus_server_shipping_minus_discount(client, customer):
    p = await create_product(price_cents=10000, sale_price_cents=7999, weight_grams=2000, stock_quantity=5)
    cart = await add(client, customer, p)
    assert cart["subtotal_cents"] == 7999
    ent = await seed_entitlement(customer.id, 1000)
    q = (await quote(client, customer, "courier")).json()
    assert q["price_cents"] == 1290 and q["parcel_weight_grams"] == 2000
    body = {
        "delivery_type": "courier",
        "quote_id": q["id"],
        "shipping_address": ADDRESS,
        "discount_entitlement_id": str(ent.id),
    }
    preview = await client.post(f"{API}/orders/checkout/preview", json=body, headers=customer.headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_cents"] == 7999 - 1000 + 1290

    r = await checkout(client, customer, body)
    assert r.status_code == 201, r.text
    order = r.json()
    assert (order["subtotal_cents"], order["discount_cents"], order["shipping_cents"]) == (
        7999,
        1000,
        1290,
    )
    assert order["total_cents"] == 8289 == preview.json()["total_cents"]
    assert order["status"] == "pending_payment" and order["payment_status"] == "unpaid"
    assert order["order_number"].startswith("HM-") and order["can_cancel"] and order["can_retry_payment"]
    item = order["items"][0]
    assert (item["list_price_cents"], item["unit_price_cents"], item["line_total_cents"]) == (
        10000,
        7999,
        7999,
    )
    assert order["delivery"]["shipping_address"]["postcode"] == "1010"
    assert order["expires_at"] is not None
    # Stock reserved, cart moved into the order, discount reserved for this order.
    assert await stock(p.id) == 4
    assert await reservation_statuses(order["id"]) == ["reserved"]
    assert await cart_quantities(customer.id) == {}
    ent_row = await entitlement(ent.id)
    assert ent_row.status == "reserved" and str(ent_row.order_id) == order["id"]

    # The charged amount is the order total.
    pi = await intent(client, customer, order["id"])
    assert pi.status_code == 200, pi.text
    assert pi.json()["amount_cents"] == 8289 and pi.json()["currency"] == "NZD"
    assert pi.json()["test_mode"] is True and pi.json()["provider"] == "local"


async def test_free_shipping_threshold_applies_after_discount(client, customer):
    p = await create_product(price_cents=10000, weight_grams=1000, stock_quantity=10)
    await add(client, customer, p, 2)  # 20000 >= 15000
    r = await courier_checkout(client, customer)
    assert r.status_code == 201, r.text
    assert r.json()["shipping_cents"] == 0 and r.json()["total_cents"] == 20000
    assert r.json()["delivery"]["free_shipping_applied"] is True

    other = await create_actor()
    await add(client, other, p, 2)
    ent = await seed_entitlement(other.id, 6000)  # 20000 - 6000 = 14000 < threshold
    r = await courier_checkout(client, other, discount_entitlement_id=str(ent.id))
    assert r.status_code == 201, r.text
    assert (r.json()["discount_cents"], r.json()["shipping_cents"], r.json()["total_cents"]) == (
        6000,
        1290,
        15290,
    )


async def test_click_and_collect_is_free_and_needs_no_quote(client, customer):
    p = await create_product(price_cents=2500, weight_grams=None)  # no weight needed
    await add(client, customer, p)
    r = await checkout(client, customer, {"delivery_type": "click_and_collect"})
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["shipping_cents"] == 0 and order["total_cents"] == 2500
    assert order["delivery"]["pickup_location"] == get_settings().click_and_collect_location
    assert order["delivery"]["quote_id"] is None

    await add(client, customer, p)
    q = await quote(client, customer, "courier")
    assert q.status_code == 422 and q.json()["code"] == "weight_unknown"
    r = await checkout(client, customer, {"delivery_type": "click_and_collect", "quote_id": order["id"]})
    assert r.status_code == 422 and r.json()["code"] == "quote_not_applicable"


async def test_helm_dash_checkout_uses_quote_and_contact(client, customer):
    await seed_area()
    p = await create_product(price_cents=5000)
    await add(client, customer, p)
    q = await quote(client, customer, "helm_dash")
    assert q.status_code == 201, q.text
    body = {"delivery_type": "helm_dash", "quote_id": q.json()["id"]}
    r = await checkout(client, customer, body)
    assert r.status_code == 422 and r.json()["code"] == "helm_dash_contact_required"
    r = await checkout(client, customer, {**body, "helm_dash_contact": CONTACT})
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["shipping_cents"] == q.json()["price_cents"]
    assert order["total_cents"] == 5000 + q.json()["price_cents"]
    hd = order["delivery"]["helm_dash"]
    assert hd["vessel_name"] == "Sea Biscuit" and hd["lat"] == -36.79 and hd["operating_area_id"] == "hauraki-gulf"
    assert order["delivery"]["estimated_minutes"] == q.json()["estimated_minutes"]


async def test_quote_must_be_owned_unexpired_unused_and_match_the_cart(client, customer, other_customer):
    p = await create_product(stock_quantity=20)
    p2 = await create_product(stock_quantity=20)
    await add(client, customer, p)
    await add(client, other_customer, p)

    def body(qid, **extra):
        return {"delivery_type": "courier", "quote_id": qid, "shipping_address": ADDRESS, **extra}

    # Another user's quote is invisible.
    theirs = (await quote(client, other_customer)).json()
    r = await checkout(client, customer, body(theirs["id"]))
    assert r.status_code == 404 and r.json()["code"] == "quote_not_found"

    # Expired.
    q = (await quote(client, customer)).json()
    await expire_quote(q["id"])
    r = await checkout(client, customer, body(q["id"]))
    assert r.status_code == 409 and r.json()["code"] == "quote_expired"

    # Cart changed after the quote.
    q = (await quote(client, customer)).json()
    await add(client, customer, p2)
    r = await checkout(client, customer, body(q["id"]))
    assert r.status_code == 409 and r.json()["code"] == "quote_cart_changed"

    # Wrong type / wrong postcode / missing address.
    await seed_area()
    hd = (await quote(client, customer, "helm_dash")).json()
    r = await checkout(client, customer, body(hd["id"]))
    assert r.status_code == 422 and r.json()["code"] == "quote_type_mismatch"
    q = (await quote(client, customer)).json()
    r = await checkout(client, customer, body(q["id"], shipping_address={**ADDRESS, "postcode": "9016"}))
    assert r.status_code == 422 and r.json()["code"] == "quote_destination_mismatch"
    r = await checkout(client, customer, {"delivery_type": "courier", "quote_id": q["id"]})
    assert r.status_code == 422 and r.json()["code"] == "shipping_address_required"
    r = await checkout(client, customer, {"delivery_type": "courier", "shipping_address": ADDRESS})
    assert r.status_code == 422 and r.json()["code"] == "quote_required"

    # Used once only.
    r = await checkout(client, customer, body(q["id"]))
    assert r.status_code == 201, r.text
    await add(client, customer, p)
    await add(client, customer, p2)
    r = await checkout(client, customer, body(q["id"]))
    assert r.status_code == 409 and r.json()["code"] == "quote_used"
    async with async_session() as s:
        used = (await s.execute(select(DeliveryQuote.used_by_order_id).where(DeliveryQuote.id == q["id"]))).scalar_one()
    assert used is not None


async def test_dangerous_goods_restricted_to_configured_delivery_types(client, customer):
    fuel = await create_product(name="Outboard Fuel Additive 1L", dangerous_goods=True, weight_grams=1100)
    rope = await create_product(name="Mooring Line", weight_grams=900)
    await add(client, customer, rope)
    q = (await quote(client, customer)).json()  # quoted before the DG item was added
    await add(client, customer, fuel)
    r = await checkout(
        client,
        customer,
        {"delivery_type": "courier", "quote_id": q["id"], "shipping_address": ADDRESS},
    )
    assert r.status_code == 422 and r.json()["code"] == "dangerous_goods_restricted"
    assert [x["product_id"] for x in r.json()["products"]] == [str(fuel.id)]
    assert r.json()["allowed_delivery_types"] == ["click_and_collect"]
    assert "approv" not in r.json()["detail"].lower()
    # The same cart can be collected.
    r = await checkout(client, customer, {"delivery_type": "click_and_collect"})
    assert r.status_code == 201, r.text


async def test_idempotent_checkout_and_double_tap(client, customer):
    p = await create_product(stock_quantity=5)
    await add(client, customer, p, 2)
    key = idem()
    first = await checkout(client, customer, key=key)
    assert first.status_code == 201, first.text
    again = await checkout(client, customer, {"delivery_type": "courier"}, key=key)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert await stock(p.id) == 3

    # Concurrent double tap with one key: one order, one reservation.
    await add(client, customer, p, 1)
    key = idem()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c2:
        r1, r2 = await asyncio.gather(checkout(client, customer, key=key), checkout(c2, customer, key=key))
    assert sorted([r1.status_code, r2.status_code]) == [200, 201]
    assert r1.json()["id"] == r2.json()["id"]
    assert await stock(p.id) == 2
    async with async_session() as s:
        n = (await s.execute(select(func.count()).select_from(Order).where(Order.user_id == customer.id))).scalar_one()
    assert n == 2


async def test_concurrent_last_item_exactly_one_wins(client):
    buyers = [await create_actor(), await create_actor()]
    p = await create_product(stock_quantity=1)
    for b in buyers:
        await add(client, b, p)
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c1,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c2,
    ):
        results = await asyncio.gather(checkout(c1, buyers[0]), checkout(c2, buyers[1]))
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["code"] == "insufficient_stock" and loser.json()["product_ids"] == [str(p.id)]
    assert await stock(p.id) == 0
    async with async_session() as s:
        assert (await s.execute(select(func.count()).select_from(Order))).scalar_one() == 1


async def test_last_item_race_is_decided_by_the_conditional_update(client, monkeypatch):
    """Both checkouts are held at the reservation step until both have validated the
    cart (stock looked sufficient to each), so only the conditional UPDATE decides."""
    from app.services import reservations

    original = reservations.decrement_stock
    barrier = asyncio.Barrier(2)
    results: list[list] = []

    async def gated(db, lines):
        async with asyncio.timeout(10):
            await barrier.wait()
        failed = await original(db, lines)
        results.append(failed)
        return failed

    monkeypatch.setattr(reservations, "decrement_stock", gated)
    buyers = [await create_actor(), await create_actor()]
    p = await create_product(stock_quantity=1)
    for b in buyers:
        await add(client, b, p)
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c1,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c2,
    ):
        responses = await asyncio.gather(checkout(c1, buyers[0]), checkout(c2, buyers[1]))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert sorted(len(f) for f in results) == [0, 1]  # both reached the UPDATE; one lost
    assert await stock(p.id) == 0


async def test_failed_checkout_rolls_back_everything(client, customer):
    a = await create_product(stock_quantity=5, weight_grams=500)
    b = await create_product(stock_quantity=1, weight_grams=500)
    await add(client, customer, a, 2)
    await add(client, customer, b, 1)
    ent = await seed_entitlement(customer.id, 500)
    q = (await quote(client, customer)).json()
    async with async_session() as s:
        await s.execute(update(Product).where(Product.id == b.id).values(stock_quantity=0))
        await s.commit()
    r = await checkout(
        client,
        customer,
        {
            "delivery_type": "courier",
            "quote_id": q["id"],
            "shipping_address": ADDRESS,
            "discount_entitlement_id": str(ent.id),
        },
    )
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    assert r.json()["product_ids"] == [str(b.id)]
    assert await stock(a.id) == 5
    assert (await entitlement(ent.id)).status == "issued"
    assert await cart_quantities(customer.id) == {a.id: 2, b.id: 1}
    async with async_session() as s:
        assert (
            await s.execute(select(DeliveryQuote.used_by_order_id).where(DeliveryQuote.id == q["id"]))
        ).scalar_one() is None
        assert (await s.execute(select(func.count()).select_from(Order))).scalar_one() == 0


async def test_checkout_input_validation(client, customer, other_customer):
    p = await create_product(price_cents=40)
    r = await checkout(client, customer)
    assert r.status_code == 422 and r.json()["code"] == "cart_empty"
    await add(client, customer, p)
    r = await checkout(client, customer)
    assert r.status_code == 422 and r.json()["code"] == "below_minimum_charge"

    for bad_key in (None, "short", "x" * 101, "has space in it"):
        headers = dict(customer.headers)
        if bad_key is not None:
            headers["Idempotency-Key"] = bad_key
        r = await client.post(f"{API}/orders/checkout", json={"delivery_type": "click_and_collect"}, headers=headers)
        assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"

    r = await checkout(client, customer, {"delivery_type": "click_and_collect", "payment_method": "afterpay"})
    assert r.status_code == 422 and r.json()["code"] == "payment_method_unavailable"
    assert "Afterpay" in r.json()["detail"]
    r = await checkout(client, customer, {"delivery_type": "click_and_collect", "total_cents": 1})
    assert r.status_code == 422
    r = await client.post(
        f"{API}/orders/checkout",
        json={"delivery_type": "click_and_collect"},
        headers={"Idempotency-Key": idem()},
    )
    assert r.status_code == 401


async def test_discount_entitlement_rules(client, customer, other_customer):
    p = await create_product(price_cents=3000)
    await add(client, customer, p)
    theirs = await seed_entitlement(other_customer.id, 500)
    r = await checkout(
        client,
        customer,
        {"delivery_type": "click_and_collect", "discount_entitlement_id": str(theirs.id)},
    )
    assert r.status_code == 404 and r.json()["code"] == "entitlement_not_found"
    used = await seed_entitlement(customer.id, 500, status="consumed")
    r = await checkout(
        client,
        customer,
        {"delivery_type": "click_and_collect", "discount_entitlement_id": str(used.id)},
    )
    assert r.status_code == 409 and r.json()["code"] == "entitlement_unavailable"
    big = await seed_entitlement(customer.id, 3001)
    r = await checkout(
        client,
        customer,
        {"delivery_type": "click_and_collect", "discount_entitlement_id": str(big.id)},
    )
    assert r.status_code == 422 and r.json()["code"] == "discount_exceeds_subtotal"
    ok = await seed_entitlement(customer.id, 3000 - 50)
    r = await checkout(
        client,
        customer,
        {"delivery_type": "click_and_collect", "discount_entitlement_id": str(ok.id)},
    )
    assert r.status_code == 201 and r.json()["total_cents"] == 50
    # It cannot be used twice.
    await add(client, customer, p)
    r = await checkout(
        client,
        customer,
        {"delivery_type": "click_and_collect", "discount_entitlement_id": str(ok.id)},
    )
    assert r.status_code == 409 and r.json()["code"] == "entitlement_unavailable"


async def test_inactive_product_blocks_checkout(client, customer):
    p = await create_product()
    await add(client, customer, p)
    async with async_session() as s:
        await s.execute(update(Product).where(Product.id == p.id).values(is_active=False))
        await s.commit()
    r = await checkout(client, customer)
    assert r.status_code == 409 and r.json()["code"] == "product_unavailable"


async def test_payments_disabled_refuses_checkout_and_intent(client, customer, monkeypatch):
    p = await create_product()
    await add(client, customer, p, 2)
    order = (await checkout(client, customer)).json()
    await add(client, customer, p)
    monkeypatch.setattr(get_settings(), "payment_provider", "disabled")
    r = await checkout(client, customer)
    assert r.status_code == 503 and r.json()["code"] == "payments_unavailable"
    assert await stock(p.id) == 48
    r = await intent(client, customer, order["id"])
    assert r.status_code == 503 and r.json()["code"] == "payments_unavailable"
    detail = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert detail["can_retry_payment"] is False


async def test_paid_flow_end_to_end_keeps_amounts(client, customer):
    p = await create_product(price_cents=4500, sale_price_cents=3900, stock_quantity=3)
    await add(client, customer, p, 2)
    order = (await checkout(client, customer)).json()
    result = await pay(client, customer, order["id"])
    assert result["order_status"] == "paid" and result["payment_status"] == "succeeded"
    detail = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert detail["total_cents"] == 7800 and detail["paid_at"] is not None
    assert detail["can_cancel"] is False and detail["can_retry_payment"] is False
    assert await stock(p.id) == 1
    assert await reservation_statuses(order["id"]) == ["consumed"]
