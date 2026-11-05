"""Local test-mode payments through the signed webhook state machine."""

import json

from app.config import get_settings
from app.tests.conftest import create_product
from app.tests.test_commerce_support import (
    API,
    EventSpy,
    add,
    checkout,
    confirm,
    db_order,
    entitlement,
    intent,
    pay,
    payment_events,
    pi_event,
    placed_order,
    post_event,
    refund_event,
    reservation_statuses,
    seed_entitlement,
    stock,
)


async def _order_detail(client, actor, order_id):
    return (await client.get(f"{API}/orders/{order_id}", headers=actor.headers)).json()


async def test_local_success_marks_paid_once_and_consumes(client, customer, monkeypatch):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=4, price_cents=2000)
    await add(client, customer, p, 2)
    ent = await seed_entitlement(customer.id, 500)
    order = (
        await checkout(
            client,
            customer,
            {"delivery_type": "click_and_collect", "discount_entitlement_id": str(ent.id)},
        )
    ).json()
    pi = (await intent(client, customer, order["id"])).json()
    assert pi["payment_intent_id"].startswith("pi_local_") and pi["test_mode"] is True
    assert pi["client_secret"].startswith(pi["payment_intent_id"] + "_secret_")
    # Intent creation is idempotent.
    again = (await intent(client, customer, order["id"])).json()
    assert again["payment_intent_id"] == pi["payment_intent_id"] and again["client_secret"] == pi["client_secret"]

    r = await confirm(client, customer, pi["payment_intent_id"], "succeed")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["test_mode"] and body["event_outcome"] == "applied" and body["order_status"] == "paid"
    assert body["event_id"].startswith("evt_local_")
    assert await stock(p.id) == 2
    assert await reservation_statuses(order["id"]) == ["consumed"]
    assert (await entitlement(ent.id)).status == "consumed"
    assert spy.calls == [db_id := (await db_order(order["id"])).id]

    # Paying again is refused; the intent endpoint is closed for paid orders.
    r = await confirm(client, customer, pi["payment_intent_id"], "succeed")
    assert r.status_code == 409 and r.json()["code"] == "order_already_paid"
    r = await intent(client, customer, order["id"])
    assert r.status_code == 409
    assert spy.calls == [db_id]
    events = await payment_events(order["id"])
    assert [e.outcome for e in events] == ["applied"] and events[0].provider == "local"


async def test_decline_then_retry_succeeds(client, customer):
    p = await create_product()
    order = await placed_order(client, customer, p)
    declined = await pay(client, customer, order["id"], "decline")
    assert declined["payment_status"] == "failed" and declined["order_status"] == "pending_payment"
    detail = await _order_detail(client, customer, order["id"])
    assert detail["can_retry_payment"] and detail["can_cancel"]
    retried = await pay(client, customer, order["id"], "succeed")
    assert retried["order_status"] == "paid" and retried["payment_status"] == "succeeded"


async def test_requires_action_then_authenticate(client, customer):
    p = await create_product()
    order = await placed_order(client, customer, p)
    pi = (await intent(client, customer, order["id"])).json()
    r = await confirm(client, customer, pi["payment_intent_id"], "authenticate")
    assert r.status_code == 409 and r.json()["code"] == "no_action_required"
    r = await confirm(client, customer, pi["payment_intent_id"], "requires_action")
    assert r.json()["payment_status"] == "requires_action"
    assert (await intent(client, customer, order["id"])).json()["status"] == "requires_action"
    r = await confirm(client, customer, pi["payment_intent_id"], "authenticate")
    assert r.json()["order_status"] == "paid"


async def test_processing_status_is_recorded(client, customer):
    p = await create_product()
    order = await placed_order(client, customer, p)
    r = await pay(client, customer, order["id"], "processing")
    assert r["payment_status"] == "processing" and r["order_status"] == "pending_payment"
    detail = await _order_detail(client, customer, order["id"])
    assert detail["can_cancel"] is False
    r = await client.post(f"{API}/orders/{order['id']}/cancel", headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "payment_processing"


async def test_duplicate_and_out_of_order_events_are_no_ops(client, customer, monkeypatch):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=3)
    order = await placed_order(client, customer, p)
    order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
    succeeded = pi_event(order, "payment_intent.succeeded")
    r = await post_event(client, succeeded)
    assert r.status_code == 200 and r.json()["outcome"] == "applied"
    r = await post_event(client, succeeded)
    assert r.status_code == 200 and r.json()["outcome"] == "duplicate"
    # A failure (or requires_action) arriving after success is ignored.
    r = await post_event(client, pi_event(order, "payment_intent.payment_failed"))
    assert r.json()["outcome"] == "stale"
    r = await post_event(client, pi_event(order, "payment_intent.requires_action"))
    assert r.json()["outcome"] == "stale"
    # A second, distinct success event for the same intent changes nothing.
    r = await post_event(client, pi_event(order, "payment_intent.succeeded"))
    assert r.json()["outcome"] == "stale"
    row = await db_order(order["id"])
    assert row.status == "paid" and row.payment_status == "succeeded"
    assert await stock(p.id) == 2
    assert len(spy.calls) == 1
    outcomes = sorted(e.outcome for e in await payment_events(order["id"]))
    assert outcomes == ["applied", "stale", "stale", "stale"]
    # Unknown event types are recorded and ignored.
    r = await post_event(client, {**pi_event(order, "payment_intent.created")})
    assert r.json()["outcome"] == "ignored"


async def test_refund_before_success_is_deferred_without_record(client, customer, monkeypatch):
    spy = EventSpy(monkeypatch, "order_refunded")
    p = await create_product(stock_quantity=3, price_cents=3000)
    order = await placed_order(client, customer, p)
    order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
    refund = refund_event(order, 1000)
    r = await post_event(client, refund)
    assert r.status_code == 409 and r.json()["code"] == "event_deferred"
    assert await payment_events() == []
    r = await post_event(client, pi_event(order))
    assert r.json()["outcome"] == "applied"
    r = await post_event(client, refund)  # Stripe retries the same event
    assert r.status_code == 200 and r.json()["outcome"] == "applied"
    row = await db_order(order["id"])
    assert row.refunded_cents == 1000 and row.payment_status == "partially_refunded" and row.status == "paid"
    assert len(spy.calls) == 1


async def test_signature_is_required_and_verified(client, customer):
    p = await create_product()
    order = await placed_order(client, customer, p)
    order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
    event = pi_event(order)
    r = await post_event(client, event, signature="")
    assert r.status_code == 400 and r.json()["code"] == "missing_signature"
    r = await post_event(client, event, secret="whsec_wrong_secret")
    assert r.status_code == 400 and r.json()["code"] == "invalid_signature"
    r = await post_event(client, event, signature="t=1,v1=deadbeef")
    assert r.status_code == 400
    # A valid signature over a different payload does not verify.
    from app.services.payments import sign_payload

    sig = sign_payload(json.dumps({"id": "evt_other"}), get_settings().local_payment_webhook_secret)
    r = await post_event(client, event, signature=sig)
    assert r.status_code == 400
    assert (await db_order(order["id"])).status == "pending_payment"
    assert await payment_events() == []
    # Signed but malformed events are refused too.
    r = await post_event(client, {"id": "not-an-event", "type": "x", "data": {}})
    assert r.status_code == 400 and r.json()["code"] == "invalid_event"


async def test_amount_and_currency_mismatch_go_to_review_without_effects(client, customer, monkeypatch):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=5, price_cents=5000)
    for change in ({"amount": 4999, "amount_received": 4999}, {"currency": "aud"}):
        await add(client, customer, p)
        order = (await checkout(client, customer)).json()
        order = {**order, **(await intent(client, customer, order["id"])).json(), "id": order["id"]}
        r = await post_event(client, pi_event(order, **change))
        assert r.status_code == 200 and r.json()["outcome"] == "mismatch"
        row = await db_order(order["id"])
        assert row.status == "payment_review" and row.review_reason and row.paid_at is None
        assert await reservation_statuses(order["id"]) == ["reserved"]  # not consumed
    assert spy.calls == []
    assert await stock(p.id) == 3


async def test_event_for_another_order_binding_is_a_mismatch(client, customer, other_customer):
    p = await create_product()
    a = await placed_order(client, customer, p)
    a = {**a, **(await intent(client, customer, a["id"])).json(), "id": a["id"]}
    b = await placed_order(client, other_customer, p)
    # PI of order A carrying order B's id in metadata.
    event = pi_event(a, metadata={"order_id": b["id"]})
    r = await post_event(client, event)
    assert r.json()["outcome"] == "mismatch"
    assert (await db_order(a["id"])).status == "payment_review"
    assert (await db_order(b["id"])).status == "pending_payment"
    # Unknown intents are recorded and ignored.
    r = await post_event(client, pi_event({**a, "payment_intent_id": "pi_unknown", "id": "x"}))
    assert r.json()["outcome"] == "ignored"


async def test_intent_access_and_method_rules(client, customer, other_customer):
    p = await create_product()
    order = await placed_order(client, customer, p)
    r = await intent(client, other_customer, order["id"])
    assert r.status_code == 404
    r = await client.post(
        f"{API}/payments/orders/{order['id']}/intent",
        json={"payment_method": "laybuy"},
        headers=customer.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "payment_method_unavailable"
    pi = (await intent(client, customer, order["id"])).json()
    r = await confirm(client, other_customer, pi["payment_intent_id"], "succeed")
    assert r.status_code == 404
    r = await client.post(f"{API}/payments/orders/{order['id']}/intent", json={})
    assert r.status_code == 401


async def test_local_confirm_is_404_outside_local_mode(client, customer, monkeypatch):
    p = await create_product()
    order = await placed_order(client, customer, p)
    pi = (await intent(client, customer, order["id"])).json()
    monkeypatch.setattr(get_settings(), "payment_provider", "stripe")
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(get_settings(), "stripe_webhook_secret", "whsec_x")
    r = await confirm(client, customer, pi["payment_intent_id"], "succeed")
    assert r.status_code == 404
    monkeypatch.setattr(get_settings(), "payment_provider", "local")
    monkeypatch.setattr(get_settings(), "app_env", "production")
    r = await confirm(client, customer, pi["payment_intent_id"], "succeed")
    assert r.status_code == 404
    # ...and the local secret is no longer accepted by the webhook.
    order = {**order, **pi, "id": order["id"]}
    r = await post_event(client, pi_event(order))
    assert r.status_code == 503
    assert (await db_order(order["id"])).status == "pending_payment"
