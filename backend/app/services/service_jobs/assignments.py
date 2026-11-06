"""Assignments: explicit owner grants of sections to one contractor organization (SJ-06, SJ-07).

Owner: preview exactly what an organization would receive → invite (``Idempotency-Key``;
at most one live assignment per job, enforced by a partial unique index) → change sections
/ live updates → authorise individual members for restricted access → revoke (immediate)
or reassign (revoke + new invite in one transaction). Organization administrator: see a
minimal invitation summary, accept/decline, choose the members who work the job. An org
administrator never sees job content unless also assigned. Every sharing change is audited.

Lock order: the job row (``access.job_for(lock=True)`` or :func:`_lock_job`) before the
assignment row, before member rows.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.ops import AuditLog
from app.models.service_jobs import (
    JOB_SECTIONS,
    ContractorMembership,
    ContractorOrganization,
    EvidenceAsset,
    EvidenceRequest,
    Invoice,
    JobAccessDetails,
    JobAssignment,
    JobAssignmentMember,
    Measurement,
    PreparationBrief,
    PreparationItem,
    ScopeRevision,
    ServiceJob,
)
from app.models.user import User
from app.services import audit
from app.services.service_jobs import access, notify, organizations
from app.services.service_jobs.access import JobActor

INVITE_ACTION = "service_job_invite"
CLOSED_FOR_SHARING = ("completed", "archived", "cancelled")

SECTION_LABELS = {
    "summary": "Problem summary and vessel details",
    "evidence": "Photos, documents and evidence requests",
    "measurements": "Measurements",
    "preparation": "Preparation list and briefs",
    "access_general": "General access and logistics",
    "access_restricted": "Access credentials and exact location",
    "scope": "Scope of work and decisions",
    "invoices": "Invoice questions you choose to share",
}
SUMMARY_FIELDS = [
    "title",
    "issue_description",
    "affected_system",
    "affected_equipment",
    "occurs_when",
    "already_tried",
    "urgency",
    "vessel_context",
]


def ordered_sections(sections) -> list[str]:
    s = set(sections or [])
    return [x for x in JOB_SECTIONS if x in s]


def first_name(full_name: str | None) -> str | None:
    if not full_name or not full_name.strip():
        return None
    return full_name.strip().split()[0]


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _members(db: AsyncSession, assignment_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(JobAssignmentMember, User.full_name)
            .join(User, User.id == JobAssignmentMember.user_id)
            .where(JobAssignmentMember.assignment_id == assignment_id, JobAssignmentMember.removed_at.is_(None))
            .order_by(JobAssignmentMember.created_at, JobAssignmentMember.id)
        )
    ).all()
    return [
        {"user_id": m.user_id, "name": name, "restricted_access": m.restricted_access, "added_at": m.created_at}
        for m, name in rows
    ]


async def view(db: AsyncSession, a: JobAssignment) -> dict:
    org = await db.get(ContractorOrganization, a.organization_id)
    return {
        "id": a.id,
        "job_id": a.job_id,
        "organization": {"id": org.id, "name": org.name, "trading_name": org.trading_name},
        "status": a.status,
        "sections": ordered_sections(a.sections),
        "live_updates": a.live_updates,
        "invited_at": a.created_at,
        "accepted_at": a.accepted_at,
        "revoked_at": a.revoked_at,
        "version": a.version,
        "members": await _members(db, a.id),
    }


NEUTRAL_JOB_LABEL = "Service job"


def offered_title(a: JobAssignment, job: ServiceJob) -> str:
    """The job title only when the owner offered the summary section; otherwise a neutral label."""
    return job.title if "summary" in (a.sections or []) else NEUTRAL_JOB_LABEL


async def invitation_view(db: AsyncSession, a: JobAssignment, job: ServiceJob) -> dict:
    """Minimal summary for an org administrator: no evidence, no access details, and no job
    details beyond what the offered summary section allows."""
    inviter = await db.get(User, a.invited_by)
    summary = "summary" in (a.sections or [])
    vessel = ((job.vessel_context or {}).get("vessel") or {}) if summary else {}
    return {
        "assignment_id": a.id,
        "job_id": a.job_id,
        "organization_id": a.organization_id,
        "status": a.status,
        "job_title": offered_title(a, job),
        "vessel_make": vessel.get("make"),
        "vessel_model": vessel.get("model"),
        "sections": ordered_sections(a.sections),
        "live_updates": a.live_updates,
        "inviter_first_name": first_name(inviter.full_name if inviter else None),
        "invited_at": a.created_at,
        "accepted_at": a.accepted_at,
        "version": a.version,
        "members": await _members(db, a.id) if a.status == "accepted" else [],
    }


async def _active_org(db: AsyncSession, org_id: uuid.UUID) -> ContractorOrganization:
    org = await db.get(ContractorOrganization, org_id)
    if org is None or org.status != "active":
        raise not_found("Organization")
    return org


async def _count(db: AsyncSession, model, *where) -> int:
    return int((await db.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


COLLABORATION_NOTE = (
    "Evidence requests and your answers, scope proposals and your decisions, visits and any invoice "
    "question you choose to send stay up to date either way."
)


def live_updates_note(live_updates: bool) -> str:
    """What the contractor will actually read (enforced by ``access.visibility``)."""
    if live_updates:
        return "They will see the sections you share as they are now, including changes you make later. " + (
            COLLABORATION_NOTE
        )
    return (
        "They will see the job — its summary, photos and documents, observations, measurements and "
        "preparation items — as of the brief you publish, not later changes, unless you turn on live updates. "
        "Until you publish a brief they see only the job's title and status. " + COLLABORATION_NOTE
    )


# --- Owner side ------------------------------------------------------------------------
async def preview(db: AsyncSession, actor: JobActor, org_id: uuid.UUID, sections: list[str], live_updates: bool):
    """Exactly what the organization would receive — field names and counts, never values."""
    actor.require_owner()
    org = await _active_org(db, org_id)
    job = actor.job
    details = await db.get(JobAccessDetails, job.id)
    general = sorted(k for k, v in ((details.general if details else {}) or {}).items() if v not in (None, ""))
    restricted = sorted(k for k, v in ((details.restricted if details else {}) or {}).items() if v not in (None, ""))
    out = []
    for s in ordered_sections(sections):
        exposes: list[str]
        counts: dict[str, int] = {}
        note = None
        if s == "summary":
            exposes = SUMMARY_FIELDS
        elif s == "evidence":
            exposes = ["evidence requests and answers", "photos and documents (metadata-stripped copies)"]
            counts = {
                "evidence_requests": await _count(db, EvidenceRequest, EvidenceRequest.job_id == job.id),
                "available_assets": await _count(
                    db,
                    EvidenceAsset,
                    EvidenceAsset.job_id == job.id,
                    EvidenceAsset.status == "available",
                    EvidenceAsset.deleted_at.is_(None),
                ),
            }
        elif s == "measurements":
            exposes = ["measurements with their method and source"]
            counts = {"measurements": await _count(db, Measurement, Measurement.job_id == job.id)}
        elif s == "preparation":
            exposes = ["preparation items", "published briefs"]
            counts = {
                "preparation_items": await _count(db, PreparationItem, PreparationItem.job_id == job.id),
                "published_briefs": await _count(
                    db, PreparationBrief, PreparationBrief.job_id == job.id, PreparationBrief.status == "published"
                ),
            }
        elif s == "access_general":
            exposes = general
            counts = {"fields": len(general)}
        elif s == "access_restricted":
            exposes = restricted
            counts = {"fields": len(restricted)}
            note = "Shown only to the assigned members you individually authorise, on a separate audited screen."
        elif s == "scope":
            exposes = ["scope revisions and your decisions"]
            counts = {"scope_revisions": await _count(db, ScopeRevision, ScopeRevision.job_id == job.id)}
        else:  # invoices
            exposes = ["invoice questions and documents you explicitly share"]
            counts = {"linked_invoices": await _count(db, Invoice, Invoice.job_id == job.id)}
            note = "Nothing from an invoice is shared until you share a specific question."
        out.append({"section": s, "label": SECTION_LABELS[s], "exposes": exposes, "counts": counts, "note": note})
    return {
        "organization": {"id": org.id, "name": org.name, "trading_name": org.trading_name},
        "sections": out,
        "withheld": [s for s in JOB_SECTIONS if s not in set(sections)],
        "live_updates": live_updates,
        "live_updates_note": live_updates_note(live_updates),
    }


async def _replayed(db: AsyncSession, actor: JobActor, key: str, request_digest: str) -> JobAssignment | None:
    prior = (
        await db.execute(
            select(AuditLog)
            .where(
                AuditLog.actor_id == actor.user_id,
                AuditLog.action == INVITE_ACTION,
                AuditLog.detail["job_id"].astext == str(actor.job.id),
                AuditLog.detail["idempotency_key"].astext == key,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if prior is None:
        return None
    if prior.detail.get("request_digest") != request_digest:
        raise AppError(
            409, "idempotency_key_conflict", "This Idempotency-Key was already used for a different invitation"
        )
    return await db.get(JobAssignment, uuid.UUID(prior.detail["assignment_id"]))


async def invite(
    db: AsyncSession,
    actor: JobActor,
    *,
    organization_id: uuid.UUID,
    sections: list[str],
    live_updates: bool,
    idempotency_key: str,
    reassigned_from: uuid.UUID | None = None,
) -> tuple[JobAssignment, bool]:
    """Create the job's one live invitation. Returns (assignment, created). The job row is locked."""
    actor.require_owner()
    job = actor.job
    request_digest = _digest(
        {
            "organization_id": str(organization_id),
            "sections": ordered_sections(sections),
            "live_updates": live_updates,
            "reassigned_from": str(reassigned_from) if reassigned_from else None,
        }
    )
    existing = await _replayed(db, actor, idempotency_key, request_digest)
    if existing is not None:
        return existing, False
    if job.status in CLOSED_FOR_SHARING:
        raise AppError(409, "job_closed", "This service job is closed", extra={"status": job.status})
    await _active_org(db, organization_id)
    if reassigned_from is not None:
        await _revoke(db, actor, reassigned_from, reason="reassigned")
    if await access.live_assignment(db, job.id) is not None:
        raise AppError(409, "assignment_exists", "This job already has a live contractor assignment")
    a = JobAssignment(
        job_id=job.id,
        organization_id=organization_id,
        status="invited",
        sections=ordered_sections(sections),
        live_updates=live_updates,
        invited_by=actor.user_id,
    )
    try:
        async with db.begin_nested():
            db.add(a)
            await db.flush()
    except IntegrityError:
        raise AppError(409, "assignment_exists", "This job already has a live contractor assignment") from None
    await audit.record(
        db,
        actor.user_id,
        INVITE_ACTION,
        "service_job_assignment",
        a.id,
        {
            "job_id": str(job.id),
            "assignment_id": str(a.id),
            "organization_id": str(organization_id),
            "sections": a.sections,
            "live_updates": live_updates,
            "idempotency_key": idempotency_key,
            "request_digest": request_digest,
            "reassigned_from": str(reassigned_from) if reassigned_from else None,
        },
    )
    for admin_id in await _org_admin_ids(db, organization_id):
        await notify.notify(db, admin_id, "assignment_invited", job_id=job.id, key=f"{a.id}:{admin_id}")
    await db.flush()
    await db.refresh(a)
    return a, True


async def _org_admin_ids(db: AsyncSession, org_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(ContractorMembership.user_id).where(
                    ContractorMembership.organization_id == org_id,
                    ContractorMembership.status == "active",
                    ContractorMembership.role == "admin",
                )
            )
        ).scalars()
    )


async def _locked_assignment(db: AsyncSession, job_id: uuid.UUID, assignment_id: uuid.UUID) -> JobAssignment:
    a = (
        await db.execute(
            select(JobAssignment)
            .where(JobAssignment.id == assignment_id, JobAssignment.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if a is None:
        raise not_found("Assignment")
    return a


async def list_for_job(db: AsyncSession, actor: JobActor, *, limit: int, offset: int) -> list[JobAssignment]:
    actor.require_owner()
    return list(
        (
            await db.execute(
                select(JobAssignment)
                .where(JobAssignment.job_id == actor.job.id)
                .order_by(JobAssignment.created_at.desc(), JobAssignment.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
    )


async def update_sharing(
    db: AsyncSession,
    actor: JobActor,
    assignment_id: uuid.UUID,
    *,
    expected_version: int,
    sections: list[str] | None,
    live_updates: bool | None,
) -> JobAssignment:
    actor.require_owner()
    a = await _locked_assignment(db, actor.job.id, assignment_id)
    if a.status not in access.LIVE_ASSIGNMENT:
        raise AppError(409, "assignment_not_live", "This assignment is no longer live")
    access.check_version(a.version, expected_version, "assignment")
    before = {"sections": ordered_sections(a.sections), "live_updates": a.live_updates}
    if sections is not None:
        a.sections = ordered_sections(sections)
    if live_updates is not None:
        a.live_updates = live_updates
    a.version += 1
    await audit.record(
        db,
        actor.user_id,
        "service_job_sharing_change",
        "service_job_assignment",
        a.id,
        {
            "job_id": str(actor.job.id),
            "from": before,
            "to": {"sections": ordered_sections(a.sections), "live_updates": a.live_updates},
        },
    )
    await db.flush()
    await db.refresh(a)
    return a


async def set_restricted_access(
    db: AsyncSession,
    actor: JobActor,
    assignment_id: uuid.UUID,
    user_id: uuid.UUID,
    restricted_access: bool,
    expected_version: int | None,
) -> JobAssignment:
    """The owner authorises (or withdraws) one assigned member's view of access credentials."""
    actor.require_owner()
    a = await _locked_assignment(db, actor.job.id, assignment_id)
    if a.status != "accepted":
        raise AppError(409, "assignment_not_accepted", "The organization has not accepted this job")
    access.check_version(a.version, expected_version, "assignment")
    m = (
        await db.execute(
            select(JobAssignmentMember)
            .where(
                JobAssignmentMember.assignment_id == a.id,
                JobAssignmentMember.user_id == user_id,
                JobAssignmentMember.removed_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Assigned member")
    previous = m.restricted_access
    m.restricted_access = restricted_access
    a.version += 1
    await audit.record(
        db,
        actor.user_id,
        "service_job_restricted_access",
        "service_job_assignment",
        a.id,
        {"job_id": str(actor.job.id), "user_id": str(user_id), "from": previous, "to": restricted_access},
    )
    await db.flush()
    await db.refresh(a)
    return a


async def _revoke(db: AsyncSession, actor: JobActor, assignment_id: uuid.UUID, *, reason: str | None) -> JobAssignment:
    a = await _locked_assignment(db, actor.job.id, assignment_id)
    if a.status not in access.LIVE_ASSIGNMENT:
        raise AppError(409, "assignment_not_live", "This assignment is no longer live")
    previous = a.status
    a.status = "revoked"
    a.revoked_at = utcnow()
    a.version += 1
    await db.flush()
    await audit.record(
        db,
        actor.user_id,
        "service_job_revoke",
        "service_job_assignment",
        a.id,
        {"job_id": str(actor.job.id), "from": previous, "reason": reason},
    )
    return a


async def revoke(db: AsyncSession, actor: JobActor, assignment_id: uuid.UUID, reason: str | None) -> JobAssignment:
    """Immediate: the next request by any member of that organization is refused (D23)."""
    actor.require_owner()
    a = await _revoke(db, actor, assignment_id, reason=reason)
    await db.refresh(a)
    return a


# --- Organization administrator side --------------------------------------------------------
async def _lock_job(db: AsyncSession, job_id: uuid.UUID) -> ServiceJob:
    job = (
        await db.execute(
            select(ServiceJob)
            .where(ServiceJob.id == job_id, ServiceJob.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None:
        raise not_found("Assignment")
    return job


async def _admin_assignment(
    db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID, *, lock: bool
) -> tuple[JobAssignment, ServiceJob]:
    """An assignment of an organization the caller administers (404 otherwise), job locked first."""
    a = await db.get(JobAssignment, assignment_id)
    if a is None:
        raise not_found("Assignment")
    try:
        await organizations.require_org_admin(db, user_id, a.organization_id)
    except AppError as e:
        if e.status_code == 404:
            raise not_found("Assignment") from None
        raise
    if not lock:
        job = await db.get(ServiceJob, a.job_id)
        if job is None or job.deleted_at is not None:
            raise not_found("Assignment")
        return a, job
    job = await _lock_job(db, a.job_id)
    a = await _locked_assignment(db, job.id, assignment_id)
    return a, job


async def invitations_for_org(
    db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID, *, status: str | None, limit: int, offset: int
) -> list[dict]:
    await organizations.require_org_admin(db, user_id, org_id)
    q = (
        select(JobAssignment, ServiceJob)
        .join(ServiceJob, ServiceJob.id == JobAssignment.job_id)
        .where(JobAssignment.organization_id == org_id, ServiceJob.deleted_at.is_(None))
        .order_by(JobAssignment.created_at.desc(), JobAssignment.id)
    )
    if status:
        q = q.where(JobAssignment.status == status)
    rows = (await db.execute(q.limit(limit).offset(offset))).all()
    return [await invitation_view(db, a, job) for a, job in rows]


async def invitation(db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID) -> dict:
    a, job = await _admin_assignment(db, user_id, assignment_id, lock=False)
    return await invitation_view(db, a, job)


async def _check_members(db: AsyncSession, org_id: uuid.UUID, user_ids: list[uuid.UUID]) -> None:
    for uid in user_ids:
        if await access.active_membership(db, uid, org_id) is None:
            raise AppError(422, "not_an_active_member", "Only active members of the organization can be assigned")


async def _add_member(db: AsyncSession, a: JobAssignment, user_id: uuid.UUID, added_by: uuid.UUID) -> None:
    m = (
        await db.execute(
            select(JobAssignmentMember)
            .where(JobAssignmentMember.assignment_id == a.id, JobAssignmentMember.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if m is None:
        db.add(JobAssignmentMember(assignment_id=a.id, user_id=user_id, restricted_access=False, added_by=added_by))
    elif m.removed_at is not None:
        # Re-adding never restores an earlier restricted-access authorisation.
        m.removed_at = None
        m.restricted_access = False
        m.added_by = added_by


async def accept(
    db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID, member_user_ids: list[uuid.UUID]
) -> tuple[JobAssignment, ServiceJob]:
    a, job = await _admin_assignment(db, user_id, assignment_id, lock=True)
    if a.status != "invited":
        raise AppError(409, "invitation_not_pending", "This invitation is not pending", extra={"status": a.status})
    if job.status in CLOSED_FOR_SHARING:
        raise AppError(409, "job_closed", "This service job is closed", extra={"status": job.status})
    await _check_members(db, a.organization_id, member_user_ids)
    a.status = "accepted"
    a.accepted_by = user_id
    a.accepted_at = utcnow()
    a.version += 1
    for uid in dict.fromkeys(member_user_ids):
        await _add_member(db, a, uid, user_id)
    await db.flush()
    await audit.record(
        db,
        user_id,
        "service_job_assignment_accept",
        "service_job_assignment",
        a.id,
        {"job_id": str(job.id), "members": [str(u) for u in member_user_ids]},
    )
    await notify.notify(db, job.owner_id, "assignment_accepted", job_id=job.id, key=str(a.id))
    await db.refresh(a)
    return a, job


async def decline(db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID) -> tuple[JobAssignment, ServiceJob]:
    a, job = await _admin_assignment(db, user_id, assignment_id, lock=True)
    if a.status != "invited":
        raise AppError(409, "invitation_not_pending", "This invitation is not pending", extra={"status": a.status})
    a.status = "declined"
    a.version += 1
    await db.flush()
    await audit.record(
        db, user_id, "service_job_assignment_decline", "service_job_assignment", a.id, {"job_id": str(job.id)}
    )
    await db.refresh(a)
    return a, job


async def add_assignment_member(
    db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID, member_id: uuid.UUID
) -> tuple[JobAssignment, ServiceJob]:
    a, job = await _admin_assignment(db, user_id, assignment_id, lock=True)
    if a.status != "accepted":
        raise AppError(409, "assignment_not_accepted", "Accept the invitation before assigning members")
    await _check_members(db, a.organization_id, [member_id])
    await _add_member(db, a, member_id, user_id)
    a.version += 1
    await db.flush()
    await audit.record(
        db,
        user_id,
        "service_job_member_assign",
        "service_job_assignment",
        a.id,
        {"job_id": str(job.id), "user_id": str(member_id)},
    )
    await db.refresh(a)
    return a, job


async def remove_assignment_member(
    db: AsyncSession, user_id: uuid.UUID, assignment_id: uuid.UUID, member_id: uuid.UUID
) -> tuple[JobAssignment, ServiceJob]:
    a, job = await _admin_assignment(db, user_id, assignment_id, lock=True)
    m = (
        await db.execute(
            select(JobAssignmentMember)
            .where(
                JobAssignmentMember.assignment_id == a.id,
                JobAssignmentMember.user_id == member_id,
                JobAssignmentMember.removed_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Assigned member")
    m.removed_at = utcnow()
    m.restricted_access = False
    a.version += 1
    await db.flush()
    await audit.record(
        db,
        user_id,
        "service_job_member_unassign",
        "service_job_assignment",
        a.id,
        {"job_id": str(job.id), "user_id": str(member_id)},
    )
    await db.refresh(a)
    return a, job


async def inbox(db: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int) -> dict:
    """Jobs I am assigned to on an accepted assignment (+ pending invitations for orgs I administer)."""
    rows = (
        await db.execute(
            select(JobAssignment, ServiceJob, ContractorOrganization, JobAssignmentMember)
            .join(ServiceJob, ServiceJob.id == JobAssignment.job_id)
            .join(ContractorOrganization, ContractorOrganization.id == JobAssignment.organization_id)
            .join(JobAssignmentMember, JobAssignmentMember.assignment_id == JobAssignment.id)
            .join(
                ContractorMembership,
                (ContractorMembership.organization_id == JobAssignment.organization_id)
                & (ContractorMembership.user_id == JobAssignmentMember.user_id),
            )
            .where(
                JobAssignmentMember.user_id == user_id,
                JobAssignmentMember.removed_at.is_(None),
                JobAssignment.status == "accepted",
                ContractorMembership.status == "active",
                ContractorOrganization.status == "active",
                ServiceJob.deleted_at.is_(None),
            )
            .order_by(ServiceJob.updated_at.desc(), ServiceJob.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    assigned = [
        {
            "job_id": job.id,
            "title": offered_title(a, job),
            "status": job.status,
            "assignment_id": a.id,
            "organization_id": org.id,
            "organization_name": org.name,
            "sections": ordered_sections(a.sections),
            "restricted_access": bool(m.restricted_access and "access_restricted" in (a.sections or [])),
            "accepted_at": a.accepted_at,
            "updated_at": job.updated_at,
        }
        for a, job, org, m in rows
    ]
    invitations: list[dict] = []
    admin_orgs = await organizations.admin_org_ids(db, user_id)
    if admin_orgs:
        inv = (
            await db.execute(
                select(JobAssignment, ServiceJob)
                .join(ServiceJob, ServiceJob.id == JobAssignment.job_id)
                .where(
                    JobAssignment.organization_id.in_(admin_orgs),
                    JobAssignment.status == "invited",
                    ServiceJob.deleted_at.is_(None),
                )
                .order_by(JobAssignment.created_at.desc(), JobAssignment.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        invitations = [await invitation_view(db, a, job) for a, job in inv]
    return {"assigned": assigned, "invitations": invitations}
