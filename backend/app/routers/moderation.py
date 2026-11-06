"""Case-scoped feedback moderation (spec §3, §9.3; SJ-18).

Moderators (``users.role = moderator``, or a platform admin) see the case queue and, per
case, only the reported content and minimal job context. Every view and action is audited.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import require_roles
from app.models.user import User
from app.schemas.service_feedback import CaseDetail, CaseSummary, ModerationActionCreate
from app.services.service_jobs import moderation

router = APIRouter(prefix="/moderation", tags=["Moderation"])

ModeratorUser = Annotated[User, Depends(require_roles("moderator", "admin"))]


@router.get("/cases", response_model=list[CaseSummary])
async def list_cases(
    moderator: ModeratorUser,
    status: Literal["active", "open", "under_review", "resolved", "all"] = "active",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict]:
    return await moderation.list_cases(db, status=status, limit=limit, offset=offset)


@router.get("/cases/{case_id}", response_model=CaseDetail)
async def get_case(
    case_id: uuid.UUID, moderator: ModeratorUser, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    return await moderation.get_case(db, moderator.id, case_id)


@router.post("/cases/{case_id}/actions", response_model=CaseDetail, dependencies=[Depends(mutation_limit())])
async def act_on_case(
    case_id: uuid.UUID,
    body: ModerationActionCreate,
    moderator: ModeratorUser,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """assign | restrict | unrestrict | resolve (with a disposition). Reason required; audited."""
    return await moderation.act(
        db,
        moderator.id,
        case_id,
        action=body.action,
        reason=body.reason,
        disposition=body.disposition,
        assignee_id=body.assignee_id,
    )
