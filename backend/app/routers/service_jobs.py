"""Service jobs: create/resume, access details, assignments/grants and evidence requests (workstream A2).

Every endpoint resolves the caller with ``access.job_for`` (owner, or an assigned member of
the accepted assignment limited to granted sections; anyone else 404, an unshared section
403). Mutations lock the job row first and check ``expected_version`` (409 on conflict).
Restricted access values are served only by ``GET /{job_id}/access/restricted`` (audited).
"""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.schemas.service_jobs import (
    AccessGeneralResponse,
    AccessGeneralUpdate,
    AccessRestrictedResponse,
    AccessRestrictedUpdate,
    AssignmentInvite,
    AssignmentResponse,
    AssignmentRevoke,
    AssignmentUpdate,
    EvidenceAnswer,
    EvidenceRequestCreate,
    EvidenceRequestResponse,
    EvidenceStatus,
    EvidenceUnavailable,
    EvidenceWaive,
    JobCreate,
    JobListItem,
    JobResponse,
    JobStatus,
    JobTransition,
    JobUpdate,
    JobVersioned,
    NextEvidence,
    RestrictedAccessUpdate,
    SharingPreview,
    VesselContextCorrection,
)
from app.services.service_jobs import access, assignments, evidence_requests, jobs

router = APIRouter(prefix="/service-jobs", tags=["Service jobs"])

DB = Annotated[AsyncSession, Depends(get_db, scope="function")]
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,100}$")
MUTATE = [Depends(mutation_limit())]


def _idem(key: str | None) -> str:
    if key is None or not IDEMPOTENCY_KEY.match(key):
        raise AppError(
            400,
            "idempotency_key_required",
            "An Idempotency-Key header of 8-100 characters (letters, digits, _ - : .) is required",
        )
    return key


# --- Jobs ---------------------------------------------------------------------------
@router.post("/", response_model=JobResponse, status_code=status.HTTP_201_CREATED, dependencies=MUTATE)
async def create_job(body: JobCreate, user_id: CurrentUserId, db: DB) -> dict:
    """Owner: start a job from one of their vessels (snapshotting its context for correction)."""
    job = await jobs.create(db, user_id, body.model_dump())
    actor = await access.job_for(db, user_id, job.id, owner_only=True)
    return await jobs.view(db, actor)


@router.get("/", response_model=list[JobListItem])
async def list_jobs(
    user_id: CurrentUserId,
    db: DB,
    status_filter: Annotated[JobStatus | None, Query(alias="status")] = None,
    include_archived: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
) -> list[dict]:
    """Owner: my service jobs (contractors use ``/contractors/me/jobs``)."""
    return await jobs.list_own(
        db, user_id, status=status_filter, include_archived=include_archived, limit=limit, offset=offset
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    """Owner or assigned contractor: the job filtered to the caller's sections (resume view)."""
    actor = await access.job_for(db, user_id, job_id)
    return await jobs.view(db, actor)


@router.patch("/{job_id}", response_model=JobResponse, dependencies=MUTATE)
async def update_job(job_id: uuid.UUID, body: JobUpdate, user_id: CurrentUserId, db: DB) -> dict:
    """Owner: edit the job (``expected_version`` required; 409 if someone else changed it)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    changes = body.model_dump(exclude_unset=True)
    expected = changes.pop("expected_version")
    await jobs.update(db, actor, expected, changes)
    return await jobs.view(db, actor)


@router.put("/{job_id}/vessel-context", response_model=JobResponse, dependencies=MUTATE)
async def correct_vessel_context(
    job_id: uuid.UUID, body: VesselContextCorrection, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner: confirm or correct the vessel/equipment snapshot (bumps the evidence revision)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    data = body.model_dump(exclude_unset=True)
    for part in ("vessel", "engine"):
        if part in data and data[part] is not None:
            data[part] = getattr(body, part).model_dump(exclude_unset=True)
    await jobs.correct_vessel_context(db, actor, data)
    return await jobs.view(db, actor)


@router.post("/{job_id}/transition", response_model=JobResponse, dependencies=MUTATE)
async def transition_job(job_id: uuid.UUID, body: JobTransition, user_id: CurrentUserId, db: DB) -> dict:
    """Owner (or the assigned contractor for review/preparation/scheduling steps): change status."""
    actor = await access.job_for(db, user_id, job_id, lock=True)
    await jobs.transition(db, actor, body.expected_version, body.to, body.note)
    return await jobs.view(db, actor)


@router.post("/{job_id}/archive", response_model=JobResponse, dependencies=MUTATE)
async def archive_job(job_id: uuid.UUID, body: JobVersioned, user_id: CurrentUserId, db: DB) -> dict:
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    await jobs.archive(db, actor, body.expected_version)
    return await jobs.view(db, actor)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=MUTATE)
async def delete_job(job_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> None:
    """Owner: delete a job that was never shared (immediate soft delete)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    await jobs.delete_draft(db, actor)


# --- Access details -----------------------------------------------------------------------
def _access_out(d) -> dict:
    return {"job_id": d.job_id, "version": d.version, "updated_at": d.updated_at}


@router.get("/{job_id}/access/general", response_model=AccessGeneralResponse)
async def get_access_general(job_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    """Owner, or an assigned contractor granted ``access_general``."""
    actor = await access.job_for(db, user_id, job_id, section="access_general")
    d = await jobs.get_access(db, actor, "general")
    return {**_access_out(d), "general": d.general}


@router.put("/{job_id}/access/general", response_model=AccessGeneralResponse, dependencies=MUTATE)
async def put_access_general(job_id: uuid.UUID, body: AccessGeneralUpdate, user_id: CurrentUserId, db: DB) -> dict:
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    d = await jobs.put_access(db, actor, "general", body.expected_version, body.general.model_dump())
    return {**_access_out(d), "general": d.general}


@router.get("/{job_id}/access/restricted", response_model=AccessRestrictedResponse)
async def get_access_restricted(job_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    """Owner, or an assigned member granted ``access_restricted`` AND authorised by the owner. Audited."""
    actor = await access.job_for(db, user_id, job_id, section="access_restricted")
    d = await jobs.get_access(db, actor, "restricted")
    return {**_access_out(d), "restricted": d.restricted}


@router.put("/{job_id}/access/restricted", response_model=AccessRestrictedResponse, dependencies=MUTATE)
async def put_access_restricted(
    job_id: uuid.UUID, body: AccessRestrictedUpdate, user_id: CurrentUserId, db: DB
) -> dict:
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    d = await jobs.put_access(db, actor, "restricted", body.expected_version, body.restricted.model_dump())
    return {**_access_out(d), "restricted": d.restricted}


# --- Assignments / grants ---------------------------------------------------------------
@router.get("/{job_id}/assignments", response_model=list[AssignmentResponse])
async def list_assignments(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DB,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
) -> list[dict]:
    """Owner: every assignment of this job (live and past)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True)
    rows = await assignments.list_for_job(db, actor, limit=limit, offset=offset)
    return [await assignments.view(db, a) for a in rows]


@router.post("/{job_id}/assignments/preview", response_model=SharingPreview)
async def preview_assignment(job_id: uuid.UUID, body: AssignmentInvite, user_id: CurrentUserId, db: DB) -> dict:
    """Owner: exactly what this organization would receive (field names and counts only)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True)
    return await assignments.preview(db, actor, body.organization_id, body.sections, body.live_updates)


@router.post(
    "/{job_id}/assignments",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=MUTATE,
    responses={200: {"model": AssignmentResponse, "description": "Existing invitation for this Idempotency-Key"}},
)
async def invite(
    job_id: uuid.UUID,
    body: AssignmentInvite,
    response: Response,
    user_id: CurrentUserId,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """Owner: invite one organization with the chosen sections (one live assignment per job)."""
    key = _idem(idempotency_key)
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    a, created = await assignments.invite(
        db,
        actor,
        organization_id=body.organization_id,
        sections=body.sections,
        live_updates=body.live_updates,
        idempotency_key=key,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return await assignments.view(db, a)


@router.patch("/{job_id}/assignments/{assignment_id}", response_model=AssignmentResponse, dependencies=MUTATE)
async def update_assignment(
    job_id: uuid.UUID, assignment_id: uuid.UUID, body: AssignmentUpdate, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner: change the shared sections or live updates (audited)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    a = await assignments.update_sharing(
        db,
        actor,
        assignment_id,
        expected_version=body.expected_version,
        sections=body.sections,
        live_updates=body.live_updates,
    )
    return await assignments.view(db, a)


@router.put(
    "/{job_id}/assignments/{assignment_id}/members/{member_id}",
    response_model=AssignmentResponse,
    dependencies=MUTATE,
)
async def set_member_restricted_access(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    member_id: uuid.UUID,
    body: RestrictedAccessUpdate,
    user_id: CurrentUserId,
    db: DB,
) -> dict:
    """Owner: authorise (or withdraw) one assigned member's view of access credentials (audited)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    a = await assignments.set_restricted_access(
        db, actor, assignment_id, member_id, body.restricted_access, body.expected_version
    )
    return await assignments.view(db, a)


@router.post("/{job_id}/assignments/{assignment_id}/revoke", response_model=AssignmentResponse, dependencies=MUTATE)
async def revoke_assignment(
    job_id: uuid.UUID, assignment_id: uuid.UUID, body: AssignmentRevoke, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner: revoke immediately; the organization's next request is refused (audited)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    a = await assignments.revoke(db, actor, assignment_id, body.reason)
    return await assignments.view(db, a)


@router.post(
    "/{job_id}/assignments/{assignment_id}/reassign",
    response_model=AssignmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=MUTATE,
)
async def reassign(
    job_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AssignmentInvite,
    response: Response,
    user_id: CurrentUserId,
    db: DB,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict:
    """Owner: revoke this assignment and invite another organization, atomically."""
    key = _idem(idempotency_key)
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    a, created = await assignments.invite(
        db,
        actor,
        organization_id=body.organization_id,
        sections=body.sections,
        live_updates=body.live_updates,
        idempotency_key=key,
        reassigned_from=assignment_id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return await assignments.view(db, a)


# --- Evidence requests --------------------------------------------------------------------
@router.get("/{job_id}/evidence-requests/next", response_model=NextEvidence)
async def next_evidence(job_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    """The next useful step: an outstanding request, else a safe guidance proposal, else complete."""
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    return await evidence_requests.next_for(db, actor)


@router.post("/{job_id}/evidence-requests/next", response_model=NextEvidence, dependencies=MUTATE)
async def accept_next_evidence(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DB,
    key: Annotated[str | None, Query(max_length=200)] = None,
) -> dict:
    """Owner: turn the current proposal into an outstanding request (returns an existing one if any)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    return await evidence_requests.accept_next(db, actor, key)


@router.get("/{job_id}/evidence-requests", response_model=list[EvidenceRequestResponse])
async def list_evidence_requests(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DB,
    status_filter: Annotated[EvidenceStatus | None, Query(alias="status")] = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
) -> list[dict]:
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    rows = await evidence_requests.list_for_job(db, actor.job.id, status=status_filter, limit=limit, offset=offset)
    return [evidence_requests.view(r) for r in rows]


@router.post(
    "/{job_id}/evidence-requests",
    response_model=EvidenceRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=MUTATE,
)
async def create_evidence_request(
    job_id: uuid.UUID, body: EvidenceRequestCreate, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner, or the assigned contractor with ``evidence``: ask for a specific additional view."""
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    r = await evidence_requests.create(db, actor, body.model_dump())
    return evidence_requests.view(r)


@router.get("/{job_id}/evidence-requests/{request_id}", response_model=EvidenceRequestResponse)
async def get_evidence_request(job_id: uuid.UUID, request_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    return evidence_requests.view(await evidence_requests.get_one(db, actor.job.id, request_id))


@router.post(
    "/{job_id}/evidence-requests/{request_id}/answer", response_model=EvidenceRequestResponse, dependencies=MUTATE
)
async def answer_evidence_request(
    job_id: uuid.UUID, request_id: uuid.UUID, body: EvidenceAnswer, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner: answer with a note or a manually typed entry (photo answers come from uploads)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    r = await evidence_requests.answer(db, actor, request_id, body.note, body.expected_version)
    return evidence_requests.view(r)


@router.post(
    "/{job_id}/evidence-requests/{request_id}/unavailable",
    response_model=EvidenceRequestResponse,
    dependencies=MUTATE,
)
async def mark_evidence_unavailable(
    job_id: uuid.UUID, request_id: uuid.UUID, body: EvidenceUnavailable, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner: “I cannot safely get this” (or not visible / not available): a visible gap."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    r = await evidence_requests.mark_unavailable(db, actor, request_id, body.reason, body.note, body.expected_version)
    return evidence_requests.view(r)


@router.post(
    "/{job_id}/evidence-requests/{request_id}/waive", response_model=EvidenceRequestResponse, dependencies=MUTATE
)
async def waive_evidence_request(
    job_id: uuid.UUID, request_id: uuid.UUID, body: EvidenceWaive, user_id: CurrentUserId, db: DB
) -> dict:
    """Owner (any request) or the requesting contractor (their own): no longer needed."""
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    r = await evidence_requests.waive(db, actor, request_id, body.note, body.expected_version)
    return evidence_requests.view(r)
