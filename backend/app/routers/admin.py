"""Administration: role management and audit trail (admin role only)."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import get_db
from app.middleware.auth import AdminUser
from app.models.ops import AuditLog
from app.models.user import User
from app.schemas.user import RoleUpdate, UserResponse
from app.services import audit

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: AdminUser,
    email: str | None = None,
    role: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[User]:
    """Find users by email fragment and/or role."""
    q = select(User).order_by(User.created_at.desc()).limit(limit)
    if email:
        q = q.where(func.lower(User.email).contains(email.lower()))
    if role:
        q = q.where(User.role == role)
    return list((await db.execute(q)).scalars())


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def set_role(
    user_id: uuid.UUID, body: RoleUpdate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> User:
    """Change a user's role. The last remaining admin cannot be demoted."""
    # Lock every admin row (in id order, before the target) so concurrent demotions
    # serialise without deadlocking and at least one admin always remains.
    admin_ids = list(
        (await db.execute(select(User.id).where(User.role == "admin").order_by(User.id).with_for_update())).scalars()
    )
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
    if user is None:
        raise not_found("User")
    if user.role == "admin" and body.role != "admin":
        if len(admin_ids) <= 1:
            raise AppError(409, "last_admin", "Cannot remove the last administrator")
    previous = user.role
    user.role = body.role
    await audit.record(db, admin.id, "set_role", "user", user.id, {"from": previous, "to": body.role})
    await db.flush()
    return user


@router.get("/audit")
async def audit_trail(
    admin: AdminUser,
    entity_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict]:
    """Recent privileged actions."""
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    rows = (await db.execute(q)).scalars()
    return [
        {
            "id": r.id,
            "actor_id": r.actor_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "created_at": r.created_at,
        }
        for r in rows
    ]
