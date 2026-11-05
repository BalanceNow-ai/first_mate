"""Append-only audit log for privileged actions."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ops import AuditLog


async def record(
    db: AsyncSession,
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: object | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            detail=detail,
        )
    )
