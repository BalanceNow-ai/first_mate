"""Cross-workstream journeys driven only through the public API (real tokens, real DB).

Each workstream tested its own side; these tests prove the hand-offs between them:
checkout -> signed payment event -> points -> Helm Dash job -> dispatch -> order status
-> payout record -> notifications -> refund reversal; and AI/checklist -> cart -> order.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import async_session
from app.models.loyalty import PointsTransaction
from app.models.notifications import NotificationOutbox
from app.tests.conftest import add_fitment_rule, create_actor, create_product, create_vessel
from app.tests.test_commerce_support import CONTACT, WAIHEKE, add, idem, pay

API = "/api/v1"


async def _setup_helm_dash(client, admin, operator):
    r = await client.post(
        f"{API}/dispatch/areas",
        json={"id": "hauraki-gulf", "name": "Hauraki Gulf", "center_lat": -36.75,
              "center_lng": 175.0, "radius_nm": 25, "enabled": True},
        headers=admin.headers,
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"{API}/dispatch/operators",
        json={"user_id": str(operator.id), "display_name": "Skipper Sam", "vessel_name": "Dash One",
              "area_id": "hauraki-gulf"},
        headers=admin.headers,
    )
    assert r.status_code in (200, 201), r.text
    r = await client.post(f"{API}/dispatch/operators/{operator.id}/activate", headers=admin.headers)
    assert r.status_code == 200, r.text


async def test_helm_dash_purchase_to_delivery_and_refund(client, customer, admin, dispatcher, operator):
    await _setup_helm_dash(client, admin, operator)
    product = await create_product(price_cents=12000, sale_price_cents=9950, stock_quantity=5, weight_grams=900)
    cart = await add(client, customer, product, 2)
    assert cart["subtotal_cents"] == 19900  # sale price used in the cart

    q = await client.post(f"{API}/shipping/quotes", json={"delivery_type": "helm_dash", "destination": WAIHEKE},
                          headers=customer.headers)
    assert q.status_code == 201, q.text
    quote = q.json()
    r = await client.post(
        f"{API}/orders/checkout",
        json={"delivery_type": "helm_dash", "quote_id": quote["id"], "helm_dash_contact": CONTACT},
        headers={**customer.headers, "Idempotency-Key": idem()},
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["subtotal_cents"] == 19900 and order["shipping_cents"] == quote["price_cents"]
    assert order["total_cents"] == 19900 + quote["price_cents"]

    intent = (await client.post(f"{API}/payments/orders/{order['id']}/intent", headers=customer.headers)).json()
    assert intent["amount_cents"] == order["total_cents"] and intent["currency"] == "NZD"
    await pay(client, customer, order["id"])
    order = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert order["status"] == "paid" and order["payment_status"] == "succeeded"

    # Points: 1 CP per whole dollar of merchandise (shipping excluded), exactly once.
    points = (await client.get(f"{API}/loyalty/points", headers=customer.headers)).json()
    assert points["points_balance"] == 199

    # Delivery job created from the paid order; customer sees no fabricated position.
    deliveries = (await client.get(f"{API}/helm-dash/deliveries", headers=customer.headers)).json()
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d["status"] == "awaiting_dispatch" and d["latest_location"] is None
    assert d["delivery_fee_cents"] == quote["price_cents"]

    # Customers and operators cannot dispatch; dispatcher assigns; operator works the job.
    assert (await client.post(f"{API}/dispatch/deliveries/{d['id']}/assign",
                              json={"operator_id": str(operator.id)}, headers=customer.headers)).status_code == 403
    r = await client.post(f"{API}/dispatch/deliveries/{d['id']}/assign",
                          json={"operator_id": str(operator.id)}, headers=dispatcher.headers)
    assert r.status_code == 200, r.text
    assert (await client.post(f"{API}/dispatch/jobs/{d['id']}/accept", headers=operator.headers)).status_code == 200
    now = datetime.now(UTC).isoformat()
    r = await client.post(f"{API}/dispatch/jobs/{d['id']}/location",
                          json={"lat": -36.80, "lng": 174.90, "recorded_at": now}, headers=operator.headers)
    assert r.status_code == 201, r.text
    for status in ("picked_up", "en_route", "delivered"):
        r = await client.post(f"{API}/dispatch/jobs/{d['id']}/status", json={"status": status}, headers=operator.headers)
        assert r.status_code == 200, (status, r.text)
        if status == "picked_up":
            o = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
            assert o["status"] == "dispatched"
    tracking = (await client.get(f"{API}/helm-dash/deliveries/{d['id']}", headers=customer.headers)).json()
    assert tracking["status"] == "delivered"
    assert tracking["latest_location"]["source"] == "operator_device"
    assert (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()["status"] == "delivered"

    payouts = (await client.get(f"{API}/dispatch/payouts", headers=admin.headers)).json()
    assert len(payouts) == 1 and payouts[0]["status"] == "rate_unconfigured" and payouts[0]["amount_cents"] is None

    # Admin full refund after delivery: points reversed, no restock after dispatch.
    r = await client.post(f"{API}/orders/{order['id']}/refund",
                          json={"amount_cents": order["total_cents"], "reason": "Integration test refund"},
                          headers={**admin.headers, "Idempotency-Key": f"refund-{uuid.uuid4().hex}"})
    assert r.status_code == 202, r.text
    o = (await client.get(f"{API}/orders/{order['id']}", headers=customer.headers)).json()
    assert o["payment_status"] == "refunded" and o["refunded_cents"] == order["total_cents"]
    assert (await client.get(f"{API}/loyalty/points", headers=customer.headers)).json()["points_balance"] == 0

    async with async_session() as s:
        kinds = [t.kind for t in (await s.execute(
            select(PointsTransaction).where(PointsTransaction.user_id == customer.id)
            .order_by(PointsTransaction.created_at))).scalars()]
        templates = {n.template for n in (await s.execute(
            select(NotificationOutbox).where(NotificationOutbox.user_id == customer.id))).scalars()}
    assert kinds == ["earn", "earn_reversal"]
    assert {"order_confirmed", "order_refunded"} <= templates


async def test_points_discount_redeemed_once_at_checkout(client, customer):
    product = await create_product(price_cents=50000, stock_quantity=10, weight_grams=500)
    await add(client, customer, product, 1)
    first = (await client.post(f"{API}/orders/checkout", json={"delivery_type": "click_and_collect"},
                               headers={**customer.headers, "Idempotency-Key": idem()})).json()
    await pay(client, customer, first["id"])
    assert (await client.get(f"{API}/loyalty/points", headers=customer.headers)).json()["points_balance"] == 500

    ent = await client.post(f"{API}/loyalty/redeem/discount", json={"points": 500}, headers=customer.headers)
    assert ent.status_code == 201, ent.text
    ent = ent.json()
    assert ent["amount_cents"] == 500
    await add(client, customer, product, 1)
    body = {"delivery_type": "click_and_collect", "discount_entitlement_id": ent["id"]}
    second = await client.post(f"{API}/orders/checkout", json=body,
                               headers={**customer.headers, "Idempotency-Key": idem()})
    assert second.status_code == 201, second.text
    second = second.json()
    assert second["discount_cents"] == 500 and second["total_cents"] == 49500 and second["shipping_cents"] == 0
    await pay(client, customer, second["id"])
    ents = (await client.get(f"{API}/loyalty/entitlements", headers=customer.headers)).json()
    assert [e["status"] for e in ents] == ["consumed"]
    # The consumed entitlement cannot be reused.
    await add(client, customer, product, 1)
    third = await client.post(f"{API}/orders/checkout", json=body, headers={**customer.headers, "Idempotency-Key": idem()})
    assert third.status_code == 409
    # Points earned on the discounted order are based on the amount actually paid for goods.
    assert (await client.get(f"{API}/loyalty/points", headers=customer.headers)).json()["points_balance"] == 495


async def test_ai_recommendation_and_checklist_reach_the_cart(client, customer, admin):
    vessel = await create_vessel(customer.id, engine_make="Yamaha", engine_model="F150")
    plug = await create_product(sku="SYN-PLUG-150", name="Synthetic spark plug F150", part_role="spark_plug",
                                fitment_scope="specific", oem_part_numbers=["SYN-PLUG-150"], stock_quantity=8,
                                price_cents=1890, weight_grams=60)
    await add_fitment_rule(plug.id, engine_make="Yamaha", engine_model="F150")
    # Ingest + admit the synthetic engine source through the admin API.
    from pathlib import Path
    doc = Path(__file__).resolve().parents[1] / "seed" / "knowledge"
    f150 = next(p for p in doc.glob("*.md") if "f150" in p.name.lower())
    from app.services.rag.chunking import parse_front_matter
    meta, body = parse_front_matter(f150.read_text())
    payload = {k: meta[k] for k in ("title", "publisher", "licence", "domain") if k in meta}
    payload.update({"licence_verified": False, "is_synthetic": True, "applies_to": meta.get("applies_to", {}),
                    "facts": meta.get("facts", []), "format": "markdown", "content": body})
    r = await client.post(f"{API}/knowledge/sources", json=payload, headers=admin.headers)
    assert r.status_code == 201, r.text
    sid = r.json()["source"]["id"]
    assert (await client.post(f"{API}/knowledge/sources/{sid}/admit", headers=admin.headers)).status_code == 200

    chat = await client.post(f"{API}/ai/chat", json={"message": "Which spark plug does my Yamaha F150 need?",
                                                     "vessel_id": str(vessel.id)}, headers=customer.headers)
    assert chat.status_code == 200, chat.text
    chat = chat.json()
    assert chat["grounding"]["status"] == "grounded" and chat["citations"]
    action = next(a for a in chat["actions"] if a["product_id"] == str(plug.id))
    cart = await client.post(f"{API}/cart/items", json={"product_id": action["product_id"],
                                                        "quantity": action["quantity"]}, headers=customer.headers)
    assert cart.status_code == 201

    # Checklist links the same verified part and "add missing" is idempotent with the cart.
    gen = await client.post(f"{API}/checklists/vessel/{vessel.id}/generate", headers=customer.headers)
    assert gen.status_code == 201, gen.text
    plug_items = [i for t in gen.json()["tiers"] for i in t["items"] if i["part_role"] == "spark_plug"]
    assert plug_items and plug_items[0]["product"]["id"] == str(plug.id)
    assert plug_items[0]["link_status"] == "verified_fit"
    for _ in range(2):
        r = await client.post(f"{API}/checklists/vessel/{vessel.id}/add-missing-to-cart",
                              json={"tier": "grab_and_go"}, headers=customer.headers)
        assert r.status_code == 200, r.text
    lines = (await client.get(f"{API}/cart/", headers=customer.headers)).json()["items"]
    assert [ln["quantity"] for ln in lines if ln["product_id"] == str(plug.id)] == [max(action["quantity"], plug_items[0]["quantity"])]


async def test_cross_owner_denials_across_domains(client, customer, other_customer):
    vessel = await create_vessel(other_customer.id)
    product = await create_product()
    checks = [
        ("get", f"{API}/vessels/{vessel.id}"),
        ("get", f"{API}/vessels/{vessel.id}/equipment"),
        ("get", f"{API}/vessels/{vessel.id}/service-records"),
        ("get", f"{API}/checklists/vessel/{vessel.id}"),
        ("get", f"{API}/products/{product.id}/fitment?vessel_id={vessel.id}"),
        ("get", f"{API}/products/?vessel_id={vessel.id}"),
    ]
    for method, url in checks:
        r = await getattr(client, method)(url, headers=customer.headers)
        assert r.status_code == 404, (url, r.status_code)
    r = await client.post(f"{API}/ai/chat", json={"message": "hi", "vessel_id": str(vessel.id)}, headers=customer.headers)
    assert r.status_code == 404
    # Public catalogue with another owner's vessel id and no token: refused, nothing leaked.
    r = await client.get(f"{API}/products/?vessel_id={vessel.id}")
    assert r.status_code == 401 and "Stabi" not in r.text
    assert (await create_actor()).role == "customer"
