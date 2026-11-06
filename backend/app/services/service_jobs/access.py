"""Server-side authorization for service jobs (SJ-06, SJ-07; decision D23).

Every lookup, download, export, AI tool and action goes through :func:`job_for`. Access
is evaluated on each request from current rows — owner, or an *assigned* member of the
organization holding the job's live, **accepted** assignment, limited to the sections the
owner granted. Knowing an id, belonging to an organization, or being a platform admin
grants nothing (404 — no existence leak). Restricted access details additionally need
the member-level ``restricted_access`` flag the owner set.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.models.service_jobs import (
    JOB_SECTIONS,
    ContractorMembership,
    ContractorOrganization,
    JobAssignment,
    JobAssignmentMember,
    ServiceJob,
)

ALL_SECTIONS = frozenset(JOB_SECTIONS)
LIVE_ASSIGNMENT = ("invited", "accepted")


@dataclass
class JobActor:
    """Who is acting on a job, and what they may see right now."""

    job: ServiceJob
    user_id: uuid.UUID
    role: str  # "owner" | "contractor"
    assignment: JobAssignment | None = None
    organization_id: uuid.UUID | None = None
    member: JobAssignmentMember | None = None
    sections: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    def can(self, section: str) -> bool:
        if section not in ALL_SECTIONS:
            raise ValueError(f"unknown section {section}")
        if self.is_owner:
            return True
        if section not in self.sections:
            return False
        if section == "access_restricted":
            return bool(self.member and self.member.restricted_access)
        return True

    def require(self, section: str) -> JobActor:
        if not self.can(section):
            raise AppError(403, "section_not_shared", "That part of the job has not been shared with you")
        return self

    def require_owner(self) -> JobActor:
        if not self.is_owner:
            raise AppError(403, "owner_only", "Only the job owner can do this")
        return self

    def require_contractor(self) -> JobActor:
        if self.role != "contractor":
            raise AppError(403, "contractor_only", "Only the assigned contractor can do this")
        return self


async def active_membership(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID
) -> ContractorMembership | None:
    return (
        await db.execute(
            select(ContractorMembership)
            .join(ContractorOrganization, ContractorOrganization.id == ContractorMembership.organization_id)
            .where(
                ContractorMembership.user_id == user_id,
                ContractorMembership.organization_id == organization_id,
                ContractorMembership.status == "active",
                ContractorOrganization.status == "active",
            )
        )
    ).scalar_one_or_none()


async def live_assignment(db: AsyncSession, job_id: uuid.UUID, *, lock: bool = False) -> JobAssignment | None:
    q = select(JobAssignment).where(JobAssignment.job_id == job_id, JobAssignment.status.in_(LIVE_ASSIGNMENT))
    if lock:
        q = q.with_for_update()
    return (await db.execute(q)).scalar_one_or_none()


async def assigned_member(db: AsyncSession, assignment_id: uuid.UUID, user_id: uuid.UUID) -> JobAssignmentMember | None:
    return (
        await db.execute(
            select(JobAssignmentMember).where(
                JobAssignmentMember.assignment_id == assignment_id,
                JobAssignmentMember.user_id == user_id,
                JobAssignmentMember.removed_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _load_job(db: AsyncSession, job_id: uuid.UUID, lock: bool) -> ServiceJob | None:
    q = select(ServiceJob).where(ServiceJob.id == job_id, ServiceJob.deleted_at.is_(None))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(q)).scalar_one_or_none()


async def job_for(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    section: str | None = None,
    owner_only: bool = False,
    lock: bool = False,
) -> JobActor:
    """Resolve the actor's current access to a job, or raise 404/403.

    ``lock`` takes the job row FOR UPDATE (the job row is the per-job serialisation
    point; D22 extension: lock the job before any of its child rows)."""
    job = await _load_job(db, job_id, lock)
    if job is None:
        raise not_found("Service job")
    if job.owner_id == user_id:
        actor = JobActor(job=job, user_id=user_id, role="owner", sections=ALL_SECTIONS)
    else:
        if owner_only:
            raise not_found("Service job")
        actor = await _contractor_actor(db, job, user_id)
        if actor is None:
            raise not_found("Service job")
    if owner_only:
        actor.require_owner()
    if section is not None:
        actor.require(section)
    return actor


async def _contractor_actor(db: AsyncSession, job: ServiceJob, user_id: uuid.UUID) -> JobActor | None:
    assignment = await live_assignment(db, job.id)
    if assignment is None or assignment.status != "accepted":
        return None
    if await active_membership(db, user_id, assignment.organization_id) is None:
        return None
    member = await assigned_member(db, assignment.id, user_id)
    if member is None:
        return None
    return JobActor(
        job=job,
        user_id=user_id,
        role="contractor",
        assignment=assignment,
        organization_id=assignment.organization_id,
        member=member,
        sections=frozenset(assignment.sections or []) & ALL_SECTIONS,
    )


async def still_authorized(
    db: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID, assignment_id: uuid.UUID | None
) -> bool:
    """Recheck, at publication time, that the requester still has the access the work was
    started under (owner, or the same accepted assignment with the member still assigned)."""
    job = await _load_job(db, job_id, lock=False)
    if job is None:
        return False
    if job.owner_id == user_id:
        return True
    actor = await _contractor_actor(db, job, user_id)
    return actor is not None and (assignment_id is None or actor.assignment.id == assignment_id)


def check_version(current: int, expected: int | None, what: str = "job") -> None:
    """Optimistic concurrency: a stale ``expected_version`` is a 409, never a silent overwrite."""
    if expected is not None and expected != current:
        raise AppError(
            409,
            "version_conflict",
            f"This {what} was changed by someone else; reload and try again",
            extra={"current_version": current},
        )
