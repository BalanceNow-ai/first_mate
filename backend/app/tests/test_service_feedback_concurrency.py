"""Concurrency (SJ-21): simultaneous submissions, duplicate submits, sweep versus late submission."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core.errors import AppError
from app.database import async_session
from app.models.service_jobs import FeedbackVersion, JobFeedback, VisitEvent
from app.services.service_jobs import feedback
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_feedback import (
    C2O,
    O2C,
    OWNER_RATINGS,
    TECH_RATINGS,
    draft,
    key,
    open_window,
    outbox,
    window_row,
)


async def _rows(job_id) -> list[JobFeedback]:
    async with async_session() as s:
        return list(
            (
                await s.execute(select(JobFeedback).where(JobFeedback.job_id == job_id).order_by(JobFeedback.direction))
            ).scalars()
        )


def _submit_req(client, actor, job_id, direction, idem=None):
    return client.post(
        f"/api/v1/service-jobs/{job_id}/feedback/{direction}/submit",
        headers={**actor.headers, "Idempotency-Key": idem or key()},
    )


async def test_simultaneous_submissions_from_both_sides_reveal_exactly_once(client, world):  # noqa: F811
    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS, "Owner text")
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS, "Tech text")
    a, b = await asyncio.gather(
        _submit_req(client, world.owner, world.job.id, O2C), _submit_req(client, world.tech, world.job.id, C2O)
    )
    assert (a.status_code, b.status_code) == (201, 201), (a.text, b.text)
    rows = await _rows(world.job.id)
    window = await window_row(world.job.id)
    assert [r.status for r in rows] == ["revealed", "revealed"]
    assert {r.revealed_at for r in rows} == {window.revealed_at}
    # Exactly one of the two submissions saw the other already submitted and revealed both.
    assert sorted([a.json()["window"]["revealed"], b.json()["window"]["revealed"]]) == [False, True]
    revealed = await outbox(kind="feedback_revealed")
    assert sorted(str(r.user_id) for r in revealed) == sorted([str(world.owner.id), str(world.tech.id)])


async def test_concurrent_duplicate_submissions_yield_one(client, world):  # noqa: F811
    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS)
    idem = key()
    results = await asyncio.gather(
        *(_submit_req(client, world.owner, world.job.id, O2C, idem if i % 2 else None) for i in range(4))
    )
    assert sorted(r.status_code for r in results) == [200, 200, 200, 201]
    rows = await _rows(world.job.id)
    assert len(rows) == 1 and rows[0].status == "submitted" and rows[0].version == 1
    async with async_session() as s:
        versions = list(
            (await s.execute(select(FeedbackVersion).where(FeedbackVersion.feedback_id == rows[0].id))).scalars()
        )
    assert len(versions) == 1


async def test_concurrent_attendance_opens_one_window(client, world):  # noqa: F811
    from app.database import utcnow

    body = {"kind": "attended", "occurred_at": utcnow().isoformat()}
    results = await asyncio.gather(
        client.post(
            f"/api/v1/service-jobs/{world.job.id}/visits",
            json=body,
            headers={**world.tech.headers, "Idempotency-Key": key()},
        ),
        client.post(
            f"/api/v1/service-jobs/{world.job.id}/visits",
            json=body,
            headers={**world.owner.headers, "Idempotency-Key": key()},
        ),
    )
    assert [r.status_code for r in results] == [201, 201]
    assert sorted(r.json()["feedback_window_opened"] for r in results) == [False, True]
    async with async_session() as s:
        events = list((await s.execute(select(VisitEvent).where(VisitEvent.job_id == world.job.id))).scalars())
    window = await window_row(world.job.id)
    assert len(events) == 2 and window.eligibility_event_id in {e.id for e in events}


async def _late_submit(job_id, user_id, now):
    async with async_session() as s:
        try:
            _, created = await feedback.submit(s, user_id, job_id, C2O, now=now)
            await s.commit()
            return created
        except AppError as e:
            await s.rollback()
            return e.code


async def _sweep(now):
    async with async_session() as s:
        return await feedback.reveal_due(s, now=now)


async def test_sweep_races_a_late_submission_safely(client, world):  # noqa: F811
    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS)
    await _submit_req(client, world.owner, world.job.id, O2C)
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS)
    window = await window_row(world.job.id)
    just_before = window.closes_at - timedelta(milliseconds=1)
    late, swept = await asyncio.gather(_late_submit(world.job.id, world.tech.id, just_before), _sweep(window.closes_at))
    rows = {r.direction: r for r in await _rows(world.job.id)}
    assert rows[O2C].status == "revealed"
    if late is True:
        # The submission committed first: it is revealed (by itself or by the sweep), exactly once.
        assert rows[C2O].status == "revealed"
        assert rows[C2O].revealed_at == rows[O2C].revealed_at
    else:
        # The sweep won: the late submission was refused and the draft stays private.
        assert late == "feedback_revealed" and rows[C2O].status == "draft"
    assert swept["windows_revealed"] in (0, 1)
    assert (await _sweep(window.closes_at + timedelta(hours=1)))["windows_revealed"] == 0
    # A submission at (or after) closes_at is always refused.
    assert await _late_submit(world.job.id, world.tech.id, window.closes_at) in ("feedback_revealed", False)
    assert len(await outbox(world.owner.id, "feedback_revealed")) == 1
