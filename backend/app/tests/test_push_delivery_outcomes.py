"""FM-04: per-device push outcomes and outbox lease fencing.

The real FCM adapter is driven through an HTTP-boundary fake. A transient failure on
one device must be retried — for that device only — and a device that already received
the message must never receive it twice. A worker whose lease expired must not
overwrite a row another worker reclaimed.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session, utcnow
from app.models.notifications import NotificationOutbox, PushDevice
from app.services import notification_providers as providers
from app.services import notifications

GOOD, FLAKY, DEAD, BAD = "tok-good-000000", "tok-flaky-00000", "tok-dead-000000", "tok-bad-0000000"


@pytest.fixture
def fcm(monkeypatch):
    """Configure FCM with a throwaway service account; returns (behaviour, sends)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    account = {
        "client_email": "svc@helm-test.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.test/token",
    }
    settings = get_settings()
    monkeypatch.setattr(settings, "push_provider", "fcm")
    monkeypatch.setattr(settings, "firebase_project_id", "helm-test")
    monkeypatch.setattr(settings, "firebase_service_account_json", json.dumps(account))
    behaviour: dict[str, list] = {}  # token -> queued responses (last one repeats)
    sends: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "oauth2.test":
            return httpx.Response(200, json={"access_token": "ya29.fake", "expires_in": 3600})
        token = json.loads(req.content)["message"]["token"]
        sends.append(token)
        queue = behaviour.get(token) or [200]
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if outcome == "timeout":
            raise httpx.ReadTimeout("slow", request=req)
        if outcome == "unregistered":
            return httpx.Response(
                404, json={"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}
            )
        if outcome == 200:
            return httpx.Response(200, json={"name": f"projects/helm-test/messages/{token}-{len(sends)}"})
        return httpx.Response(outcome, json={"error": {"status": "ERR"}})

    providers.http_transport = httpx.MockTransport(handler)
    yield behaviour, sends
    providers.http_transport = None
    providers._fcm_token.clear()


async def _push(user_id, *tokens: str) -> None:
    async with async_session() as s:
        s.add_all([PushDevice(user_id=user_id, token=t, platform="android") for t in tokens])
        await s.commit()
        await notifications.enqueue(
            s,
            template="points_earned",
            category="rewards",
            idempotency_key="push-outcomes",
            user_id=user_id,
            payload={"points": 3, "balance": 3},
            channels=("push",),
        )
        await s.commit()


async def _row() -> NotificationOutbox:
    async with async_session() as s:
        return (await s.execute(select(NotificationOutbox))).scalar_one()


async def _dispatch(now=None) -> dict:
    async with async_session() as s:
        return await notifications.dispatch_pending(s, now=now)


async def _retry() -> dict:
    """Run the dispatcher once the backoff for the row has elapsed."""
    row = await _row()
    return await _dispatch(now=row.next_attempt_at + timedelta(seconds=1))


@pytest.mark.parametrize("failure", [500, 429, "timeout"])
async def test_partial_success_retries_only_the_failed_device(customer, fcm, failure):
    behaviour, sends = fcm
    behaviour[FLAKY] = [failure, 200]  # fails once, then recovers
    await _push(customer.id, GOOD, FLAKY)

    await _dispatch()
    row = await _row()
    assert row.status == "failed" and row.attempts == 1, (row.status, row.last_error)
    assert sorted(sends) == [FLAKY, GOOD]

    await _retry()
    row = await _row()
    assert row.status == "sent" and row.attempts == 2
    assert sends.count(GOOD) == 1, "the device that already received it is not sent again"
    assert sends.count(FLAKY) == 2
    assert {v["status"] for v in row.push_targets.values()} == {"sent"}
    assert row.provider_message_id.count("messages/") == 2


async def test_invalid_and_permanent_failures_are_final_not_retried(customer, fcm):
    behaviour, sends = fcm
    behaviour[DEAD] = ["unregistered"]
    behaviour[BAD] = [403]  # permanent (e.g. sender mismatch)
    await _push(customer.id, GOOD, DEAD, BAD)
    await _dispatch()
    row = await _row()
    assert row.status == "sent"
    statuses = sorted(v["status"] for v in row.push_targets.values())
    assert statuses == ["failed_permanent", "invalid", "sent"]
    async with async_session() as s:
        assert set((await s.execute(select(PushDevice.token))).scalars()) == {GOOD, BAD}  # unregistered pruned


async def test_all_devices_failing_transiently_then_recovering(customer, fcm, monkeypatch):
    behaviour, sends = fcm
    behaviour[GOOD] = [503, 503, 200]
    behaviour[FLAKY] = [503, 200]
    await _push(customer.id, GOOD, FLAKY)
    for _ in range(3):
        if (await _row()).status == "sent":
            break
        await (_retry() if (await _row()).attempts else _dispatch())
    row = await _row()
    assert row.status == "sent" and row.attempts == 3
    assert sends.count(FLAKY) == 2 and sends.count(GOOD) == 3


async def test_transient_failures_until_dead_keep_delivered_record(customer, fcm, monkeypatch):
    monkeypatch.setattr(get_settings(), "notification_max_attempts", 2)
    behaviour, sends = fcm
    behaviour[FLAKY] = [500]
    await _push(customer.id, GOOD, FLAKY)
    await _dispatch()
    await _retry()
    row = await _row()
    assert row.status == "dead" and row.attempts == 2
    assert sends.count(GOOD) == 1
    assert sorted(v["status"] for v in row.push_targets.values()) == ["retry", "sent"]


async def test_expired_lease_cannot_overwrite_a_reclaimed_row(customer, fcm, monkeypatch):
    """A slow worker outlives its lease; another worker reclaims and finishes the row.
    The slow worker's completion write is fenced off. (A provider call already in flight
    cannot be recalled — FCM has no idempotency key — so push is at-least-once for a
    call that outlives its lease; the per-device record prevents any *retry* duplicate.)"""
    monkeypatch.setattr(get_settings(), "notification_claim_lease_seconds", 1)
    behaviour, sends = fcm
    await _push(customer.id, GOOD)

    release = asyncio.Event()
    original = notifications._deliver

    async def slow_deliver(db, row):
        await release.wait()
        return await original(db, row)

    monkeypatch.setattr(notifications, "_deliver", slow_deliver)
    slow = asyncio.create_task(_dispatch())
    await asyncio.sleep(0.2)
    while (await _row()).status != "sending":
        await asyncio.sleep(0.05)
    await asyncio.sleep(1.2)  # the slow worker's lease (1 s) has now expired

    monkeypatch.setattr(notifications, "_deliver", original)
    fast = await _dispatch(now=utcnow())
    assert fast["sent"] == 1
    release.set()
    slow_counts = await slow
    assert slow_counts["lease_lost"] == 1 and slow_counts["sent"] == 0
    row = await _row()
    assert row.status == "sent" and row.lease_token is None and row.attempts == 2


async def test_lost_lease_fences_every_later_row_of_the_batch(customer, other_customer, fcm, monkeypatch):
    """Second review: after the first lost lease, later rows of the stale batch must not be
    treated as owned because the row now carries the reclaiming worker's token."""
    monkeypatch.setattr(get_settings(), "notification_claim_lease_seconds", 1)
    behaviour, sends = fcm
    async with async_session() as s:
        s.add_all(
            [
                PushDevice(user_id=customer.id, token=GOOD, platform="android"),
                PushDevice(user_id=other_customer.id, token=FLAKY, platform="android"),
            ]
        )
        await s.commit()
        for user, key in ((customer.id, "row-a"), (other_customer.id, "row-b")):
            await notifications.enqueue(
                s,
                template="points_earned",
                category="rewards",
                idempotency_key=key,
                user_id=user,
                payload={"points": 1, "balance": 1},
                channels=("push",),
            )
            await s.commit()

    original = notifications._deliver
    w1_release, w2_release = asyncio.Event(), asyncio.Event()
    w1_stalled, w2_stalled = [], []
    phase = {"worker": 1}

    async def gated(db, row):
        if phase["worker"] == 1 and not w1_stalled:
            w1_stalled.append(row.id)  # worker 1 stalls on row A
            await w1_release.wait()
        elif phase["worker"] == 2 and row.id != w1_stalled[0] and not w2_stalled:
            w2_stalled.append(row.id)  # worker 2 is mid-delivery on row B
            await w2_release.wait()
        return await original(db, row)

    monkeypatch.setattr(notifications, "_deliver", gated)
    slow = asyncio.create_task(_dispatch())
    while not w1_stalled:
        await asyncio.sleep(0.05)
    await asyncio.sleep(1.2)  # worker 1's lease on the whole batch has expired
    phase["worker"] = 2
    fast = asyncio.create_task(_dispatch(now=utcnow()))
    while not w2_stalled:
        await asyncio.sleep(0.05)
    phase["worker"] = 0
    w1_release.set()
    slow_counts = await slow  # worker 1 resumes while worker 2 owns row B
    w2_release.set()
    fast_counts = await fast
    assert slow_counts["lease_lost"] == 2 and slow_counts["sent"] == 0, slow_counts
    assert fast_counts["sent"] == 2, fast_counts
    assert sends.count(FLAKY) == 1  # row B was sent once, by the worker that owns it
    async with async_session() as s:
        rows = (await s.execute(select(NotificationOutbox))).scalars().all()
    assert {r.status for r in rows} == {"sent"} and all(r.lease_token is None for r in rows)
