"""Reciprocal job feedback: eligibility, blind drafts/submission, reveal, responses and reports.

Spec §9 (SJ-16, SJ-17, SJ-18, SJ-21). Rules owned here, server-side:

* **Eligibility** is a :class:`FeedbackWindow`, opened only by the first recorded
  ``attended``/``completed`` visit on an accepted assignment (``visits.py``). Its
  ``opens_at`` is the server time of that event and ``closes_at`` is ``feedback_window_days``
  later. An invoice upload or AI-created job never opens one.
* **Parties**: the job owner (direction ``owner_to_contractor``, subject: the organization)
  and a named active member of the window's organization who is or was an assigned member
  of the window's assignment (``contractor_to_owner``, on behalf of the organization —
  one review per organization). Revoking the working assignment later keeps this
  participation record but never restores job media or access details.
* **Blind**: before reveal a party sees only its own side's review. Nothing in any
  response, count, status, notification or listing says whether — or what — the other
  side wrote. The only statement is the reveal rule.
* **Reveal** happens exactly once per window, under the job row lock: when the second side
  submits (same transaction) or by the sweep once ``closes_at`` has passed (one-sided reveal
  shows only what was submitted). Revealed reviews are frozen; later changes are visible
  responses/addenda/correction requests.
* **Ratings** are integers 1–5 or ``"not_applicable"``; there is no default, an absent
  answer stays absent and nothing is averaged, counted or ranked.

Lock order (extends D22): job row → feedback window → feedback rows → moderation cases.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    ContractorMembership,
    ContractorOrganization,
    FeedbackResponse,
    FeedbackVersion,
    FeedbackWindow,
    JobAssignmentMember,
    JobFeedback,
    ModerationAction,
    ModerationCase,
    ServiceJob,
    VisitEvent,
)
from app.models.user import User
from app.services import audit
from app.services.service_jobs import access
from app.services.service_jobs.notify import notify

OWNER_TO_CONTRACTOR = "owner_to_contractor"
CONTRACTOR_TO_OWNER = "contractor_to_owner"
DIRECTIONS = (OWNER_TO_CONTRACTOR, CONTRACTOR_TO_OWNER)
NOT_APPLICABLE = "not_applicable"

# Spec §9.2 — exactly these dimensions; no payment-timeliness dimension.
DIMENSIONS: dict[str, tuple[tuple[str, str], ...]] = {
    OWNER_TO_CONTRACTOR: (
        ("communication_clarity", "Communication and clarity"),
        ("arrival_access_coordination", "Arrival and access coordination"),
        ("explanation_of_work_and_changes", "Explanation of work and changes"),
        ("care_and_agreed_work_delivery", "Care and agreed work delivery"),
        ("invoice_clarity_and_scope_relationship", "Invoice clarity and relationship to scope"),
    ),
    CONTRACTOR_TO_OWNER: (
        ("problem_description_accuracy", "Accuracy of problem description and evidence"),
        ("access_arrival_accuracy", "Accuracy of access and arrival arrangements"),
        ("equipment_site_prepared", "Equipment and site prepared as agreed"),
        ("availability_for_decisions", "Availability for agreed decisions"),
        ("communication_and_scope_changes", "Communication and handling of scope changes"),
    ),
}
# A visit attended and then cancelled: the agreed work was not delivered, so that
# dimension does not apply. Every contractor→owner dimension concerns the owner's
# preparation and communication up to the attended visit and still applies.
INAPPLICABLE_BY_BASIS: dict[str, dict[str, frozenset[str]]] = {
    "attended_then_cancelled": {
        OWNER_TO_CONTRACTOR: frozenset({"care_and_agreed_work_delivery"}),
        CONTRACTOR_TO_OWNER: frozenset(),
    }
}
DIMENSIONS_KEYS = {d: frozenset(k for k, _ in dims) for d, dims in DIMENSIONS.items()}
RESPONSE_KINDS = ("response", "correction_request", "addendum")
REPORT_CATEGORIES = ("factual_dispute", "opinion", "harassment", "personal_or_security_information", "other")
REMOVED_DISPOSITION = "content_removed_for_personal_information"
RESTRICTED_DISPOSITION = "content_restricted"


def applicable_dimensions(direction: str, basis: str | None) -> list[str]:
    excluded = INAPPLICABLE_BY_BASIS.get(basis or "", {}).get(direction, frozenset())
    return [key for key, _ in DIMENSIONS[direction] if key not in excluded]


def reveal_rule(window: FeedbackWindow | None) -> str:
    if window is None:
        return "Feedback opens after a visit is recorded as attended or completed."
    closes = window.closes_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return (
        f"Reviews are revealed when both sides submit, or on {closes}. "
        "Until then neither side can see the other's review."
    )


# Parties -----------------------------------------------------------------------------
@dataclass
class Party:
    job: ServiceJob
    user_id: uuid.UUID
    side: str  # "owner" | "contractor"
    window: FeedbackWindow | None
    organization_id: uuid.UUID | None
    assignment_id: uuid.UUID | None

    @property
    def direction(self) -> str:
        return OWNER_TO_CONTRACTOR if self.side == "owner" else CONTRACTOR_TO_OWNER

    @property
    def other_direction(self) -> str:
        return CONTRACTOR_TO_OWNER if self.side == "owner" else OWNER_TO_CONTRACTOR


async def _job(db: AsyncSession, job_id: uuid.UUID, *, lock: bool) -> ServiceJob | None:
    q = select(ServiceJob).where(ServiceJob.id == job_id, ServiceJob.deleted_at.is_(None))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one_or_none()


async def window_for(db: AsyncSession, job_id: uuid.UUID, *, lock: bool = False) -> FeedbackWindow | None:
    q = select(FeedbackWindow).where(FeedbackWindow.job_id == job_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one_or_none()


async def was_assigned(db: AsyncSession, window: FeedbackWindow, user_id: uuid.UUID) -> bool:
    """An active member of the window's organization who is or was assigned to its assignment."""
    if await access.active_membership(db, user_id, window.organization_id) is None:
        return False
    row = (
        await db.execute(
            select(JobAssignmentMember.id)
            .where(JobAssignmentMember.assignment_id == window.assignment_id, JobAssignmentMember.user_id == user_id)
            .limit(1)
        )
    ).first()
    return row is not None


async def party_for(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID, *, lock: bool = False, allow_live: bool = True
) -> Party:
    """Resolve a feedback/visit participant, or 404 (no existence leak).

    With a window: the owner, or a contractor who is/was assigned to the window's
    assignment (working access may since have been revoked). Without one (and with
    ``allow_live``): the owner, or an assigned member of the live accepted assignment.
    Platform admins and moderators get nothing here; moderators work through cases."""
    job = await _job(db, job_id, lock=lock)
    if job is None:
        raise not_found("Service job")
    window = await window_for(db, job.id, lock=lock)
    if job.owner_id == user_id:
        org = window.organization_id if window else None
        assignment_id = window.assignment_id if window else None
        if window is None:
            live = await access.live_assignment(db, job.id)
            if live is not None and live.status == "accepted":
                org, assignment_id = live.organization_id, live.id
        return Party(job, user_id, "owner", window, org, assignment_id)
    if window is not None and await was_assigned(db, window, user_id):
        return Party(job, user_id, "contractor", window, window.organization_id, window.assignment_id)
    if window is None and allow_live:
        live = await access.live_assignment(db, job.id)
        if (
            live is not None
            and live.status == "accepted"
            and await access.active_membership(db, user_id, live.organization_id) is not None
            and await access.assigned_member(db, live.id, user_id) is not None
        ):
            return Party(job, user_id, "contractor", None, live.organization_id, live.id)
    raise not_found("Service job")


async def contractor_recipients(db: AsyncSession, assignment_id: uuid.UUID, organization_id: uuid.UUID) -> list:
    """Currently assigned members with an active membership (notification recipients)."""
    rows = await db.execute(
        select(JobAssignmentMember.user_id)
        .join(
            ContractorMembership,
            (ContractorMembership.user_id == JobAssignmentMember.user_id)
            & (ContractorMembership.organization_id == organization_id),
        )
        .where(
            JobAssignmentMember.assignment_id == assignment_id,
            JobAssignmentMember.removed_at.is_(None),
            ContractorMembership.status == "active",
        )
        .order_by(JobAssignmentMember.user_id)
    )
    return [r[0] for r in rows]


async def notify_parties(db: AsyncSession, window: FeedbackWindow, kind: str, key: str) -> None:
    recipients = [window.owner_id, *await contractor_recipients(db, window.assignment_id, window.organization_id)]
    for uid in recipients:
        await notify(db, uid, kind, job_id=window.job_id, key=f"{key}:{uid}")


# Window ------------------------------------------------------------------------------
async def open_window(
    db: AsyncSession, job: ServiceJob, event: VisitEvent, organization_id: uuid.UUID, now: datetime
) -> FeedbackWindow:
    """Open the job's single window from a server-recorded eligibility event (caller holds the job lock)."""
    days = get_settings().feedback_window_days
    window = FeedbackWindow(
        job_id=job.id,
        assignment_id=event.assignment_id,
        organization_id=organization_id,
        owner_id=job.owner_id,
        eligibility_event_id=event.id,
        basis=event.kind,
        opens_at=now,
        closes_at=now + timedelta(days=days),
    )
    db.add(window)
    await db.flush()
    await notify_parties(db, window, "feedback_open", f"{job.id}")
    return window


def window_view(window: FeedbackWindow | None, now: datetime) -> dict | None:
    if window is None:
        return None
    return {
        "basis": window.basis,
        "opens_at": window.opens_at,
        "closes_at": window.closes_at,
        "is_open": window.revealed_at is None and now < window.closes_at,
        "revealed": window.revealed_at is not None,
        "revealed_at": window.revealed_at,
    }


# Views -------------------------------------------------------------------------------
async def _cases(db: AsyncSession, feedback_id: uuid.UUID) -> list[ModerationCase]:
    return list(
        (
            await db.execute(
                select(ModerationCase)
                .where(ModerationCase.feedback_id == feedback_id)
                .order_by(ModerationCase.created_at, ModerationCase.id)
            )
        ).scalars()
    )


def content_state(fb: JobFeedback, cases: list[ModerationCase]) -> str:
    resolved = [c.disposition for c in cases if c.status == "resolved"]
    if REMOVED_DISPOSITION in resolved:
        return "removed"
    if any(c.status != "resolved" and c.restrict_content for c in cases) or fb.under_review:
        return "under_review"
    if RESTRICTED_DISPOSITION in resolved:
        return "restricted"
    return "visible"


async def _names(db: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
    return {r[0]: r[1] for r in rows}


async def _org_name(db: AsyncSession, org_id: uuid.UUID | None) -> str | None:
    if org_id is None:
        return None
    return (
        await db.execute(select(ContractorOrganization.name).where(ContractorOrganization.id == org_id))
    ).scalar_one_or_none()


async def responses_of(db: AsyncSession, fb: JobFeedback) -> list[FeedbackResponse]:
    return list(
        (
            await db.execute(
                select(FeedbackResponse)
                .where(FeedbackResponse.feedback_id == fb.id)
                .order_by(FeedbackResponse.created_at, FeedbackResponse.id)
            )
        ).scalars()
    )


def _side_of_author(fb: JobFeedback, author_id: uuid.UUID, owner_id: uuid.UUID) -> str:
    return "owner" if author_id == owner_id else "contractor"


async def feedback_view(
    db: AsyncSession,
    fb: JobFeedback,
    window: FeedbackWindow,
    *,
    moderator: bool = False,
) -> dict[str, Any]:
    """One review as a party (or a case moderator) may see it. Callers decide visibility."""
    cases = await _cases(db, fb.id)
    state = content_state(fb, cases)
    responses = await responses_of(db, fb)
    names = await _names(db, {fb.author_id, *(r.author_id for r in responses)})
    event = await db.get(VisitEvent, window.eligibility_event_id)
    show_text = moderator or state == "visible"
    return {
        "id": fb.id,
        "job_id": fb.job_id,
        "direction": fb.direction,
        "status": fb.status,
        "version": fb.version,
        "author": {
            "id": fb.author_id,
            "name": names.get(fb.author_id),
            "role": "owner" if fb.direction == OWNER_TO_CONTRACTOR else "contractor",
        },
        "organization": {"id": fb.organization_id, "name": await _org_name(db, fb.organization_id)},
        "basis": window.basis,
        "visit_date": event.occurred_at if event else None,
        "ratings": dict(fb.ratings or {}),
        "narrative": fb.narrative if show_text else None,
        "content_state": state,
        "submitted_at": fb.submitted_at,
        "revealed_at": fb.revealed_at,
        "created_at": fb.created_at,
        "updated_at": fb.updated_at,
        "responses": [
            {
                "id": r.id,
                "kind": r.kind,
                "author": {
                    "id": r.author_id,
                    "name": names.get(r.author_id),
                    "role": _side_of_author(fb, r.author_id, window.owner_id),
                },
                "text": r.text if (moderator or r.hidden_by_case_id is None) else None,
                "content_state": "visible" if r.hidden_by_case_id is None else "under_review",
                "created_at": r.created_at,
            }
            for r in responses
        ],
    }


async def _feedback(db: AsyncSession, job_id: uuid.UUID, direction: str, *, lock: bool = False) -> JobFeedback | None:
    q = select(JobFeedback).where(JobFeedback.job_id == job_id, JobFeedback.direction == direction)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one_or_none()


def _ineligible_reason(job: ServiceJob, window: FeedbackWindow | None) -> str | None:
    if window is not None:
        return None
    return "cancelled_before_attendance" if job.status == "cancelled" else "no_attended_visit"


async def overview(db: AsyncSession, party: Party, now: datetime) -> dict[str, Any]:
    """GET /service-jobs/{id}/feedback — the party's own side, and the other side only after reveal."""
    window = party.window
    mine = theirs = None
    can_edit = False
    if window is not None:
        own = await _feedback(db, party.job.id, party.direction)
        if own is not None:
            mine = await feedback_view(db, own, window)
        other = await _feedback(db, party.job.id, party.other_direction)
        if other is not None and other.status == "revealed":
            theirs = await feedback_view(db, other, window)
        can_edit = (
            window.revealed_at is None
            and now < window.closes_at
            and (own is None or (own.status in ("draft", "submitted") and _may_author(party, own)))
        )
    return {
        "job_id": party.job.id,
        "my_side": party.side,
        "my_direction": party.direction,
        "eligible": window is not None,
        "ineligible_reason": _ineligible_reason(party.job, window),
        "window": window_view(window, now),
        "reveal_rule": reveal_rule(window),
        "dimensions": [
            {"key": key, "label": label}
            for key, label in DIMENSIONS[party.direction]
            if key in applicable_dimensions(party.direction, window.basis if window else None)
        ],
        "can_edit": can_edit,
        "mine": mine,
        "theirs": theirs,
    }


# Drafts, submission, reveal -----------------------------------------------------------
def _may_author(party: Party, fb: JobFeedback) -> bool:
    return fb.author_id == party.user_id


def _require_direction(party: Party, direction: str) -> None:
    if direction not in DIRECTIONS:
        raise not_found("Feedback")
    if direction != party.direction:
        raise AppError(403, "wrong_feedback_direction", "You can only write the review for your own side of the job")


def _require_open(window: FeedbackWindow | None, now: datetime) -> FeedbackWindow:
    if window is None:
        raise AppError(
            409, "feedback_not_eligible", "Feedback opens only after a visit is recorded as attended or completed"
        )
    if window.revealed_at is not None:
        raise AppError(409, "feedback_revealed", "Feedback for this job has been revealed and can no longer change")
    if now >= window.closes_at:
        raise AppError(409, "feedback_window_closed", "The feedback window for this job has closed")
    return window


def validate_ratings(direction: str, basis: str, ratings: dict[str, Any]) -> dict[str, Any]:
    allowed = applicable_dimensions(direction, basis)
    unknown = sorted(k for k in ratings if k not in DIMENSIONS_KEYS[direction])
    if unknown:
        raise AppError(
            422, "unknown_dimension", "These are not feedback questions for this review", extra={"keys": unknown}
        )
    inapplicable = sorted(k for k in ratings if k not in allowed)
    if inapplicable:
        raise AppError(
            422,
            "dimension_not_applicable",
            "These questions do not apply to a visit that was cancelled after attendance",
            extra={"keys": inapplicable},
        )
    clean: dict[str, Any] = {}
    for key, value in ratings.items():
        if value == NOT_APPLICABLE:
            clean[key] = NOT_APPLICABLE
        elif isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 5:
            clean[key] = value
        else:
            raise AppError(422, "invalid_rating", "Ratings are whole numbers from 1 to 5, or not_applicable")
    return clean


async def save_draft(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    direction: str,
    *,
    ratings: dict[str, Any],
    narrative: str | None,
    expected_version: int | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create or edit the party's own review before reveal; every save is a FeedbackVersion."""
    now = now or utcnow()
    party = await party_for(db, user_id, job_id, lock=True, allow_live=False)
    _require_direction(party, direction)
    window = _require_open(party.window, now)
    clean = validate_ratings(direction, window.basis, ratings)
    fb = await _feedback(db, job_id, direction, lock=True)
    if fb is None:
        access.check_version(0, expected_version, "review")
        fb = JobFeedback(
            job_id=job_id,
            direction=direction,
            author_id=user_id,
            organization_id=window.organization_id,
            ratings=clean,
            narrative=narrative,
            status="draft",
            version=1,
        )
        db.add(fb)
        await db.flush()
    else:
        if not _may_author(party, fb):
            raise AppError(
                403, "feedback_authored_by_colleague", "A colleague is writing your organization's review for this job"
            )
        if fb.status not in ("draft", "submitted"):
            raise AppError(409, "feedback_frozen", "This review can no longer be edited")
        access.check_version(fb.version, expected_version, "review")
        if fb.status == "submitted" and not clean and not (narrative or "").strip():
            raise AppError(422, "feedback_empty", "A submitted review needs at least one answer or a comment")
        fb.ratings = clean
        fb.narrative = narrative
        fb.version += 1
        fb.updated_at = now
    db.add(FeedbackVersion(feedback_id=fb.id, version=fb.version, ratings=clean, narrative=narrative))
    await db.flush()
    return await overview(db, party, now)


async def submit(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    direction: str,
    *,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Submit the party's review blind. Repeating a submission returns it unchanged.

    When this is the second side's submission, both reviews are revealed in this same
    transaction (serialized under the job lock, so concurrent submissions reveal once)."""
    now = now or utcnow()
    party = await party_for(db, user_id, job_id, lock=True, allow_live=False)
    _require_direction(party, direction)
    fb = await _feedback(db, job_id, direction, lock=True) if party.window is not None else None
    if fb is not None and fb.status in ("submitted", "revealed"):
        return await overview(db, party, now), False
    window = _require_open(party.window, now)
    if fb is None:
        raise AppError(409, "feedback_no_draft", "Save your answers before submitting")
    if not _may_author(party, fb):
        raise AppError(
            403, "feedback_authored_by_colleague", "A colleague is writing your organization's review for this job"
        )
    if fb.status != "draft":
        raise AppError(409, "feedback_frozen", "This review can no longer be submitted")
    access.check_version(fb.version, expected_version, "review")
    validate_ratings(direction, window.basis, fb.ratings or {})
    if not fb.ratings and not (fb.narrative or "").strip():
        raise AppError(422, "feedback_empty", "Answer at least one question or add a comment before submitting")
    fb.status = "submitted"
    fb.submitted_at = now
    fb.updated_at = now
    await db.flush()
    other = await _feedback(db, job_id, party.other_direction, lock=True)
    if other is not None and other.status == "submitted":
        await _reveal(db, window, [fb, other], now)
    return await overview(db, party, now), True


async def _reveal(db: AsyncSession, window: FeedbackWindow, feedbacks: list[JobFeedback], now: datetime) -> int:
    """Reveal and freeze every submitted review of the window (caller holds the job lock)."""
    revealed = 0
    for fb in feedbacks:
        if fb.status == "submitted":
            fb.status = "revealed"
            fb.revealed_at = now
            revealed += 1
    window.revealed_at = now
    await db.flush()
    if revealed:
        await notify_parties(db, window, "feedback_revealed", f"{window.job_id}")
    return revealed


async def reveal_due(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Beat sweep: reveal every window whose ``closes_at`` has passed. Idempotent.

    Each job is handled under its own row lock and committed on its own, so a racing
    late submission either commits first (and is revealed here) or sees the window
    revealed/closed and is refused."""
    now = now or utcnow()
    due = (
        await db.execute(
            select(FeedbackWindow.job_id)
            .where(FeedbackWindow.revealed_at.is_(None), FeedbackWindow.closes_at <= now)
            .order_by(FeedbackWindow.closes_at)
        )
    ).scalars()
    windows = reviews = 0
    for job_id in list(due):
        await db.execute(
            select(ServiceJob.id)
            .where(ServiceJob.id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        window = await window_for(db, job_id, lock=True)
        if window is not None and window.revealed_at is None and window.closes_at <= now:
            rows = list(
                (
                    await db.execute(
                        select(JobFeedback)
                        .where(JobFeedback.job_id == job_id)
                        .order_by(JobFeedback.direction)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalars()
            )
            reviews += await _reveal(db, window, rows, now)
            windows += 1
        await db.commit()
    return {"windows_revealed": windows, "reviews_revealed": reviews}


# Responses and reports ------------------------------------------------------------------
@dataclass
class FeedbackAccess:
    party: Party
    feedback: JobFeedback
    window: FeedbackWindow

    @property
    def is_subject(self) -> bool:
        return self.feedback.direction != self.party.direction

    @property
    def is_author_side(self) -> bool:
        return self.feedback.direction == self.party.direction


async def feedback_for(
    db: AsyncSession, user_id: uuid.UUID, feedback_id: uuid.UUID, *, lock: bool = False
) -> FeedbackAccess:
    """A review the user may see: their own side's, or the other side's once revealed (else 404)."""
    job_id = (await db.execute(select(JobFeedback.job_id).where(JobFeedback.id == feedback_id))).scalar_one_or_none()
    if job_id is None:
        raise not_found("Feedback")
    try:
        party = await party_for(db, user_id, job_id, lock=lock, allow_live=False)
    except AppError:
        raise not_found("Feedback") from None
    q = select(JobFeedback).where(JobFeedback.id == feedback_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    fb = (await db.execute(q)).scalar_one()
    if party.window is None or fb.status == "withdrawn":
        raise not_found("Feedback")
    if fb.direction != party.direction and fb.status != "revealed":
        raise not_found("Feedback")
    return FeedbackAccess(party, fb, party.window)


async def add_response(
    db: AsyncSession, user_id: uuid.UUID, feedback_id: uuid.UUID, *, kind: str, text: str
) -> dict[str, Any]:
    """Append a response/correction request (subject) or an addendum (author side). Never edits the review."""
    fa = await feedback_for(db, user_id, feedback_id, lock=True)
    if fa.feedback.status != "revealed":
        raise AppError(409, "feedback_not_revealed", "Responses can be added once feedback has been revealed")
    if kind in ("response", "correction_request") and not fa.is_subject:
        raise AppError(403, "subject_only", "Only the person or organization reviewed can respond to this review")
    if kind == "addendum" and not fa.is_author_side:
        raise AppError(403, "author_only", "Only the review's author side can add an addendum")
    if kind == "response":
        existing = [r for r in await responses_of(db, fa.feedback) if r.kind == "response"]
        if existing:
            raise AppError(409, "already_responded", "This review already has a response; responses cannot be edited")
    resp = FeedbackResponse(feedback_id=fa.feedback.id, author_id=user_id, kind=kind, text=text)
    db.add(resp)
    await db.flush()
    if fa.is_subject:
        if fa.feedback.direction == OWNER_TO_CONTRACTOR:
            recipients = [fa.window.owner_id]
        else:
            recipients = await contractor_recipients(db, fa.window.assignment_id, fa.window.organization_id)
    else:
        recipients = (
            await contractor_recipients(db, fa.window.assignment_id, fa.window.organization_id)
            if fa.feedback.direction == OWNER_TO_CONTRACTOR
            else [fa.window.owner_id]
        )
    for uid in recipients:
        if uid != user_id:
            await notify(db, uid, "feedback_response", job_id=fa.feedback.job_id, key=f"{resp.id}:{uid}")
    return await feedback_view(db, fa.feedback, fa.window)


async def report(
    db: AsyncSession,
    user_id: uuid.UUID,
    feedback_id: uuid.UUID,
    *,
    category: str,
    reason: str,
    restrict_content: bool,
) -> tuple[ModerationCase, bool]:
    """The subject reports a revealed review → a moderation case bound to its content version.

    Reporting never suppresses the review by itself; only a personal/security-information
    report may ask to show a neutral "under review" state while the case is open."""
    fa = await feedback_for(db, user_id, feedback_id, lock=True)
    if fa.feedback.status != "revealed" or not fa.is_subject:
        raise AppError(403, "subject_only", "Only the person or organization reviewed can report this review")
    if restrict_content and category != "personal_or_security_information":
        raise AppError(
            422,
            "restriction_not_available",
            "Text can be hidden while under review only for personal or security information reports",
        )
    existing = (
        await db.execute(
            select(ModerationCase).where(
                ModerationCase.feedback_id == fa.feedback.id,
                ModerationCase.reporter_id == user_id,
                ModerationCase.category == category,
                ModerationCase.status != "resolved",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    case = ModerationCase(
        job_id=fa.feedback.job_id,
        feedback_id=fa.feedback.id,
        reporter_id=user_id,
        category=category,
        reason=reason,
        content_version=fa.feedback.version,
        status="open",
        restrict_content=restrict_content,
        retention_hold=True,
    )
    db.add(case)
    await db.flush()
    if restrict_content:
        fa.feedback.under_review = True
    db.add(
        ModerationAction(
            case_id=case.id, actor_id=user_id, action="reported", reason=reason, content_version=case.content_version
        )
    )
    await audit.record(
        db,
        user_id,
        "moderation.case_opened",
        "moderation_case",
        case.id,
        {"category": category, "feedback_id": str(fa.feedback.id), "content_version": case.content_version},
    )
    await db.flush()
    return case, True
