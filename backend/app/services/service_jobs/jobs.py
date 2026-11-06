"""Owner service jobs: create from a vessel, resume, edit, transitions, delete/archive (SJ-01, SJ-21).

* Creation snapshots the owner's own vessel record (identity, primary engine, usable
  equipment) into ``vessel_context``; the owner corrects it explicitly, which bumps the
  evidence revision (stale analysis/confirmations are invalidated by ``revisions.bump``).
* The job representation is filtered by the actor's sections (§3): contractors see only
  what was granted; restricted access values never appear in it.
* Every mutation locks the job row first and checks ``expected_version`` (409).
* Transitions here: draft → evidence_collection → contractor_review → preparation_ready →
  scheduled (and the matching step-backs), plus cancel. attended/completed are recorded
  by visits; archive and delete have their own operations.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    JOB_SECTIONS,
    EvidenceRequest,
    JobAccessDetails,
    JobAssignment,
    ServiceJob,
)
from app.models.vessel import Vessel
from app.services import audit, fitment
from app.services.service_jobs import access, assignments, evidence_requests, revisions
from app.services.service_jobs.access import JobActor

CLOSED = ("completed", "archived", "cancelled")
PRE_ATTENDANCE = ("draft", "evidence_collection", "contractor_review", "preparation_ready", "scheduled")
# (from, to) -> who may make it
TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("draft", "evidence_collection"): frozenset({"owner"}),
    ("evidence_collection", "contractor_review"): frozenset({"owner"}),
    ("contractor_review", "evidence_collection"): frozenset({"owner", "contractor"}),
    ("contractor_review", "preparation_ready"): frozenset({"owner", "contractor"}),
    ("preparation_ready", "contractor_review"): frozenset({"owner", "contractor"}),
    ("preparation_ready", "scheduled"): frozenset({"owner", "contractor"}),
    ("scheduled", "preparation_ready"): frozenset({"owner", "contractor"}),
    **{(s, "cancelled"): frozenset({"owner"}) for s in PRE_ATTENDANCE},
}
SUMMARY_FIELDS = (
    "issue_description",
    "affected_system",
    "affected_equipment",
    "occurs_when",
    "already_tried",
    "urgency",
    "vessel_context",
)
CONTEXT_FIELDS = ("affected_system", "affected_equipment", "issue_description")


def ensure_editable(job: ServiceJob) -> None:
    if job.status in CLOSED:
        raise AppError(409, "job_closed", "This service job is closed", extra={"status": job.status})


async def snapshot_vessel(db: AsyncSession, vessel: Vessel) -> dict:
    """The vessel/equipment context the owner confirms or corrects (no HIN or serials)."""
    profile = await fitment.load_vessel_profile(db, vessel)
    equipment = [
        {
            "category": f.category,
            "make": f.make,
            "model": f.model,
            "year": f.year,
            "provenance": f.provenance,
            "confidence": str(f.confidence),
        }
        for f in profile.facts
        if f.provenance != "vessel_record"
    ]
    return {
        "source": "vessel_record",
        "captured_at": utcnow().isoformat(),
        "vessel": {
            "nickname": vessel.nickname,
            "make": vessel.make,
            "model": vessel.model,
            "year": vessel.year,
            "hull_type": vessel.hull_type,
            "propulsion_type": vessel.propulsion_type,
            "length_ft": float(vessel.length_ft) if vessel.length_ft is not None else None,
        },
        "engine": (
            {"make": vessel.engine_make, "model": vessel.engine_model, "year": vessel.engine_year}
            if vessel.engine_make
            else None
        ),
        "equipment": equipment,
        "uncertain_categories": sorted(profile.uncertain_categories),
        "owner_confirmed": False,
        "corrections": [],
    }


async def create(db: AsyncSession, owner_id: uuid.UUID, data: dict) -> ServiceJob:
    vessel = (
        await db.execute(select(Vessel).where(Vessel.id == data["vessel_id"], Vessel.user_id == owner_id))
    ).scalar_one_or_none()
    if vessel is None:
        raise not_found("Vessel")
    job = ServiceJob(owner_id=owner_id, status="draft", vessel_context=await snapshot_vessel(db, vessel), **data)
    db.add(job)
    await db.flush()
    db.add(JobAccessDetails(job_id=job.id, general={}, restricted={}))
    await db.flush()
    await db.refresh(job)
    return job


async def update(db: AsyncSession, actor: JobActor, expected_version: int, changes: dict) -> ServiceJob:
    actor.require_owner()
    job = actor.job
    access.check_version(job.version, expected_version)
    ensure_editable(job)
    if "title" in changes and changes["title"] is None:
        changes.pop("title")
    if "urgency" in changes and changes["urgency"] is None:
        changes.pop("urgency")
    if "issue_description" in changes and changes["issue_description"] is None:
        changes["issue_description"] = ""
    context_changed = any(k in changes and getattr(job, k) != changes[k] for k in CONTEXT_FIELDS)
    for k, v in changes.items():
        setattr(job, k, v)
    job.version += 1
    if context_changed:
        await revisions.bump(db, job, reason="job_context_changed")
    await db.flush()
    await db.refresh(job)
    return job


async def correct_vessel_context(db: AsyncSession, actor: JobActor, body: dict) -> ServiceJob:
    """Explicit owner correction/confirmation of the vessel snapshot; bumps the evidence revision."""
    actor.require_owner()
    job = actor.job
    access.check_version(job.version, body["expected_version"])
    ensure_editable(job)
    ctx = dict(job.vessel_context or {})
    changed: list[str] = []
    for part in ("vessel", "engine"):
        upd = body.get(part)
        if upd is None:
            continue
        current = dict(ctx.get(part) or {})
        for k, v in upd.items():
            if current.get(k) != v:
                changed.append(f"{part}.{k}")
            current[k] = v
        ctx[part] = current
    if body.get("equipment") is not None:
        ctx["equipment"] = [{**e, "provenance": "owner_corrected"} for e in body["equipment"]]
        changed.append("equipment")
    ctx["owner_confirmed"] = True
    ctx["corrections"] = [
        *(ctx.get("corrections") or []),
        {"at": utcnow().isoformat(), "by": "owner", "fields": changed, "note": body.get("note")},
    ]
    job.vessel_context = ctx
    job.version += 1
    await revisions.bump(db, job, reason="vessel_context_corrected")
    await db.flush()
    await db.refresh(job)
    return job


async def transition(db: AsyncSession, actor: JobActor, expected_version: int, to: str, note: str | None):
    job = actor.job
    access.check_version(job.version, expected_version)
    allowed = TRANSITIONS.get((job.status, to))
    if allowed is None:
        raise AppError(
            409,
            "invalid_transition",
            f"A job cannot move from {job.status} to {to}",
            extra={"from": job.status, "to": to},
        )
    if actor.role not in allowed:
        raise AppError(403, "owner_only" if allowed == {"owner"} else "forbidden", "You cannot make this change")
    if not actor.is_owner:
        actor.require("preparation")
    if to == "scheduled":
        live = await access.live_assignment(db, job.id)
        if live is None or live.status != "accepted":
            raise AppError(409, "no_accepted_assignment", "A contractor must accept the job before it is scheduled")
    previous = job.status
    job.status = to
    job.version += 1
    if to == "cancelled":
        # A pending invitation for a cancelled job is withdrawn; an accepted one is kept as the
        # participation record (visits/feedback decide what follows).
        pending = await access.live_assignment(db, job.id, lock=True)
        if pending is not None and pending.status == "invited":
            pending.status = "revoked"
            pending.revoked_at = utcnow()
            pending.version += 1
            await audit.record(
                db,
                actor.user_id,
                "service_job_revoke",
                "service_job_assignment",
                pending.id,
                {"job_id": str(job.id), "from": "invited", "reason": "job_cancelled"},
            )
    await audit.record(
        db,
        actor.user_id,
        "service_job_transition",
        "service_job",
        job.id,
        {"from": previous, "to": to, "role": actor.role, "note": note},
    )
    await db.flush()
    await db.refresh(job)
    return job


async def delete_draft(db: AsyncSession, actor: JobActor) -> None:
    """Owners delete an unshared job immediately (soft delete). Shared jobs are archived instead."""
    actor.require_owner()
    job = actor.job
    shared = (
        await db.execute(select(func.count()).select_from(JobAssignment).where(JobAssignment.job_id == job.id))
    ).scalar_one()
    if shared or job.retention_hold or job.status not in ("draft", "evidence_collection", "cancelled"):
        raise AppError(
            409, "job_shared", "This job has been shared or is past preparation; archive it instead of deleting it"
        )
    job.deleted_at = utcnow()
    job.version += 1
    await audit.record(db, actor.user_id, "service_job_delete", "service_job", job.id, {"status": job.status})
    await db.flush()


async def archive(db: AsyncSession, actor: JobActor, expected_version: int) -> ServiceJob:
    actor.require_owner()
    job = actor.job
    access.check_version(job.version, expected_version)
    if job.status == "archived":
        return job
    live = await access.live_assignment(db, job.id)
    if job.status not in ("completed", "cancelled") and live is not None:
        raise AppError(409, "job_active", "Cancel the job or revoke the contractor's assignment before archiving it")
    if job.status == "attended":
        raise AppError(409, "job_active", "Record completion before archiving this job")
    previous = job.status
    job.status = "archived"
    job.archived_at = utcnow()
    job.version += 1
    await audit.record(db, actor.user_id, "service_job_archive", "service_job", job.id, {"from": previous})
    await db.flush()
    await db.refresh(job)
    return job


async def list_own(
    db: AsyncSession, owner_id: uuid.UUID, *, status: str | None, include_archived: bool, limit: int, offset: int
) -> list[dict]:
    outstanding = (
        select(func.count())
        .where(EvidenceRequest.job_id == ServiceJob.id, EvidenceRequest.status == "outstanding")
        .correlate(ServiceJob)
        .scalar_subquery()
    )
    gaps = (
        select(func.count())
        .where(EvidenceRequest.job_id == ServiceJob.id, EvidenceRequest.status == "unavailable")
        .correlate(ServiceJob)
        .scalar_subquery()
    )
    live = (
        select(JobAssignment.status)
        .where(JobAssignment.job_id == ServiceJob.id, JobAssignment.status.in_(access.LIVE_ASSIGNMENT))
        .correlate(ServiceJob)
        .limit(1)
        .scalar_subquery()
    )
    q = select(ServiceJob, outstanding, gaps, live).where(
        ServiceJob.owner_id == owner_id, ServiceJob.deleted_at.is_(None)
    )
    if status:
        q = q.where(ServiceJob.status == status)
    elif not include_archived:
        q = q.where(ServiceJob.status != "archived")
    q = q.order_by(ServiceJob.updated_at.desc(), ServiceJob.id).limit(limit).offset(offset)
    return [
        {
            "id": j.id,
            "vessel_id": j.vessel_id,
            "title": j.title,
            "status": j.status,
            "urgency": j.urgency,
            "version": j.version,
            "outstanding_requests": o,
            "gap_count": g,
            "assignment_status": a,
            "created_at": j.created_at,
            "updated_at": j.updated_at,
        }
        for j, o, g, a in (await db.execute(q)).all()
    ]


async def view(db: AsyncSession, actor: JobActor) -> dict:
    """The job as this actor may see it — everything needed to resume (SJ-01)."""
    job = actor.job
    out: dict = {
        "id": job.id,
        "vessel_id": job.vessel_id,
        "entry_point": job.entry_point,
        "title": job.title,
        "status": job.status,
        "version": job.version,
        "evidence_revision": job.evidence_revision,
        "disputed": job.disputed,
        "archived_at": job.archived_at,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "viewer": {
            "role": actor.role,
            "sections": [s for s in JOB_SECTIONS if actor.can(s)] if not actor.is_owner else list(JOB_SECTIONS),
            "organization_id": actor.organization_id,
            "assignment_id": actor.assignment.id if actor.assignment else None,
            "restricted_access": actor.can("access_restricted"),
        },
    }
    if actor.can("summary"):
        for k in SUMMARY_FIELDS:
            out[k] = getattr(job, k)
    if actor.can("evidence"):
        grouped, gaps, tech = await evidence_requests.summary(db, job.id)
        out["evidence"] = grouped
        out["gaps"] = gaps
        out["technician_inspection_required"] = tech
    assignment = actor.assignment if not actor.is_owner else await access.live_assignment(db, job.id)
    out["assignment"] = await assignments.view(db, assignment) if assignment is not None else None
    return out


# --- Access details (§7.1) ---------------------------------------------------------------
async def _details(db: AsyncSession, job_id: uuid.UUID, *, lock: bool) -> JobAccessDetails:
    q = select(JobAccessDetails).where(JobAccessDetails.job_id == job_id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    d = (await db.execute(q)).scalar_one_or_none()
    if d is None:
        d = JobAccessDetails(job_id=job_id, general={}, restricted={})
        db.add(d)
        await db.flush()
        await db.refresh(d)
    return d


async def get_access(db: AsyncSession, actor: JobActor, part: str) -> JobAccessDetails:
    """``part`` is "general" or "restricted"; restricted reads are audited (never the values)."""
    actor.require("access_general" if part == "general" else "access_restricted")
    d = await _details(db, actor.job.id, lock=False)
    if part == "restricted":
        await audit.record(
            db,
            actor.user_id,
            "service_job_access_restricted_read",
            "service_job",
            actor.job.id,
            {
                "role": actor.role,
                "organization_id": str(actor.organization_id) if actor.organization_id else None,
                "assignment_id": str(actor.assignment.id) if actor.assignment else None,
                "fields": sorted(k for k, v in (d.restricted or {}).items() if v not in (None, "")),
            },
        )
    return d


async def put_access(db: AsyncSession, actor: JobActor, part: str, expected_version: int, values: dict):
    actor.require_owner()
    ensure_editable(actor.job)
    d = await _details(db, actor.job.id, lock=True)
    access.check_version(d.version, expected_version, "access details")
    clean = {k: v for k, v in values.items() if v not in (None, "")}
    if part == "general":
        d.general = clean
    else:
        d.restricted = clean
        await audit.record(
            db,
            actor.user_id,
            "service_job_access_restricted_update",
            "service_job",
            actor.job.id,
            {"fields": sorted(clean)},
        )
    d.version += 1
    await db.flush()
    await db.refresh(d)
    return d
