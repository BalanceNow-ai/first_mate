"""Visits and reciprocal job feedback: eligibility, blind drafts/submission, reveal, responses, reports.

Spec §9 (SJ-16, SJ-17, SJ-18, SJ-21). Only the two job parties reach these endpoints:
the owner, and an assigned member of the contractor organization (whose feedback
participation survives a later revocation of working access). Anyone else — including a
platform admin or moderator — gets 404; moderators work through ``/moderation``. Before
reveal no response says anything about the other side's review, not even whether it exists.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.rate_limit import mutation_limit
from app.database import get_db, utcnow
from app.middleware.auth import CurrentUserId
from app.schemas.service_feedback import (
    ContestResult,
    FeedbackDraft,
    FeedbackOut,
    FeedbackOverview,
    FeedbackReportCreate,
    FeedbackResponseCreate,
    FeedbackSubmit,
    ReportOut,
    VisitContest,
    VisitCreate,
    VisitEventOut,
    VisitResult,
)
from app.services.service_jobs import feedback, visits

router = APIRouter(tags=["Service feedback"])

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,100}$")


def _key(value: str | None) -> str:
    if value is None or not IDEMPOTENCY_KEY.match(value):
        raise AppError(
            400,
            "idempotency_key_required",
            "An Idempotency-Key header of 8-100 characters (letters, digits, _ - : .) is required",
        )
    return value


# Visits --------------------------------------------------------------------------------
@router.post(
    "/service-jobs/{job_id}/visits",
    response_model=VisitResult,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": VisitResult, "description": "Existing event for this Idempotency-Key"}},
    dependencies=[Depends(mutation_limit())],
)
async def record_visit(
    job_id: uuid.UUID,
    body: VisitCreate,
    response: Response,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Record scheduled / attended / completed / cancelled (owner or an assigned contractor member).

    The first attended or completed visit opens the 14-day feedback window."""
    result = await visits.record(
        db,
        user_id,
        job_id,
        kind=body.kind,
        occurred_at=body.occurred_at,
        note=body.note,
        expected_version=body.expected_version,
        idempotency_key=_key(idempotency_key),
    )
    if not result["created"]:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/service-jobs/{job_id}/visits", response_model=list[VisitEventOut])
async def list_visits(
    job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict]:
    return await visits.list_events(db, user_id, job_id)


@router.post(
    "/service-jobs/{job_id}/visits/{event_id}/contest",
    response_model=ContestResult,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": ContestResult, "description": "Existing contest for this record"}},
    dependencies=[Depends(mutation_limit())],
)
async def contest_visit(
    job_id: uuid.UUID,
    event_id: uuid.UUID,
    body: VisitContest,
    response: Response,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """The other participant disputes an attendance/completion record (opens a moderation case)."""
    result = await visits.contest(
        db, user_id, job_id, event_id, reason=body.reason, idempotency_key=_key(idempotency_key)
    )
    if not result["created"]:
        response.status_code = status.HTTP_200_OK
    return result


# Feedback ------------------------------------------------------------------------------
@router.get("/service-jobs/{job_id}/feedback", response_model=FeedbackOverview)
async def get_feedback(
    job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """Eligibility, window and the caller's own review; the other side's only once revealed."""
    party = await feedback.party_for(db, user_id, job_id)
    return await feedback.overview(db, party, utcnow())


@router.put(
    "/service-jobs/{job_id}/feedback/{direction}",
    response_model=FeedbackOverview,
    dependencies=[Depends(mutation_limit())],
)
async def save_feedback_draft(
    job_id: uuid.UUID,
    direction: str,
    body: FeedbackDraft,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Create or replace the caller's own review before reveal (versioned; ``expected_version`` → 409)."""
    return await feedback.save_draft(
        db,
        user_id,
        job_id,
        direction,
        ratings=dict(body.ratings),
        narrative=body.narrative or None,
        expected_version=body.expected_version,
    )


@router.post(
    "/service-jobs/{job_id}/feedback/{direction}/submit",
    response_model=FeedbackOverview,
    responses={200: {"model": FeedbackOverview, "description": "Already submitted"}},
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def submit_feedback(
    job_id: uuid.UUID,
    direction: str,
    response: Response,
    user_id: CurrentUserId,
    body: FeedbackSubmit | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Submit blind. Repeats return the submitted review (200). Reveals both when the other side has submitted."""
    _key(idempotency_key)
    result, created = await feedback.submit(
        db, user_id, job_id, direction, expected_version=body.expected_version if body else None
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/service-feedback/{feedback_id}", response_model=FeedbackOut)
async def get_review(
    feedback_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    fa = await feedback.feedback_for(db, user_id, feedback_id)
    return await feedback.feedback_view(db, fa.feedback, fa.window)


@router.post(
    "/service-feedback/{feedback_id}/responses",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def add_feedback_response(
    feedback_id: uuid.UUID,
    body: FeedbackResponseCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Subject: ``response`` (one) or ``correction_request``; author side: ``addendum``. Append-only."""
    return await feedback.add_response(db, user_id, feedback_id, kind=body.kind, text=body.text)


@router.post(
    "/service-feedback/{feedback_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": ReportOut, "description": "You already have an open report of this kind"}},
    dependencies=[Depends(mutation_limit())],
)
async def report_feedback(
    feedback_id: uuid.UUID,
    body: FeedbackReportCreate,
    response: Response,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> object:
    """The reviewed party reports a revealed review to moderation."""
    case, created = await feedback.report(
        db,
        user_id,
        feedback_id,
        category=body.category,
        reason=body.reason,
        restrict_content=body.restrict_content,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return case
