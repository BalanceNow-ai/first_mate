"""Contractor organizations, verified membership and the assigned-job inbox (workstream A2).

* Platform administrators provision organizations and memberships (audited; also via CLI).
* Any signed-in user may search the directory — a directory entry grants nothing.
* ``/me`` and ``/me/jobs``: my memberships; jobs I am assigned to on an accepted
  assignment, plus pending invitations for organizations I administer.
* Organization administrators see a minimal invitation summary, accept/decline, and choose
  which members work an accepted assignment. They never see job content unless assigned.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import AdminUser, CurrentUser, CurrentUserId
from app.schemas.service_jobs import (
    AssignmentAccept,
    AssignmentMemberAdd,
    ContractorInbox,
    DirectoryEntry,
    InvitationSummary,
    MemberResponse,
    MembershipCreate,
    MyMembership,
    OrganizationCreate,
    OrganizationResponse,
    OrganizationUpdate,
)
from app.services.service_jobs import assignments, organizations

router = APIRouter(prefix="/contractors", tags=["Contractor organizations"])

DB = Annotated[AsyncSession, Depends(get_db, scope="function")]
MUTATE = [Depends(mutation_limit())]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0, le=100_000)]


# --- Platform administration ------------------------------------------------------------
@router.post(
    "/organizations", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED, dependencies=MUTATE
)
async def create_organization(body: OrganizationCreate, admin: AdminUser, db: DB):
    """Platform admin: provision a contractor organization (audited)."""
    return await organizations.create_org(db, admin.id, **body.model_dump())


@router.get("/organizations", response_model=list[OrganizationResponse])
async def list_organizations(
    admin: AdminUser,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    """Platform admin: every organization (any status)."""
    return await organizations.list_orgs(db, q=q, limit=limit, offset=offset, active_only=False)


@router.patch("/organizations/{org_id}", response_model=OrganizationResponse, dependencies=MUTATE)
async def update_organization(org_id: uuid.UUID, body: OrganizationUpdate, admin: AdminUser, db: DB):
    """Platform admin: rename or suspend an organization (suspension blocks its members' next request)."""
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    return await organizations.update_org(db, admin.id, org_id, changes)


@router.get("/organizations/{org_id}/members", response_model=list[MemberResponse])
async def list_members(
    org_id: uuid.UUID,
    user: CurrentUser,
    db: DB,
    include_removed: bool = False,
    limit: Limit = 100,
    offset: Offset = 0,
):
    """Platform admin, or an administrator of this organization."""
    if user.role == "admin":
        await organizations.get_org(db, org_id)
    else:
        await organizations.require_org_admin(db, user.id, org_id)
    return await organizations.members(db, org_id, include_removed=include_removed, limit=limit, offset=offset)


@router.post(
    "/organizations/{org_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=MUTATE,
)
async def add_member(org_id: uuid.UUID, body: MembershipCreate, admin: AdminUser, db: DB) -> dict:
    """Platform admin: provision a verified membership for a signed-up user (audited)."""
    user = await organizations.user_by_email(db, body.email)
    if user is None:
        raise AppError(404, "user_not_found", "No signed-up user has that email address")
    m = await organizations.add_member(db, admin.id, org_id, user, body.role)
    return {
        "user_id": m.user_id,
        "name": user.full_name,
        "email": user.email,
        "role": m.role,
        "status": m.status,
        "verified_at": m.verified_at,
        "removed_at": m.removed_at,
    }


@router.delete(
    "/organizations/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=MUTATE
)
async def remove_member(org_id: uuid.UUID, member_id: uuid.UUID, admin: AdminUser, db: DB) -> None:
    """Platform admin: remove a membership; takes effect on the member's next request (audited)."""
    await organizations.remove_member(db, admin.id, org_id, member_id)


# --- Directory and me ------------------------------------------------------------------------
@router.get("/directory", response_model=list[DirectoryEntry])
async def directory(
    user_id: CurrentUserId,
    db: DB,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 20,
    offset: Offset = 0,
):
    """Active organizations an owner can invite. Being listed grants no access to anything."""
    return await organizations.list_orgs(db, q=q, limit=limit, offset=offset, active_only=True)


@router.get("/me", response_model=list[MyMembership])
async def my_organizations(user_id: CurrentUserId, db: DB) -> list[dict]:
    """My active memberships and roles."""
    return await organizations.my_memberships(db, user_id)


@router.get("/me/jobs", response_model=ContractorInbox)
async def my_jobs(user_id: CurrentUserId, db: DB, limit: Limit = 50, offset: Offset = 0) -> dict:
    """Jobs I am assigned to (accepted assignments), plus pending invitations if I am an org admin."""
    return await assignments.inbox(db, user_id, limit=limit, offset=offset)


# --- Organization administrators ------------------------------------------------------------
@router.get("/organizations/{org_id}/invitations", response_model=list[InvitationSummary])
async def org_invitations(
    org_id: uuid.UUID,
    user_id: CurrentUserId,
    db: DB,
    status_filter: Annotated[
        Literal["invited", "accepted", "declined", "revoked"] | None, Query(alias="status")
    ] = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[dict]:
    """Org admin: this organization's invitations/assignments as a minimal summary."""
    return await assignments.invitations_for_org(db, user_id, org_id, status=status_filter, limit=limit, offset=offset)


@router.get("/assignments/{assignment_id}", response_model=InvitationSummary)
async def get_invitation(assignment_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    return await assignments.invitation(db, user_id, assignment_id)


@router.post("/assignments/{assignment_id}/accept", response_model=InvitationSummary, dependencies=MUTATE)
async def accept_invitation(assignment_id: uuid.UUID, body: AssignmentAccept, user_id: CurrentUserId, db: DB) -> dict:
    """Org admin: accept, optionally choosing the members who will work the job."""
    a, job = await assignments.accept(db, user_id, assignment_id, body.member_user_ids)
    return await assignments.invitation_view(db, a, job)


@router.post("/assignments/{assignment_id}/decline", response_model=InvitationSummary, dependencies=MUTATE)
async def decline_invitation(assignment_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    a, job = await assignments.decline(db, user_id, assignment_id)
    return await assignments.invitation_view(db, a, job)


@router.post("/assignments/{assignment_id}/members", response_model=InvitationSummary, dependencies=MUTATE)
async def assign_member(assignment_id: uuid.UUID, body: AssignmentMemberAdd, user_id: CurrentUserId, db: DB) -> dict:
    """Org admin: put a member of the organization on an accepted assignment."""
    a, job = await assignments.add_assignment_member(db, user_id, assignment_id, body.user_id)
    return await assignments.invitation_view(db, a, job)


@router.delete(
    "/assignments/{assignment_id}/members/{member_id}", response_model=InvitationSummary, dependencies=MUTATE
)
async def unassign_member(assignment_id: uuid.UUID, member_id: uuid.UUID, user_id: CurrentUserId, db: DB) -> dict:
    """Org admin: take a member off the assignment (their next request is refused)."""
    a, job = await assignments.remove_assignment_member(db, user_id, assignment_id, member_id)
    return await assignments.invitation_view(db, a, job)
