"""Visit events: scheduled / attended / completed / cancelled, and contested completion (spec §9.1, §10).

* Recorded by a participant — the job owner, or an assigned member of the job's live
  **accepted** assignment — with an ``Idempotency-Key`` (a replay returns the first event).
* The job status follows the event (scheduled, attended, completed, cancelled) and its
  version is bumped; ``expected_version`` guards against a stale view (409).
* The first ``attended`` or ``completed`` event opens the job's single feedback window,
  timed from the server's recording time. Cancelling before any attendance opens nothing
  (no service rating); cancelling after attendance narrows the window's basis to
  ``attended_then_cancelled``.
* The *other* participant may contest an attendance/completion. That records a
  ``completion_contested`` event, opens a moderation case and flags the job as disputed —
  it never rewrites or deletes the contested fact.

The job row lock is taken first, then the feedback window (D22 extension).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import ModerationAction, ModerationCase, ServiceJob, VisitEvent
from app.models.user import User
from app.services import audit
from app.services.service_jobs import access, feedback
from app.services.service_jobs.notify import notify

RECORDABLE = ("scheduled", "attended", "completed", "cancelled")
CONTESTABLE = ("attended", "completed")
PRE_ATTENDANCE = ("draft", "evidence_collection", "contractor_review", "preparation_ready", "scheduled")
ALLOWED_FROM: dict[str, tuple[str, ...]] = {
    "scheduled": (*PRE_ATTENDANCE, "attended"),
    "attended": (*PRE_ATTENDANCE, "attended"),
    "completed": (*PRE_ATTENDANCE, "attended"),
    "cancelled": (*PRE_ATTENDANCE, "attended"),
}
CLOCK_SKEW = timedelta(minutes=10)


def _new_status(kind: str, current: str) -> str:
    if kind == "scheduled":
        return "scheduled" if current in PRE_ATTENDANCE else current
    return kind


async def _by_key(db: AsyncSession, job_id: uuid.UUID, actor_id: uuid.UUID, key: str) -> VisitEvent | None:
    return (
        await db.execute(
            select(VisitEvent).where(
                VisitEvent.job_id == job_id, VisitEvent.actor_id == actor_id, VisitEvent.idempotency_key == key
            )
        )
    ).scalar_one_or_none()


async def _contests_of(db: AsyncSession, job_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(VisitEvent.contests_event_id).where(
            VisitEvent.job_id == job_id, VisitEvent.kind == "completion_contested"
        )
    )
    return {r[0] for r in rows if r[0] is not None}


async def event_view(db: AsyncSession, ev: VisitEvent, contested: set[uuid.UUID] | None = None) -> dict[str, Any]:
    if contested is None:
        contested = await _contests_of(db, ev.job_id)
    name = (
        (await db.execute(select(User.full_name).where(User.id == ev.actor_id))).scalar_one_or_none()
        if ev.actor_id
        else None
    )
    return {
        "id": ev.id,
        "job_id": ev.job_id,
        "assignment_id": ev.assignment_id,
        "kind": ev.kind,
        "actor_id": ev.actor_id,
        "actor_name": name,
        "actor_role": ev.actor_role,
        "occurred_at": ev.occurred_at,
        "recorded_at": ev.recorded_at,
        "note": ev.note,
        "contests_event_id": ev.contests_event_id,
        "contested": ev.id in contested,
    }


async def _result(db: AsyncSession, job: ServiceJob, ev: VisitEvent, opened: bool, created: bool) -> dict[str, Any]:
    return {
        "event": await event_view(db, ev),
        "job_status": job.status,
        "job_version": job.version,
        "job_disputed": job.disputed,
        "feedback_window_opened": opened,
        "created": created,
    }


async def record(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    kind: str,
    occurred_at: datetime,
    note: str | None,
    expected_version: int | None,
    idempotency_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utcnow()
    if kind not in RECORDABLE:
        raise AppError(422, "invalid_visit_kind", "Visits are recorded as scheduled, attended, completed or cancelled")
    actor = await access.job_for(db, user_id, job_id, lock=True)
    job = actor.job
    replay = await _by_key(db, job.id, user_id, idempotency_key)
    if replay is not None:
        if replay.kind != kind:
            raise AppError(409, "idempotency_key_reused", "This Idempotency-Key was already used for another visit")
        return await _result(db, job, replay, False, False)
    access.check_version(job.version, expected_version)
    if job.status not in ALLOWED_FROM[kind]:
        raise AppError(
            409,
            "invalid_visit_transition",
            f"A visit cannot be recorded as {kind} while the job is {job.status}",
            extra={"job_status": job.status},
        )
    if kind != "scheduled" and occurred_at > now + CLOCK_SKEW:
        raise AppError(422, "occurred_in_future", "Attendance, completion and cancellation cannot be in the future")
    if actor.is_owner:
        live = await access.live_assignment(db, job.id)
        assignment = live if live is not None and live.status == "accepted" else None
    else:
        assignment = actor.assignment
    if assignment is None and kind != "cancelled":
        raise AppError(
            409, "no_accepted_assignment", "A visit can be recorded only once a contractor has accepted the job"
        )
    ev = VisitEvent(
        job_id=job.id,
        assignment_id=assignment.id if assignment else None,
        kind=kind,
        actor_id=user_id,
        actor_role="owner" if actor.is_owner else "contractor",
        occurred_at=occurred_at,
        note=note,
        idempotency_key=idempotency_key,
        recorded_at=now,
    )
    db.add(ev)
    await db.flush()
    status = _new_status(kind, job.status)
    if status != job.status:
        job.status = status
        job.version += 1
        job.updated_at = now
    window = await feedback.window_for(db, job.id, lock=True)
    opened = False
    if kind in CONTESTABLE and window is None:
        await feedback.open_window(db, job, ev, assignment.organization_id, now)
        opened = True
    elif window is not None and kind == "completed" and window.basis == "attended":
        window.basis = "completed"
    elif window is not None and kind == "cancelled" and window.basis == "attended":
        window.basis = "attended_then_cancelled"
    await db.flush()
    await _notify_other_side(db, job, actor.is_owner, assignment, ev)
    return await _result(db, job, ev, opened, True)


async def _notify_other_side(db: AsyncSession, job: ServiceJob, by_owner: bool, assignment, ev: VisitEvent) -> None:
    if by_owner:
        recipients = (
            await feedback.contractor_recipients(db, assignment.id, assignment.organization_id) if assignment else []
        )
    else:
        recipients = [job.owner_id]
    for uid in recipients:
        await notify(db, uid, "visit_recorded", job_id=job.id, key=f"{ev.id}:{uid}")


async def list_events(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID) -> list[dict[str, Any]]:
    party = await feedback.party_for(db, user_id, job_id)
    rows = list(
        (
            await db.execute(
                select(VisitEvent)
                .where(VisitEvent.job_id == party.job.id)
                .order_by(VisitEvent.occurred_at, VisitEvent.recorded_at, VisitEvent.id)
            )
        ).scalars()
    )
    contested = await _contests_of(db, party.job.id)
    return [await event_view(db, ev, contested) for ev in rows]


async def contest(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    event_id: uuid.UUID,
    *,
    reason: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The other participant disputes an attendance/completion record → moderation, job flagged disputed."""
    now = now or utcnow()
    party = await feedback.party_for(db, user_id, job_id, lock=True)
    job = party.job
    replay = await _by_key(db, job.id, user_id, idempotency_key)
    if replay is not None:
        if replay.kind != "completion_contested" or replay.contests_event_id != event_id:
            raise AppError(409, "idempotency_key_reused", "This Idempotency-Key was already used for another action")
        return await _contest_result(db, job, replay, False)
    target = (
        await db.execute(select(VisitEvent).where(VisitEvent.id == event_id, VisitEvent.job_id == job.id))
    ).scalar_one_or_none()
    if target is None:
        raise not_found("Visit")
    if target.kind not in CONTESTABLE:
        raise AppError(409, "not_contestable", "Only attendance or completion records can be contested")
    if target.actor_role == party.side or target.actor_id == user_id:
        raise AppError(403, "cannot_contest_own_record", "Only the other participant can contest this record")
    prior = (
        await db.execute(
            select(VisitEvent).where(
                VisitEvent.job_id == job.id,
                VisitEvent.kind == "completion_contested",
                VisitEvent.contests_event_id == target.id,
                VisitEvent.actor_role == party.side,
            )
        )
    ).scalar_one_or_none()
    if prior is not None:
        return await _contest_result(db, job, prior, False)
    ev = VisitEvent(
        job_id=job.id,
        assignment_id=target.assignment_id,
        kind="completion_contested",
        actor_id=user_id,
        actor_role=party.side,
        occurred_at=now,
        note=reason,
        contests_event_id=target.id,
        idempotency_key=idempotency_key,
        recorded_at=now,
    )
    db.add(ev)
    await db.flush()
    case = ModerationCase(
        job_id=job.id,
        visit_event_id=target.id,
        reporter_id=user_id,
        category="completion_contested",
        reason=reason,
        status="open",
        retention_hold=True,
    )
    db.add(case)
    await db.flush()
    db.add(ModerationAction(case_id=case.id, actor_id=user_id, action="reported", reason=reason))
    await audit.record(
        db,
        user_id,
        "moderation.case_opened",
        "moderation_case",
        case.id,
        {"category": "completion_contested", "visit_event_id": str(target.id)},
    )
    if not job.disputed:
        job.disputed = True
        job.version += 1
        job.updated_at = now
    await db.flush()
    recipients = (
        [job.owner_id]
        if party.side == "contractor"
        else (
            await feedback.contractor_recipients(db, party.assignment_id, party.organization_id)
            if party.assignment_id and party.organization_id
            else []
        )
    )
    for uid in recipients:
        await notify(db, uid, "visit_recorded", job_id=job.id, key=f"{ev.id}:{uid}")
    return await _contest_result(db, job, ev, True)


async def _contest_result(db: AsyncSession, job: ServiceJob, ev: VisitEvent, created: bool) -> dict[str, Any]:
    case_id = (
        await db.execute(
            select(ModerationCase.id)
            .where(
                ModerationCase.job_id == job.id,
                ModerationCase.visit_event_id == ev.contests_event_id,
                ModerationCase.reporter_id == ev.actor_id,
                ModerationCase.category == "completion_contested",
            )
            .order_by(ModerationCase.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "event": await event_view(db, ev),
        "case_id": case_id,
        "job_status": job.status,
        "job_version": job.version,
        "job_disputed": job.disputed,
        "created": created,
    }
