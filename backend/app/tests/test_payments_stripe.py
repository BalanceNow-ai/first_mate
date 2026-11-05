"""Stripe provider path. The SDK is faked at its boundary; Stripe is never called.

Webhook signatures are produced in Stripe's format and verified by the real
``stripe.Webhook.construct_event``.
"""

import uuid

import pytest
import stripe

from app.config import get_settings
from app.database import async_session
from app.services.reservations import release_expired
from app.tests.conftest import create_product
from app.tests.test_commerce_support import (
    API,
    EventSpy,
    add,
    checkout,
    db_order,
    expire_order,
    intent,
    pi_event,
    placed_order,
    post_event,
    refund_event,
    stock,
)

WHSEC = "whsec_test_fake_stripe_secret"


class FakeStripe:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.intents: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.fail_next: Exception | None = None

    def _maybe_fail(self):
        if self.fail_next is not None:
            exc, self.fail_next = self.fail_next, None
            raise exc

    def create(self, **kw):
        self.calls.append(("create", kw))
        self._maybe_fail()
        key = kw["idempotency_key"]
        if key in self.by_key:
            return self.intents[self.by_key[key]]
        pi_id = f"pi_fake_{uuid.uuid4().hex[:16]}"
        self.intents[pi_id] = {
            "id": pi_id,
            "object": "payment_intent",
            "amount": kw["amount"],
            "currency": kw["currency"],
            "client_secret": f"{pi_id}_secret_abc",
            "status": "requires_payment_method",
            "metadata": kw["metadata"],
        }
        self.by_key[key] = pi_id
        return self.intents[pi_id]

    def retrieve(self, pi_id, **kw):
        self.calls.append(("retrieve", {"id": pi_id, **kw}))
        self._maybe_fail()
        return self.intents[pi_id]

    def cancel(self, pi_id, **kw):
        self.calls.append(("cancel", {"id": pi_id, **kw}))
        self._maybe_fail()
        pi = self.intents[pi_id]
        if pi["status"] in ("succeeded", "processing"):
            raise stripe.InvalidRequestError("cannot cancel", param=None)
        pi["status"] = "canceled"
        return pi

    def refund(self, **kw):
        self.calls.append(("refund", kw))
        self._maybe_fail()
        return {"id": f"re_fake_{uuid.uuid4().hex[:8]}", "object": "refund", "status": "pending"}

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake_stripe(monkeypatch) -> FakeStripe:
    fake = FakeStripe()
    s = get_settings()
    monkeypatch.setattr(s, "payment_provider", "stripe")
    monkeypatch.setattr(s, "stripe_secret_key", "sk_test_fake")
    monkeypatch.setattr(s, "stripe_publishable_key", "pk_test_fake")
    monkeypatch.setattr(s, "stripe_webhook_secret", WHSEC)
    monkeypatch.setattr(stripe.PaymentIntent, "create", fake.create)
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", fake.retrieve)
    monkeypatch.setattr(stripe.PaymentIntent, "cancel", fake.cancel)
    monkeypatch.setattr(stripe.Refund, "create", fake.refund)
    return fake


async def _order_with_intent(client, actor, product, qty=1):
    order = await placed_order(client, actor, product, qty)
    pi = (await intent(client, actor, order["id"])).json()
    return {**order, **pi, "id": order["id"]}


async def test_stripe_intent_amount_currency_idempotency_and_reuse(client, customer, fake_stripe):
    p = await create_product(price_cents=6000, sale_price_cents=5500)
    await add(client, customer, p, 2)
    order = (await checkout(client, customer)).json()
    assert order["payment_provider"] == "stripe" and order["total_cents"] == 11000
    r = await intent(client, customer, order["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "stripe" and body["test_mode"] is False
    assert body["publishable_key"] == "pk_test_fake" and body["amount_cents"] == 11000
    assert body["client_secret"].startswith(body["payment_intent_id"])
    name, kw = fake_stripe.calls[0]
    assert name == "create"
    assert kw["amount"] == 11000 and kw["currency"] == "nzd" and kw["payment_method_types"] == ["card"]
    assert kw["idempotency_key"] == f"order:{order['id']}:pi" and kw["api_key"] == "sk_test_fake"
    assert kw["metadata"] == {
        "order_id": order["id"],
        "user_id": str(customer.id),
        "order_number": order["order_number"],
    }

    again = (await intent(client, customer, order["id"])).json()
    assert again["payment_intent_id"] == body["payment_intent_id"]
    assert fake_stripe.names() == ["create", "retrieve"]


async def test_stripe_webhook_marks_paid_and_rejects_other_secrets(client, customer, fake_stripe, monkeypatch):
    spy = EventSpy(monkeypatch)
    p = await create_product(stock_quantity=2)
    order = await _order_with_intent(client, customer, p)
    event = pi_event(order)
    r = await post_event(client, event)  # signed with the local secret: refused in stripe mode
    assert r.status_code == 400
    r = await post_event(client, event, secret=WHSEC)
    assert r.status_code == 200 and r.json()["outcome"] == "applied"
    assert (await db_order(order["id"])).status == "paid"
    assert len(spy.calls) == 1
    # The local test endpoint does not exist in stripe mode.
    r = await client.post(
        f"{API}/payments/local/{order['payment_intent_id']}/confirm",
        json={"outcome": "succeed"},
        headers=customer.headers,
    )
    assert r.status_code == 404
    # Paid: no new intent.
    fake_stripe.intents[order["payment_intent_id"]]["status"] = "succeeded"
    r = await intent(client, customer, order["id"])
    assert r.status_code == 409


async def test_stripe_cancel_cancels_intent_first(client, customer, fake_stripe):
    p = await create_product(stock_quantity=2)
    order = await _order_with_intent(client, customer, p)
    r = await client.post(f"{API}/orders/{order['id']}/cancel", headers=customer.headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    name, kw = fake_stripe.calls[-1]
    assert name == "cancel" and kw["id"] == order["payment_intent_id"]
    assert kw["idempotency_key"] == f"order:{order['id']}:cancel"
    assert await stock(p.id) == 2
    # Stripe's own canceled event afterwards is stale.
    r = await post_event(client, pi_event(order, "payment_intent.canceled"), secret=WHSEC)
    assert r.json()["outcome"] == "stale"


async def test_stripe_cancel_when_payment_already_succeeded(client, customer, fake_stripe):
    p = await create_product(stock_quantity=1)
    order = await _order_with_intent(client, customer, p)
    fake_stripe.intents[order["payment_intent_id"]]["status"] = "succeeded"
    r = await client.post(f"{API}/orders/{order['id']}/cancel", headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "payment_already_succeeded"
    assert (await db_order(order["id"])).status == "pending_payment"
    assert await stock(p.id) == 0
    r = await post_event(client, pi_event(order), secret=WHSEC)
    assert r.json()["outcome"] == "applied"
    assert (await db_order(order["id"])).status == "paid"


async def test_stripe_expiry_cancels_and_survives_provider_errors(client, customer, fake_stripe):
    p = await create_product(stock_quantity=2)
    a = await _order_with_intent(client, customer, p)
    await add(client, customer, p)
    b_order = (await checkout(client, customer)).json()
    b = {**b_order, **(await intent(client, customer, b_order["id"])).json(), "id": b_order["id"]}
    await expire_order(a["id"], minutes=2)
    await expire_order(b["id"], minutes=1)
    fake_stripe.fail_next = stripe.APIConnectionError("network down")  # first cancel (order a) fails
    async with async_session() as s:
        assert await release_expired(s) == 1
        await s.commit()
    assert (await db_order(a["id"])).status == "pending_payment"
    assert (await db_order(b["id"])).status == "expired"
    async with async_session() as s:
        assert await release_expired(s) == 1
        await s.commit()
    assert (await db_order(a["id"])).status == "expired"
    assert await stock(p.id) == 2


async def test_stripe_refund_waits_for_webhook(client, customer, admin, fake_stripe):
    p = await create_product(stock_quantity=3, price_cents=5000)
    order = await _order_with_intent(client, customer, p)
    await post_event(client, pi_event(order), secret=WHSEC)
    refund_key = f"refund-{uuid.uuid4().hex}"
    r = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 2000, "reason": "goodwill"},
        headers={**admin.headers, "Idempotency-Key": refund_key},
    )
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending" and r.json()["refunded_cents"] == 0
    name, kw = fake_stripe.calls[-1]
    assert name == "refund" and kw["payment_intent"] == order["payment_intent_id"] and kw["amount"] == 2000
    assert kw["idempotency_key"] == f"order:{order['id']}:refund:{refund_key}"
    calls = len(fake_stripe.calls)
    # Repeating the same request never refunds twice ...
    again = await client.post(
        f"{API}/orders/{order['id']}/refund",
        json={"amount_cents": 2000, "reason": "goodwill"},
        headers={**admin.headers, "Idempotency-Key": refund_key},
    )
    assert again.status_code == 202 and again.json()["status"] == "duplicate_request"
    assert len(fake_stripe.calls) == calls
    # ... and a refund without a key is refused.
    nokey = await client.post(
        f"{API}/orders/{order['id']}/refund", json={"amount_cents": 100, "reason": "no key"}, headers=admin.headers
    )
    assert nokey.status_code == 400
    assert (await db_order(order["id"])).refunded_cents == 0
    r = await post_event(client, refund_event(order, 2000), secret=WHSEC)
    assert r.json()["outcome"] == "applied"
    row = await db_order(order["id"])
    assert row.refunded_cents == 2000 and row.payment_status == "partially_refunded"


async def test_stripe_errors_are_not_leaked(client, customer, fake_stripe):
    p = await create_product()
    order = await placed_order(client, customer, p)
    fake_stripe.fail_next = stripe.APIConnectionError("secret internal detail sk_live_123")
    r = await intent(client, customer, order["id"])
    assert r.status_code == 502 and r.json()["code"] == "payment_provider_error"
    assert "sk_live" not in r.text and "internal" not in r.text
    # Retry recovers through the same idempotency key.
    r = await intent(client, customer, order["id"])
    assert r.status_code == 200


async def test_stripe_intent_with_wrong_amount_is_refused(client, customer, fake_stripe):
    p = await create_product()
    order = await _order_with_intent(client, customer, p)
    fake_stripe.intents[order["payment_intent_id"]]["amount"] = 1
    r = await intent(client, customer, order["id"])
    assert r.status_code == 409 and r.json()["code"] == "payment_intent_mismatch"


async def test_stripe_without_keys_is_unavailable(client, customer, fake_stripe, monkeypatch):
    p = await create_product()
    await add(client, customer, p)
    monkeypatch.setattr(get_settings(), "stripe_secret_key", "")
    r = await checkout(client, customer)
    assert r.status_code == 503 and r.json()["code"] == "payments_unavailable"
    # Events signed with the webhook secret are still verified (and this one is malformed).
    r = await post_event(client, {"id": "evt_x"}, secret=WHSEC)
    assert r.status_code == 400 and r.json()["code"] == "invalid_event"
