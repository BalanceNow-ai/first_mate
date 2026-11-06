"""Evidence requests: propose / request / answer / mark unavailable / waive (SJ-01–SJ-03, SJ-08).

* Owner and assigned contractors with the ``evidence`` section read requests.
* The owner accepts a guidance proposal (``assistant`` request) or writes one; an assigned
  contractor with ``evidence`` asks for a specific additional view (SJ-08).
* Only the owner answers (note / manual entry here; photo answers come from the media
  workstream), marks a request unavailable or waives it. ``cannot_safely_access`` flags
  technician inspection and records a visible gap (SJ-03). There is no photo count.

Callers resolve the actor with ``access.job_for(lock=True)`` before any mutation here, so
the job row is locked before the request row (lock order: job → child rows).
"""

from __future__ import annotations

import uuid

from sqlalchemy import case, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import EvidenceAsset, EvidenceRequest, ServiceJob
from app.services.service_jobs import access, guidance, notify, revisions
from app.services.service_jobs.access import JobActor

CLOSED_JOB_STATUSES = ("completed", "archived", "cancelled")
STATUS_ORDER = ("outstanding", "answered", "unavailable", "waived")
_PRIORITY_RANK = case((EvidenceRequest.priority == "high", 0), (EvidenceRequest.priority == "normal", 1), else_=2)


def ensure_open(job: ServiceJob) -> None:
    if job.status in CLOSED_JOB_STATUSES:
        raise AppError(409, "job_closed", "This service job is closed", extra={"status": job.status})


def view(r: EvidenceRequest) -> dict:
    return {
        "id": r.id,
        "job_id": r.job_id,
        "requester_role": r.requester_role,
        "organization_id": r.organization_id,
        "category": r.category,
        "component": r.component,
        "prompt": r.prompt,
        "reason": r.reason,
        "measurement_dimension": r.measurement_dimension,
        "priority": r.priority,
        "status": r.status,
        "unavailable_reason": r.unavailable_reason,
        "technician_inspection_required": r.technician_inspection_required,
        "answer_note": r.answer_note,
        "answered_at": r.answered_at,
        "version": r.version,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "options": list(guidance.OPTIONS) if r.status == "outstanding" else [],
    }


def gap(r: EvidenceRequest) -> dict:
    return {
        "request_id": r.id,
        "category": r.category,
        "component": r.component,
        "prompt": r.prompt,
        "reason": r.unavailable_reason,
        "note": r.answer_note,
        "technician_inspection_required": r.technician_inspection_required,
    }


async def all_for_job(db: AsyncSession, job_id: uuid.UUID) -> list[EvidenceRequest]:
    return list(
        (
            await db.execute(
                select(EvidenceRequest)
                .where(EvidenceRequest.job_id == job_id)
                .order_by(_PRIORITY_RANK, EvidenceRequest.created_at, EvidenceRequest.id)
            )
        ).scalars()
    )


def _boundary(vis: access.Visibility | None):
    """SQL form of :meth:`access.Visibility.request` (true for the owner)."""
    if vis is None or vis.unrestricted:
        return true()
    return or_(EvidenceRequest.requester_role != "contractor", EvidenceRequest.organization_id == vis.organization_id)


async def list_for_job(
    db: AsyncSession,
    job_id: uuid.UUID,
    *,
    status: str | None,
    limit: int,
    offset: int,
    vis: access.Visibility | None = None,
) -> list[EvidenceRequest]:
    q = select(EvidenceRequest).where(EvidenceRequest.job_id == job_id, _boundary(vis))
    if status:
        q = q.where(EvidenceRequest.status == status)
    q = q.order_by(_PRIORITY_RANK, EvidenceRequest.created_at, EvidenceRequest.id).limit(limit).offset(offset)
    return list((await db.execute(q)).scalars())


async def available_asset_count(db: AsyncSession, job_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(EvidenceAsset)
                .where(
                    EvidenceAsset.job_id == job_id,
                    EvidenceAsset.status == "available",
                    EvidenceAsset.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )


def visible(requests: list[EvidenceRequest], vis: access.Visibility | None) -> list[EvidenceRequest]:
    """Requests this reader may see (another organization's requests stay with it)."""
    return requests if vis is None else [r for r in requests if vis.request(r)]


async def summary(
    db: AsyncSession, job_id: uuid.UUID, vis: access.Visibility | None = None
) -> tuple[dict, list[dict], bool]:
    """(evidence summary by state, gaps, technician_inspection_required) — the resume view.

    With live updates off this is the brief's evidence: the requests it listed (with their
    live answers — a collaboration channel) plus the reader organization's own requests,
    and the count of the brief's files that are still available."""
    requests = visible(await all_for_job(db, job_id), vis)
    if vis is not None and not vis.live:
        requests = [
            r for r in requests if vis.in_snapshot("requests", r.id) or vis.organization_record(r.organization_id)
        ]
    grouped: dict[str, list[dict]] = {s: [] for s in STATUS_ORDER}
    for r in requests:
        grouped[r.status].append(view(r))
    gaps = [gap(r) for r in requests if r.status == "unavailable"]
    tech = any(r.technician_inspection_required for r in requests)
    if vis is None or vis.unrestricted:
        grouped["available_asset_count"] = await available_asset_count(db, job_id)
    else:
        assets = (
            await db.execute(
                select(EvidenceAsset).where(
                    EvidenceAsset.job_id == job_id,
                    EvidenceAsset.purpose.in_(("job_photo", "job_document")),
                    EvidenceAsset.status == "available",
                    EvidenceAsset.deleted_at.is_(None),
                )
            )
        ).scalars()
        grouped["available_asset_count"] = sum(1 for a in assets if vis.asset(a))
    return grouped, gaps, tech


async def _guidance_context(db: AsyncSession, job: ServiceJob, requests: list[EvidenceRequest]) -> dict:
    assets = (
        await db.execute(
            select(EvidenceAsset.caption, EvidenceAsset.evidence_request_id).where(
                EvidenceAsset.job_id == job.id,
                EvidenceAsset.status == "available",
                EvidenceAsset.deleted_at.is_(None),
            )
        )
    ).all()
    by_id = {r.id: r for r in requests}
    return {
        "affected_system": job.affected_system,
        "affected_equipment": job.affected_equipment,
        "title": job.title,
        "issue_description": job.issue_description,
        "occurs_when": job.occurs_when,
        "vessel_context": job.vessel_context,
        "existing": [
            guidance.ExistingRequest(r.category, r.component, r.status, r.unavailable_reason) for r in requests
        ],
        "asset_captions": [c for c, rid in assets if c and rid is None],
        "asset_request_categories": [by_id[rid].category for _c, rid in assets if rid in by_id],
    }


def _proposal_view(p: guidance.Proposal) -> dict:
    return {
        "key": p.key,
        "category": p.category,
        "component": p.component,
        "prompt": p.prompt,
        "reason": p.reason,
        "priority": p.priority,
        "measurement_dimension": p.measurement_dimension,
        "safety_note": p.safety_note,
        "options": list(p.options),
    }


async def next_for(db: AsyncSession, actor: JobActor) -> dict:
    """The next useful step: an outstanding request first, else a guidance proposal, else complete."""
    job = actor.job
    requests = visible(await all_for_job(db, job.id), await access.visibility(db, actor))
    gaps = [gap(r) for r in requests if r.status == "unavailable"]
    outstanding = [r for r in requests if r.status == "outstanding"]
    if outstanding:
        return {
            "request": view(outstanding[0]),
            "proposal": None,
            "complete": False,
            "message": "Answer this request with a photo, a note, or “I cannot safely get this”.",
            "gaps": gaps,
        }
    proposal = guidance.next_proposal(**await _guidance_context(db, job, requests))
    if proposal is None:
        return {
            "request": None,
            "proposal": None,
            "complete": True,
            "message": (
                "Nothing more to ask right now. You can send the job for contractor review; "
                "anything you could not get is shown to them as a gap."
            ),
            "gaps": gaps,
        }
    return {
        "request": None,
        "proposal": _proposal_view(proposal),
        "complete": False,
        "message": proposal.reason,
        "gaps": gaps,
    }


async def accept_next(db: AsyncSession, actor: JobActor, key: str | None) -> dict:
    """Owner: turn the current proposal into an outstanding ``assistant`` request (idempotent)."""
    actor.require_owner()
    job = actor.job
    ensure_open(job)
    current = await next_for(db, actor)
    if current["request"] is not None or current["complete"]:
        return current
    proposal = current["proposal"]
    if key is not None and key != proposal["key"]:
        raise AppError(409, "proposal_changed", "The suggestion has changed; reload to see the current one")
    r = EvidenceRequest(
        job_id=job.id,
        requested_by=actor.user_id,
        requester_role="assistant",
        category=proposal["category"],
        component=proposal["component"],
        prompt=proposal["prompt"],
        reason=proposal["reason"],
        measurement_dimension=proposal["measurement_dimension"],
        priority=proposal["priority"],
    )
    db.add(r)
    await db.flush()
    await db.refresh(r)
    return {**current, "request": view(r), "proposal": None}


async def create(db: AsyncSession, actor: JobActor, data: dict) -> EvidenceRequest:
    """Owner, or an assigned contractor with ``evidence`` asking for a specific view (SJ-08)."""
    actor.require("evidence")
    job = actor.job
    ensure_open(job)
    for field in ("prompt", "reason", "component"):
        bad = guidance.unsafe_phrases(data.get(field) or "")
        if bad:
            raise AppError(
                422,
                "unsafe_request_wording",
                "Requests must not ask the owner to dismantle, disconnect, open, run or reach into equipment. "
                "Ask for a view from where they can already be, or note that a technician must inspect it.",
                extra={"field": field, "phrases": bad},
            )
    role = "owner" if actor.is_owner else "contractor"
    r = EvidenceRequest(
        job_id=job.id,
        requested_by=actor.user_id,
        requester_role=role,
        organization_id=actor.organization_id,
        category=data["category"],
        component=data.get("component"),
        prompt=data["prompt"],
        reason=data["reason"],
        measurement_dimension=data.get("measurement_dimension"),
        priority=data.get("priority") or ("high" if role == "contractor" else "normal"),
    )
    db.add(r)
    await db.flush()
    await db.refresh(r)
    if role == "contractor":
        await notify.notify(db, job.owner_id, "evidence_requested", job_id=job.id, key=str(r.id))
    return r


async def get_locked(db: AsyncSession, job_id: uuid.UUID, request_id: uuid.UUID) -> EvidenceRequest:
    r = (
        await db.execute(
            select(EvidenceRequest)
            .where(EvidenceRequest.id == request_id, EvidenceRequest.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if r is None:
        raise not_found("Evidence request")
    return r


async def get_one(
    db: AsyncSession, job_id: uuid.UUID, request_id: uuid.UUID, vis: access.Visibility | None = None
) -> EvidenceRequest:
    r = (
        await db.execute(
            select(EvidenceRequest).where(
                EvidenceRequest.id == request_id, EvidenceRequest.job_id == job_id, _boundary(vis)
            )
        )
    ).scalar_one_or_none()
    if r is None:
        raise not_found("Evidence request")
    return r


async def answer(
    db: AsyncSession, actor: JobActor, request_id: uuid.UUID, note: str, expected_version: int | None
) -> EvidenceRequest:
    actor.require_owner()
    ensure_open(actor.job)
    r = await get_locked(db, actor.job.id, request_id)
    access.check_version(r.version, expected_version, "evidence request")
    r.status = "answered"
    r.answer_note = note
    r.unavailable_reason = None
    r.technician_inspection_required = False
    r.answered_by = actor.user_id
    r.answered_at = utcnow()
    r.version += 1
    await revisions.bump(db, actor.job, reason="evidence_answered")
    if r.requester_role == "contractor" and r.requested_by is not None:
        if await access.still_authorized(db, actor.job.id, r.requested_by, None):
            await notify.notify(db, r.requested_by, "evidence_answered", job_id=actor.job.id, key=f"{r.id}:{r.version}")
    await db.flush()
    await db.refresh(r)
    return r


async def mark_unavailable(
    db: AsyncSession,
    actor: JobActor,
    request_id: uuid.UUID,
    reason: str,
    note: str | None,
    expected_version: int | None,
) -> EvidenceRequest:
    """“I cannot safely get this” (and other reasons): a visible gap; never a hazardous follow-up."""
    actor.require_owner()
    ensure_open(actor.job)
    r = await get_locked(db, actor.job.id, request_id)
    access.check_version(r.version, expected_version, "evidence request")
    r.status = "unavailable"
    r.unavailable_reason = reason
    r.technician_inspection_required = reason == "cannot_safely_access"
    r.answer_note = note
    r.answered_by = actor.user_id
    r.answered_at = utcnow()
    r.version += 1
    await db.flush()
    await db.refresh(r)
    return r


async def waive(
    db: AsyncSession, actor: JobActor, request_id: uuid.UUID, note: str | None, expected_version: int | None
) -> EvidenceRequest:
    """Owner waives any request; a contractor may withdraw their own organization's request."""
    actor.require("evidence")
    ensure_open(actor.job)
    r = await get_locked(db, actor.job.id, request_id)
    if not actor.is_owner and (r.requester_role != "contractor" or r.organization_id != actor.organization_id):
        raise AppError(403, "owner_only", "Only the owner can waive this request")
    access.check_version(r.version, expected_version, "evidence request")
    r.status = "waived"
    r.answer_note = note
    r.unavailable_reason = None
    r.technician_inspection_required = False
    r.answered_by = actor.user_id
    r.answered_at = utcnow()
    r.version += 1
    await db.flush()
    await db.refresh(r)
    return r
