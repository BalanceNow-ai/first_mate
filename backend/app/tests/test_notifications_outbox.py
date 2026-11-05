"""Notification outbox: idempotency, preferences, providers at the HTTP boundary,
retry/backoff/dead-letter, log sink privacy and the API."""

import asyncio
import json
import logging
import os
import socket
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session, utcnow
from app.models.notifications import NotificationOutbox, NotificationPreference, PushDevice
from app.models.order import Order
from app.services import notification_providers as providers
from app.services import notifications
from app.tasks import notifications as notification_tasks
from app.tests.test_loyalty_support import make_order, paid_order, refund

N = "/api/v1/notifications"


@pytest.fixture(autouse=True)
def _reset_transport():
    yield
    providers.http_transport = None
    providers._fcm_token.clear()


async def _rows(**filters):
    async with async_session() as s:
        q = select(NotificationOutbox).order_by(NotificationOutbox.created_at)
        for k, v in filters.items():
            q = q.where(getattr(NotificationOutbox, k) == v)
        return list((await s.execute(q)).scalars())


async def _dispatch(now=None):
    async with async_session() as s:
        return await notifications.dispatch_pending(s, now=now)


async def test_order_confirmation_queued_once(customer):
    order = await paid_order(customer.id, subtotal_cents=5000)
    async with async_session() as s:  # duplicate event delivery
        await notifications.order_paid(s, await s.get(Order, order.id))
        await s.commit()
    rows = await _rows(template="order_confirmed")
    assert len(rows) == 1 and rows[0].channel == "email" and rows[0].recipient == customer.email
    assert rows[0].status == "pending" and rows[0].payload["order_number"] == order.order_number
    assert rows[0].idempotency_key == f"order_confirmed:{order.id}:email"


async def test_transactional_ignores_opt_out_but_others_respect_it(customer):
    async with async_session() as s:
        s.add(NotificationPreference(user_id=customer.id, email_enabled=False, rewards_updates=False))
        await s.commit()
    order = await paid_order(customer.id, subtotal_cents=5000)  # also earns points
    await refund(order.id, 1000)
    confirmed = await _rows(template="order_confirmed")
    refunded = await _rows(template="order_refunded")
    points = await _rows(template="points_earned")
    assert confirmed[0].status == "pending" and refunded[0].status == "pending"
    assert points[0].status == "suppressed" and points[0].last_error == "suppressed_by_preference"
    counts = await _dispatch()
    assert counts["sent"] == 2 and counts["suppressed"] == 0
    assert {r.status for r in await _rows(template="points_earned")} == {"suppressed"}


async def test_push_only_with_devices_and_toggle(client, customer):
    r = await client.post(
        f"{N}/push-devices", json={"token": "fcm-token-abcdef-1", "platform": "android"}, headers=customer.headers
    )
    assert r.status_code == 201
    async with async_session() as s:
        await notifications.enqueue(
            s,
            template="points_earned",
            category="rewards",
            idempotency_key="k1",
            user_id=customer.id,
            payload={"points": 5, "balance": 5},
        )
        await s.commit()
    assert {r.channel for r in await _rows()} == {"email", "push"}
    r = await client.put(f"{N}/preferences", json={"push_enabled": False}, headers=customer.headers)
    assert r.status_code == 200 and r.json()["push_enabled"] is False and r.json()["email_enabled"] is True
    async with async_session() as s:
        await notifications.enqueue(
            s,
            template="points_earned",
            category="rewards",
            idempotency_key="k2",
            user_id=customer.id,
            payload={"points": 5, "balance": 10},
        )
        await s.commit()
    push2 = [r for r in await _rows() if r.idempotency_key == "k2:push"]
    assert push2[0].status == "suppressed"
    counts = await _dispatch()
    assert counts["sent"] == 3  # 2 emails + 1 push (log sinks)


async def test_log_sink_logs_no_pii(customer, caplog, monkeypatch):
    # Alembic's fileConfig (session fixture) disables pre-existing loggers; re-enable.
    for name in ("app.services.notification_providers", "app.services.notifications"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)
    await paid_order(customer.id, subtotal_cents=5000)
    with caplog.at_level(logging.DEBUG):
        counts = await _dispatch()
    assert counts["sent"] >= 1
    text = caplog.text
    assert "order_confirmed" in text
    assert customer.email not in text and "Casey" not in text and "HM-" not in text
    rows = await _rows(template="order_confirmed")
    assert rows[0].status == "sent" and rows[0].provider == "log_sink" and str(rows[0].id) in text


async def test_resend_success_at_http_boundary(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "resend")
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test_fake")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"id": "email_123"})

    providers.http_transport = httpx.MockTransport(handler)
    order = await paid_order(customer.id, subtotal_cents=5000)
    await _dispatch()
    row = (await _rows(template="order_confirmed"))[0]
    assert row.status == "sent" and row.provider == "resend" and row.provider_message_id == "email_123"
    req = next(r for r in seen if json.loads(r.content)["subject"].startswith("Order"))
    body = json.loads(req.content)
    assert req.url.path == "/emails" and req.headers["authorization"] == "Bearer re_test_fake"
    assert req.headers["idempotency-key"] == f"helm-outbox-{row.id}"
    assert body["to"] == [customer.email] and order.order_number in body["text"] and "<p>" in body["html"]


async def test_resend_without_key_is_suppressed(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "resend")
    monkeypatch.setattr(get_settings(), "resend_api_key", "")
    await paid_order(customer.id, subtotal_cents=5000)
    await _dispatch()
    row = (await _rows(template="order_confirmed"))[0]
    assert row.status == "suppressed" and row.last_error == "resend_not_configured"


async def test_retry_backoff_and_dead_letter(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "resend")
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test_fake")
    monkeypatch.setattr(get_settings(), "notification_max_attempts", 3)
    calls = []

    def failing(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(503, json={"message": f"down for {customer.email}"})

    providers.http_transport = httpx.MockTransport(failing)
    async with async_session() as s:
        await notifications.enqueue(
            s,
            template="order_confirmed",
            category="order",
            idempotency_key="retry",
            user_id=customer.id,
            transactional=True,
            payload={"order_number": "HM-1", "total_cents": 100},
        )
        await s.commit()
    t0 = utcnow()
    await _dispatch(now=t0)
    row = (await _rows())[0]
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "resend_http_503")
    assert customer.email not in row.last_error
    assert abs((row.next_attempt_at - t0).total_seconds() - 60) < 1
    assert (await _dispatch(now=t0 + timedelta(seconds=30)))["claimed"] == 0  # not yet due
    await _dispatch(now=t0 + timedelta(seconds=61))
    row = (await _rows())[0]
    assert row.attempts == 2 and abs((row.next_attempt_at - (t0 + timedelta(seconds=61))).total_seconds() - 120) < 1
    await _dispatch(now=t0 + timedelta(hours=1))
    row = (await _rows())[0]
    assert (row.status, row.attempts, row.next_attempt_at) == ("dead", 3, None)
    assert (await _dispatch(now=t0 + timedelta(days=1)))["claimed"] == 0
    assert len(calls) == 3


async def test_permanent_error_dead_immediately(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "resend")
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test_fake")
    providers.http_transport = httpx.MockTransport(lambda req: httpx.Response(422, json={"message": "bad"}))
    await paid_order(customer.id, subtotal_cents=5000)
    await _dispatch()
    row = (await _rows(template="order_confirmed"))[0]
    assert row.status == "dead" and row.attempts == 1 and row.last_error == "resend_http_422"


async def test_expired_sending_lease_is_reclaimed(customer):
    async with async_session() as s:
        await notifications.enqueue(
            s,
            template="points_earned",
            category="rewards",
            idempotency_key="lease",
            user_id=customer.id,
            payload={"points": 1, "balance": 1},
        )
        await s.commit()
    now = utcnow()
    async with async_session() as s:
        row = (await s.execute(select(NotificationOutbox))).scalar_one()
        row.status, row.attempts, row.next_attempt_at = "sending", 1, now + timedelta(minutes=5)
        await s.commit()
    assert (await _dispatch(now=now))["claimed"] == 0  # another worker holds the lease
    counts = await _dispatch(now=now + timedelta(minutes=6))  # lease expired (worker crashed)
    assert counts["sent"] == 1 and (await _rows())[0].attempts == 2


async def test_concurrent_dispatchers_send_each_row_once(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "resend")
    monkeypatch.setattr(get_settings(), "resend_api_key", "re_test_fake")
    sent = []

    async def handler(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        sent.append(json.loads(req.content)["subject"])
        return httpx.Response(200, json={"id": uuid.uuid4().hex})

    providers.http_transport = httpx.MockTransport(handler)
    async with async_session() as s:
        for i in range(12):
            await notifications.enqueue(
                s,
                template="points_earned",
                category="rewards",
                idempotency_key=f"c{i}",
                user_id=customer.id,
                payload={"points": i + 1, "balance": i + 1},
                channels=("email",),
            )
        await s.commit()
    results = await asyncio.gather(*(_dispatch() for _ in range(4)))
    assert sum(r["sent"] for r in results) == 12 and len(sent) == 12 and len(set(sent)) == 12


async def test_fcm_without_configuration_suppressed(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "push_provider", "fcm")
    monkeypatch.setattr(get_settings(), "firebase_project_id", "")
    async with async_session() as s:
        s.add(PushDevice(user_id=customer.id, token="tok-1234567890", platform="ios"))
        await s.commit()
        await notifications.enqueue(
            s,
            template="points_earned",
            category="rewards",
            idempotency_key="fcm",
            user_id=customer.id,
            payload={"points": 1, "balance": 1},
            channels=("push",),
        )
        await s.commit()
    await _dispatch()
    row = (await _rows())[0]
    assert row.status == "suppressed" and row.last_error == "fcm_not_configured"


async def test_fcm_http_v1_with_fake_service_account(customer, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    account = {
        "client_email": "svc@helm-test.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.test/token",
    }
    monkeypatch.setattr(get_settings(), "push_provider", "fcm")
    monkeypatch.setattr(get_settings(), "firebase_project_id", "helm-test")
    monkeypatch.setattr(get_settings(), "firebase_service_account_json", json.dumps(account))
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.host == "oauth2.test":
            return httpx.Response(200, json={"access_token": "ya29.fake", "expires_in": 3600})
        token = json.loads(req.content)["message"]["token"]
        if token == "tok-dead-0000000":
            return httpx.Response(
                404, json={"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}
            )
        return httpx.Response(200, json={"name": "projects/helm-test/messages/1"})

    providers.http_transport = httpx.MockTransport(handler)
    async with async_session() as s:
        s.add_all(
            [
                PushDevice(user_id=customer.id, token="tok-live-0000000", platform="android"),
                PushDevice(user_id=customer.id, token="tok-dead-0000000", platform="ios"),
            ]
        )
        await s.commit()
        await notifications.enqueue(
            s,
            template="points_earned",
            category="rewards",
            idempotency_key="fcm2",
            user_id=customer.id,
            payload={"points": 3, "balance": 3},
            channels=("push",),
        )
        await s.commit()
    await _dispatch()
    row = (await _rows())[0]
    assert row.status == "sent" and row.provider == "fcm"
    sends = [r for r in seen if r.url.host == "fcm.googleapis.com"]
    assert sends[0].url.path == "/v1/projects/helm-test/messages:send"
    assert sends[0].headers["authorization"] == "Bearer ya29.fake"
    async with async_session() as s:
        tokens = list((await s.execute(select(PushDevice.token))).scalars())
    assert tokens == ["tok-live-0000000"]  # unregistered token pruned


async def test_disabled_email_provider_suppresses(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "disabled")
    await paid_order(customer.id, subtotal_cents=5000)
    await _dispatch()
    assert {r.status for r in await _rows(channel="email")} == {"suppressed"}


async def test_celery_task_dispatches(customer):
    await make_order(customer.id)
    await paid_order(customer.id, subtotal_cents=5000)
    result = await asyncio.to_thread(notification_tasks.dispatch_pending.run)
    assert result["sent"] >= 1
    assert all(r.status == "sent" for r in await _rows(channel="email"))


async def test_api_preferences_devices_and_history(client, customer, other_customer):
    prefs = (await client.get(f"{N}/preferences", headers=customer.headers)).json()
    assert prefs["email_enabled"] is True and prefs["marketing"] is False and "transactional_note" in prefs
    r = await client.put(f"{N}/preferences", json={"delivery_updates": False, "bogus": True}, headers=customer.headers)
    assert r.status_code == 422
    r = await client.put(f"{N}/preferences", json={"delivery_updates": False}, headers=customer.headers)
    assert r.json()["delivery_updates"] is False and r.json()["order_updates"] is True
    r = await client.put(f"{N}/preferences", json={"rewards_updates": False}, headers=customer.headers)
    assert r.json()["delivery_updates"] is False and r.json()["rewards_updates"] is False
    tok = "fcm-token-shared-device"
    assert (
        await client.post(f"{N}/push-devices", json={"token": tok, "platform": "ios"}, headers=customer.headers)
    ).status_code == 201
    # The same physical device signs in as another account: the token moves.
    assert (
        await client.post(f"{N}/push-devices", json={"token": tok, "platform": "ios"}, headers=other_customer.headers)
    ).status_code == 201
    assert (await client.delete(f"{N}/push-devices/{tok}", headers=customer.headers)).status_code == 404
    assert (await client.delete(f"{N}/push-devices/{tok}", headers=other_customer.headers)).status_code == 204
    await paid_order(customer.id, subtotal_cents=5000)
    history = (await client.get(N, headers=customer.headers)).json()
    assert {h["template"] for h in history} == {"order_confirmed", "points_earned"}
    assert all("recipient" not in h and "payload" not in h for h in history)
    assert (await client.get(N, headers=other_customer.headers)).json() == []


def _mailpit_up() -> bool:
    try:
        with socket.create_connection(("localhost", 11025), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _mailpit_up(), reason="Mailpit SMTP sink not running on localhost:11025")
async def test_smtp_sink_integration(customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "email_provider", "smtp_sink")
    monkeypatch.setattr(get_settings(), "smtp_sink_host", "localhost")
    monkeypatch.setattr(get_settings(), "smtp_sink_port", 11025)
    order = await paid_order(customer.id, subtotal_cents=5000)
    await _dispatch()
    row = (await _rows(template="order_confirmed"))[0]
    assert row.status == "sent" and row.provider == "smtp_sink"
    api = os.environ.get("MAILPIT_API", "http://localhost:18026")
    async with httpx.AsyncClient(timeout=5, trust_env=False) as c:
        msgs = (
            await c.get(f"{api}/api/v1/search", params={"query": f'subject:"Order {order.order_number} confirmed"'})
        ).json()
    assert msgs["messages_count"] >= 1
