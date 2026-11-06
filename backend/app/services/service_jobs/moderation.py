"""Case-scoped moderation of reported feedback and contested visits (spec §3, §9.3, SJ-18).

A moderator (``users.role`` moderator, or a platform admin) sees only what a case is
about: the reported review with its responses and the version that was reported, or the
contested visit record — plus minimal job context. Never job media, access details,
invoices or other private job sections. Every view and action is audited; every action is
a :class:`ModerationAction` with actor, reason and the affected content version.

Nothing here scores, ranks, blacklists or affects booking or pricing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    ContractorOrganization,
    FeedbackVersion,
    FeedbackWindow,
    JobFeedback,
    ModerationAction,
    ModerationCase,
    ServiceJob,
    VisitEvent,
)
from app.models.user import User
from app.services import audit
from app.services.service_jobs import feedback, visits
from app.services.service_jobs.notify import notify

ACTIONS = ("assign", "restrict", "unrestrict", "resolve")
DISPOSITIONS = (
    "no_action",
    "addendum_requested",
    "content_restricted",
    "content_removed_for_personal_information",
    "eligibility_corrected",
)
ACTIVE = ("open", "under_review")
MODERATOR_ROLES = ("moderator", "admin")


def case_summary(case: ModerationCase) -> dict[str, Any]:
    return {
        "id": case.id,
        "job_id": case.job_id,
        "feedback_id": case.feedback_id,
        "visit_event_id": case.visit_event_id,
        "category": case.category,
        "status": case.status,
        "restrict_content": case.restrict_content,
        "assigned_moderator_id": case.assigned_moderator_id,
        "content_version": case.content_version,
        "disposition": case.disposition,
        "retention_hold": case.retention_hold,
        "created_at": case.created_at,
        "resolved_at": case.resolved_at,
    }


async def list_cases(db: AsyncSession, *, status: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
    q = select(ModerationCase)
    if status is None or status == "active":
        q = q.where(ModerationCase.status.in_(ACTIVE))
    elif status != "all":
        q = q.where(ModerationCase.status == status)
    q = q.order_by(ModerationCase.created_at, ModerationCase.id).limit(limit).offset(offset)
    return [case_summary(c) for c in (await db.execute(q)).scalars()]


async def _case(db: AsyncSession, case_id: uuid.UUID, *, lock: bool = False) -> ModerationCase:
    """Lock order: the job row first, then the case (and then its feedback)."""
    job_id = (await db.execute(select(ModerationCase.job_id).where(ModerationCase.id == case_id))).scalar_one_or_none()
    if job_id is None:
        raise not_found("Moderation case")
    if lock:
        await db.execute(
            select(ServiceJob.id)
            .where(ServiceJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    q = select(ModerationCase).where(ModerationCase.id == case_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one()


async def case_detail(db: AsyncSession, case: ModerationCase) -> dict[str, Any]:
    job = await db.get(ServiceJob, case.job_id)
    window = await db.get(FeedbackWindow, case.job_id)
    org_name = None
    if window is not None:
        org_name = (
            await db.execute(
                select(ContractorOrganization.name).where(ContractorOrganization.id == window.organization_id)
            )
        ).scalar_one_or_none()
    detail = case_summary(case)
    reporter = (await db.execute(select(User.full_name).where(User.id == case.reporter_id))).scalar_one_or_none()
    detail.update(
        {
            "reason": case.reason,
            "disposition_note": case.disposition_note,
            "reporter": {"id": case.reporter_id, "name": reporter},
            # Minimal context only: never media, access details, invoices or other sections.
            "job": {
                "id": job.id,
                "title": job.title,
                "status": job.status,
                "disputed": job.disputed,
                "organization_name": org_name,
            },
            "feedback": None,
            "reported_content": None,
            "visit_event": None,
            "contest_event": None,
            "actions": [],
        }
    )
    if case.feedback_id is not None and window is not None:
        fb = await db.get(JobFeedback, case.feedback_id)
        if fb is not None:
            detail["feedback"] = await feedback.feedback_view(db, fb, window, moderator=True)
            if case.content_version is not None:
                ver = (
                    await db.execute(
                        select(FeedbackVersion).where(
                            FeedbackVersion.feedback_id == fb.id, FeedbackVersion.version == case.content_version
                        )
                    )
                ).scalar_one_or_none()
                if ver is not None:
                    detail["reported_content"] = {
                        "version": ver.version,
                        "ratings": dict(ver.ratings or {}),
                        "narrative": ver.narrative,
                    }
    if case.visit_event_id is not None:
        target = await db.get(VisitEvent, case.visit_event_id)
        if target is not None:
            detail["visit_event"] = await visits.event_view(db, target)
            contest = (
                await db.execute(
                    select(VisitEvent)
                    .where(
                        VisitEvent.contests_event_id == target.id,
                        VisitEvent.actor_id == case.reporter_id,
                        VisitEvent.kind == "completion_contested",
                    )
                    .order_by(VisitEvent.recorded_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if contest is not None:
                detail["contest_event"] = await visits.event_view(db, contest)
    actions = (
        await db.execute(
            select(ModerationAction)
            .where(ModerationAction.case_id == case.id)
            .order_by(ModerationAction.created_at, ModerationAction.id)
        )
    ).scalars()
    detail["actions"] = [
        {
            "id": a.id,
            "action": a.action,
            "actor_id": a.actor_id,
            "reason": a.reason,
            "content_version": a.content_version,
            "created_at": a.created_at,
        }
        for a in actions
    ]
    return detail


async def get_case(db: AsyncSession, moderator_id: uuid.UUID, case_id: uuid.UUID) -> dict[str, Any]:
    case = await _case(db, case_id)
    await audit.record(db, moderator_id, "moderation.case_viewed", "moderation_case", case.id, None)
    return await case_detail(db, case)


async def _refresh_feedback_restriction(db: AsyncSession, fb: JobFeedback | None) -> None:
    if fb is None:
        return
    restricting = (
        await db.execute(
            select(ModerationCase.id)
            .where(
                ModerationCase.feedback_id == fb.id,
                ModerationCase.status.in_(ACTIVE),
                ModerationCase.restrict_content.is_(True),
            )
            .limit(1)
        )
    ).first()
    fb.under_review = restricting is not None


async def act(
    db: AsyncSession,
    moderator_id: uuid.UUID,
    case_id: uuid.UUID,
    *,
    action: str,
    reason: str,
    disposition: str | None = None,
    assignee_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or utcnow()
    case = await _case(db, case_id, lock=True)
    if case.status == "resolved":
        raise AppError(409, "case_resolved", "This case has already been resolved")
    fb = None
    if case.feedback_id is not None:
        fb = (
            await db.execute(
                select(JobFeedback)
                .where(JobFeedback.id == case.feedback_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
    content_version = fb.version if fb is not None else case.content_version
    detail: dict[str, Any] = {"reason": reason, "content_version": content_version}
    if action == "assign":
        target = assignee_id or moderator_id
        role = (await db.execute(select(User.role).where(User.id == target))).scalar_one_or_none()
        if role not in MODERATOR_ROLES:
            raise AppError(422, "not_a_moderator", "Cases can be assigned only to a moderator")
        case.assigned_moderator_id = target
        case.status = "under_review"
        detail["assignee_id"] = str(target)
    elif action in ("restrict", "unrestrict"):
        if fb is None:
            raise AppError(409, "nothing_to_restrict", "This case is not about review content")
        case.restrict_content = action == "restrict"
        await db.flush()
        await _refresh_feedback_restriction(db, fb)
    elif action == "resolve":
        if disposition not in DISPOSITIONS:
            raise AppError(422, "disposition_required", "Resolving a case needs a recorded disposition")
        await _apply_disposition(db, case, fb, disposition, now)
        case.status = "resolved"
        case.disposition = disposition
        case.disposition_note = reason
        case.resolved_at = now
        case.retention_hold = False
        await db.flush()
        await _refresh_feedback_restriction(db, fb)
        await _clear_dispute(db, case)
        detail["disposition"] = disposition
    else:
        raise AppError(422, "invalid_action", "Unknown moderation action")
    db.add(
        ModerationAction(
            case_id=case.id,
            actor_id=moderator_id,
            action=action if action != "resolve" else f"resolve:{disposition}",
            reason=reason,
            content_version=content_version,
        )
    )
    await audit.record(db, moderator_id, f"moderation.{action}", "moderation_case", case.id, detail)
    await db.flush()
    if action == "resolve":
        recipients = {case.reporter_id}
        if fb is not None and disposition != "no_action":
            recipients.add(fb.author_id)
        for uid in sorted(recipients, key=str):
            await notify(db, uid, "moderation_update", job_id=case.job_id, key=f"{case.id}:resolved:{uid}")
    return await case_detail(db, case)


async def _apply_disposition(
    db: AsyncSession, case: ModerationCase, fb: JobFeedback | None, disposition: str, now: datetime
) -> None:
    if disposition == "content_removed_for_personal_information":
        if fb is None:
            raise AppError(409, "nothing_to_remove", "This case is not about review content")
        # Purge the narrative from the review and every stored version (retention, spec §9.3).
        fb.narrative = None
        await db.execute(update(FeedbackVersion).where(FeedbackVersion.feedback_id == fb.id).values(narrative=None))
    elif disposition == "content_restricted" and fb is None:
        raise AppError(409, "nothing_to_restrict", "This case is not about review content")
    elif disposition == "eligibility_corrected":
        # The recorded visit did not establish eligibility: withdraw the job's reviews from
        # the parties (kept for the audit trail) and stop any further submissions.
        window = (
            await db.execute(
                select(FeedbackWindow)
                .where(FeedbackWindow.job_id == case.job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if window is not None:
            if window.closes_at > now:
                window.closes_at = now
            if window.revealed_at is None:
                window.revealed_at = now
            await db.execute(
                update(JobFeedback).where(JobFeedback.job_id == case.job_id).values(status="withdrawn", updated_at=now)
            )


async def _clear_dispute(db: AsyncSession, case: ModerationCase) -> None:
    if case.category != "completion_contested":
        return
    still_open = (
        await db.execute(
            select(ModerationCase.id)
            .where(
                ModerationCase.job_id == case.job_id,
                ModerationCase.category == "completion_contested",
                ModerationCase.status.in_(ACTIVE),
                ModerationCase.id != case.id,
            )
            .limit(1)
        )
    ).first()
    if still_open is None:
        job = await db.get(ServiceJob, case.job_id)
        if job is not None and job.disputed:
            job.disputed = False
            job.version += 1
