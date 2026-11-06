"""Contractor organizations and verified membership (SJ-D2; spec §3).

Organizations and memberships are provisioned only by a platform administrator (API or
CLI), and every change is audited. Membership is orthogonal to the platform ``users.role``
(no Helm Dash roles, no admin promotion). Removing a membership takes effect on the
member's next request: :mod:`access` checks ``status == 'active'`` every time, and the
member is also taken off every assignment of that organization so re-adding them later
does not silently restore job access.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    ContractorMembership,
    ContractorOrganization,
    JobAssignment,
    JobAssignmentMember,
)
from app.models.user import User
from app.services import audit


async def create_org(
    db: AsyncSession, actor_id: uuid.UUID | None, *, name: str, trading_name: str | None = None, nzbn: str | None = None
) -> ContractorOrganization:
    org = ContractorOrganization(name=name, trading_name=trading_name, nzbn=nzbn, created_by=actor_id)
    db.add(org)
    await db.flush()
    await audit.record(db, actor_id, "contractor_org_create", "contractor_organization", org.id, {"name": name})
    return org


async def get_org(db: AsyncSession, org_id: uuid.UUID, *, lock: bool = False) -> ContractorOrganization:
    q = select(ContractorOrganization).where(ContractorOrganization.id == org_id)
    if lock:
        q = q.with_for_update()
    org = (await db.execute(q)).scalar_one_or_none()
    if org is None:
        raise not_found("Organization")
    return org


async def update_org(
    db: AsyncSession, actor_id: uuid.UUID | None, org_id: uuid.UUID, changes: dict
) -> ContractorOrganization:
    org = await get_org(db, org_id, lock=True)
    before = {k: getattr(org, k) for k in changes}
    for k, v in changes.items():
        setattr(org, k, v)
    await audit.record(
        db, actor_id, "contractor_org_update", "contractor_organization", org.id, {"from": before, "to": changes}
    )
    await db.flush()
    return org


async def list_orgs(db: AsyncSession, *, q: str | None, limit: int, offset: int, active_only: bool):
    stmt = select(ContractorOrganization).order_by(ContractorOrganization.name, ContractorOrganization.id)
    if active_only:
        stmt = stmt.where(ContractorOrganization.status == "active")
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            func.lower(ContractorOrganization.name).like(like)
            | func.lower(func.coalesce(ContractorOrganization.trading_name, "")).like(like)
        )
    return list((await db.execute(stmt.limit(limit).offset(offset))).scalars())


async def user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(func.lower(User.email) == email.strip().lower()))).scalar_one_or_none()


async def add_member(
    db: AsyncSession, actor_id: uuid.UUID | None, org_id: uuid.UUID, user: User, role: str
) -> ContractorMembership:
    """Provision (or re-activate / change the role of) a verified membership. Audited."""
    org = await get_org(db, org_id, lock=True)
    m = (
        await db.execute(
            select(ContractorMembership)
            .where(ContractorMembership.organization_id == org.id, ContractorMembership.user_id == user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    previous = None if m is None else {"role": m.role, "status": m.status}
    now = utcnow()
    if m is None:
        m = ContractorMembership(organization_id=org.id, user_id=user.id)
        db.add(m)
    m.role = role
    m.status = "active"
    m.verified_by = actor_id
    m.verified_at = now
    m.removed_at = None
    await db.flush()
    await audit.record(
        db,
        actor_id,
        "contractor_member_add",
        "contractor_membership",
        m.id,
        {"organization_id": str(org.id), "user_id": str(user.id), "role": role, "previous": previous},
    )
    return m


async def remove_member(
    db: AsyncSession, actor_id: uuid.UUID | None, org_id: uuid.UUID, user_id: uuid.UUID
) -> ContractorMembership:
    """Remove a membership; blocks the member's next request (D23). Audited."""
    await get_org(db, org_id, lock=True)
    m = (
        await db.execute(
            select(ContractorMembership)
            .where(ContractorMembership.organization_id == org_id, ContractorMembership.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if m is None or m.status != "active":
        raise not_found("Membership")
    now = utcnow()
    m.status = "removed"
    m.removed_at = now
    assignment_ids = select(JobAssignment.id).where(JobAssignment.organization_id == org_id)
    taken_off = await db.execute(
        update(JobAssignmentMember)
        .where(
            JobAssignmentMember.user_id == user_id,
            JobAssignmentMember.removed_at.is_(None),
            JobAssignmentMember.assignment_id.in_(assignment_ids),
        )
        .values(removed_at=now, restricted_access=False)
    )
    await audit.record(
        db,
        actor_id,
        "contractor_member_remove",
        "contractor_membership",
        m.id,
        {"organization_id": str(org_id), "user_id": str(user_id), "assignments_left": taken_off.rowcount},
    )
    await db.flush()
    return m


async def members(db: AsyncSession, org_id: uuid.UUID, *, include_removed: bool, limit: int, offset: int):
    stmt = (
        select(ContractorMembership, User)
        .join(User, User.id == ContractorMembership.user_id)
        .where(ContractorMembership.organization_id == org_id)
        .order_by(ContractorMembership.created_at, ContractorMembership.id)
    )
    if not include_removed:
        stmt = stmt.where(ContractorMembership.status == "active")
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    return [
        {
            "user_id": m.user_id,
            "name": u.full_name,
            "email": u.email,
            "role": m.role,
            "status": m.status,
            "verified_at": m.verified_at,
            "removed_at": m.removed_at,
        }
        for m, u in rows
    ]


async def my_memberships(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(ContractorMembership, ContractorOrganization)
            .join(ContractorOrganization, ContractorOrganization.id == ContractorMembership.organization_id)
            .where(
                ContractorMembership.user_id == user_id,
                ContractorMembership.status == "active",
                ContractorOrganization.status == "active",
            )
            .order_by(ContractorOrganization.name)
        )
    ).all()
    return [
        {
            "organization_id": o.id,
            "name": o.name,
            "trading_name": o.trading_name,
            "role": m.role,
            "verified_at": m.verified_at,
        }
        for m, o in rows
    ]


async def admin_org_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(ContractorMembership.organization_id)
                .join(ContractorOrganization, ContractorOrganization.id == ContractorMembership.organization_id)
                .where(
                    ContractorMembership.user_id == user_id,
                    ContractorMembership.status == "active",
                    ContractorMembership.role == "admin",
                    ContractorOrganization.status == "active",
                )
            )
        ).scalars()
    )


async def require_org_admin(db: AsyncSession, user_id: uuid.UUID, org_id: uuid.UUID) -> ContractorMembership:
    """The caller must be an active administrator of an active organization.

    A non-member gets 404 (no existence leak); an ordinary member gets 403."""
    m = (
        await db.execute(
            select(ContractorMembership)
            .join(ContractorOrganization, ContractorOrganization.id == ContractorMembership.organization_id)
            .where(
                ContractorMembership.user_id == user_id,
                ContractorMembership.organization_id == org_id,
                ContractorMembership.status == "active",
                ContractorOrganization.status == "active",
            )
        )
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Organization")
    if m.role != "admin":
        raise AppError(403, "org_admin_only", "Only an administrator of this organization can do this")
    return m
