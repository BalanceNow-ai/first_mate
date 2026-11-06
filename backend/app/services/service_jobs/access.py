"""Server-side authorization for service jobs (SJ-06, SJ-07; decision D23).

Every lookup, download, export, AI tool and action goes through :func:`job_for`. Access
is evaluated on each request from current rows — owner, or an *assigned* member of the
organization holding the job's live, **accepted** assignment, limited to the sections the
owner granted. Knowing an id, belonging to an organization, or being a platform admin
grants nothing (404 — no existence leak). Restricted access details additionally need
the member-level ``restricted_access`` flag the owner set.

Which job *content* a contractor reads is decided in one place, :func:`visibility`:

* **Organization boundary** (after a reassignment): records another contractor
  organization authored — its uploads, notes/observations, preparation items, evidence
  requests and their answers, scope revisions/decisions, acknowledgements — are not shown
  to the newly assigned organization. Owner/assistant-authored evidence stays (it is the
  owner's job evidence); measurements another organization recorded or confirmed stay
  visible as evidence, without that organization's member identities.
* **Live updates** (``JobAssignment.live_updates``): on, the granted sections are read
  live. Off (the default), job content — summary, photos/documents, observations,
  measurements, preparation items — is read only as of the latest brief published for
  the assignment (plus what the organization itself recorded). Collaboration channels stay
  live: evidence requests and their answers, scope proposals/decisions, visits, feedback
  and explicitly shared invoice questions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.models.service_jobs import (
    JOB_SECTIONS,
    AnalysisRun,
    ContractorMembership,
    ContractorOrganization,
    JobAssignment,
    JobAssignmentMember,
    PreparationBrief,
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
    _visibility: Visibility | None = field(default=None, repr=False)

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


# ---------------------------------------------------------------------- content visibility
SNAPSHOT_KINDS = ("assets", "observations", "requests", "measurements", "items")
NOT_SHARED_CODE = "live_updates_not_shared"
NOT_SHARED_MESSAGE = (
    "The owner shares this job as of the published brief and this record is not in it. "
    "Ask the owner to publish a new brief or to turn on live updates."
)
SNAPSHOT_CONTENT_SECTIONS = ("summary", "evidence", "access_general", "measurements", "preparation", "scope")


def _snapshot_ids(content: dict) -> dict[str, frozenset[str]]:
    evidence = content.get("evidence") or {}
    measurements = content.get("measurements") or {}
    preparation = content.get("preparation") or {}
    return {
        "assets": frozenset(str(a.get("id")) for a in evidence.get("assets") or []),
        "observations": frozenset(str(o.get("id")) for o in evidence.get("observations") or []),
        "requests": frozenset(str(r.get("id")) for r in evidence.get("requests") or []),
        "measurements": frozenset(str(m.get("id")) for m in measurements.get("current") or []),
        "items": frozenset(str(i.get("id")) for i in preparation.get("items") or []),
    }


def filtered_snapshot(content: dict, actor: JobActor) -> dict:
    """A brief snapshot reduced to the sections the actor holds now (a withdrawn section is hidden)."""
    if actor.is_owner:
        return content
    out = {k: v for k, v in content.items() if k not in SNAPSHOT_CONTENT_SECTIONS}
    allowed = [s for s in content.get("sections", []) if actor.can(s)]
    out["sections"] = allowed
    for s in allowed:
        if s in content:
            out[s] = content[s]
    return out


@dataclass
class Visibility:
    """What one reader may see of a job's content right now — the single rule (see module doc).

    ``organization_id`` None means unrestricted (the owner). With live updates off,
    ``brief``/``snapshot``/``ids`` hold the latest brief published for the assignment
    (``ids`` is empty-but-set when none is published yet: see :attr:`state`)."""

    job: ServiceJob
    organization_id: uuid.UUID | None = None
    member_ids: frozenset[uuid.UUID] = frozenset()  # users this organization ever assigned to the job
    run_ids: frozenset[uuid.UUID] = frozenset()  # analysis runs those users requested
    live: bool = True
    brief: PreparationBrief | None = None
    snapshot: dict | None = None
    ids: dict[str, frozenset[str]] | None = None  # record ids in the snapshot (None: read live)

    @property
    def unrestricted(self) -> bool:
        return self.organization_id is None

    @property
    def state(self) -> str:
        """``live`` | ``brief`` | ``no_brief_published``."""
        if self.live:
            return "live"
        return "brief" if self.brief is not None else "no_brief_published"

    # -- authorship ------------------------------------------------------------------
    def own(self, user_id: uuid.UUID | None) -> bool:
        """Recorded by a member of this organization (now or formerly assigned to this job)."""
        return user_id is not None and user_id in self.member_ids

    def other_contractor(self, user_id: uuid.UUID | None) -> bool:
        """Recorded by someone who is neither the owner nor a member of this organization."""
        return (
            not self.unrestricted
            and user_id is not None
            and user_id != self.job.owner_id
            and user_id not in self.member_ids
        )

    def in_snapshot(self, kind: str, record_id) -> bool:
        return self.ids is None or str(record_id) in self.ids.get(kind, frozenset())

    # -- per record ------------------------------------------------------------------
    def asset(self, a) -> bool:
        if self.unrestricted:
            return True
        if self.other_contractor(a.uploaded_by):
            return False
        return self.own(a.uploaded_by) or self.in_snapshot("assets", a.id)

    def observation(self, o, *, asset_visible: bool = True) -> bool:
        if self.unrestricted:
            return True
        if not asset_visible:
            return False
        if o.analysis_run_id is not None:  # assistant output on the owner's evidence
            return o.analysis_run_id in self.run_ids or self.in_snapshot("observations", o.id)
        if self.other_contractor(o.recorded_by):
            return False
        return self.own(o.recorded_by) or self.in_snapshot("observations", o.id)

    def measurement(self, m) -> bool:
        if self.unrestricted:
            return True
        return self.own(m.recorded_by) or self.in_snapshot("measurements", m.id)

    def foreign_people(self, *user_ids: uuid.UUID | None) -> bool:
        """Any of these people belongs to another organization (identities are withheld)."""
        return any(self.other_contractor(u) for u in user_ids)

    def item(self, i) -> bool:
        if self.unrestricted:
            return True
        if i.origin == "contractor" and self.other_contractor(i.created_by):
            return False
        return self.own(i.created_by) or self.in_snapshot("items", i.id)

    def request(self, r) -> bool:
        """Evidence requests are a live collaboration channel, within the organization boundary."""
        if self.unrestricted:
            return True
        return not (r.requester_role == "contractor" and r.organization_id != self.organization_id)

    def organization_record(self, organization_id: uuid.UUID | None) -> bool:
        """Scope revisions/decisions, acknowledgements: only the reader's own organization's."""
        return self.unrestricted or organization_id == self.organization_id

    def require(self, kind: str, record) -> None:
        """Refuse a contractor action on a record outside what they may read (403)."""
        check = {
            "assets": self.asset,
            "observations": self.observation,
            "measurements": self.measurement,
            "items": self.item,
        }[kind]
        if not check(record):
            raise AppError(403, NOT_SHARED_CODE, NOT_SHARED_MESSAGE)


async def organization_visibility(db: AsyncSession, job: ServiceJob, organization_id: uuid.UUID) -> Visibility:
    """The organization boundary alone (read live) — e.g. what a brief for that organization may hold."""
    member_ids = frozenset(
        (
            await db.execute(
                select(JobAssignmentMember.user_id)
                .join(JobAssignment, JobAssignment.id == JobAssignmentMember.assignment_id)
                .where(JobAssignment.job_id == job.id, JobAssignment.organization_id == organization_id)
            )
        ).scalars()
    )
    run_ids: frozenset[uuid.UUID] = frozenset()
    if member_ids:
        run_ids = frozenset(
            (
                await db.execute(
                    select(AnalysisRun.id).where(AnalysisRun.job_id == job.id, AnalysisRun.requested_by.in_(member_ids))
                )
            ).scalars()
        )
    return Visibility(job=job, organization_id=organization_id, member_ids=member_ids, run_ids=run_ids)


async def latest_published_brief(db: AsyncSession, assignment: JobAssignment) -> PreparationBrief | None:
    """The brief currently shared with this assignment (published, made for it), if any."""
    if assignment.shared_brief_id is None:
        return None
    brief = (
        await db.execute(
            select(PreparationBrief).where(
                PreparationBrief.id == assignment.shared_brief_id,
                PreparationBrief.job_id == assignment.job_id,
                PreparationBrief.status == "published",
            )
        )
    ).scalar_one_or_none()
    if brief is None or ((brief.content or {}).get("recipient") or {}).get("assignment_id") != str(assignment.id):
        return None
    return brief


async def visibility(db: AsyncSession, actor: JobActor) -> Visibility:
    """What this actor reads of the job's content now (computed once per request)."""
    if actor._visibility is not None:
        return actor._visibility
    if actor.is_owner:
        vis = Visibility(job=actor.job)
    else:
        vis = await organization_visibility(db, actor.job, actor.organization_id)
        if not actor.assignment.live_updates:
            vis.live = False
            brief = await latest_published_brief(db, actor.assignment)
            if brief is not None:
                vis.brief = brief
                vis.snapshot = filtered_snapshot(brief.content or {}, actor)
                vis.ids = _snapshot_ids(vis.snapshot)
            else:
                vis.ids = {k: frozenset() for k in SNAPSHOT_KINDS}
    actor._visibility = vis
    return vis


def check_version(current: int, expected: int | None, what: str = "job") -> None:
    """Optimistic concurrency: a stale ``expected_version`` is a 409, never a silent overwrite."""
    if expected is not None and expected != current:
        raise AppError(
            409,
            "version_conflict",
            f"This {what} was changed by someone else; reload and try again",
            extra={"current_version": current},
        )
