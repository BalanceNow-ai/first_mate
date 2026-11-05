"""Crew Rewards: points, ledger, crews & invites, multiplier, discounts, experiences."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import AdminUser, CurrentPrincipal, CurrentUser
from app.models.loyalty import (
    CrewTeam,
    DiscountEntitlement,
    ExperienceRedemption,
    PointsTransaction,
)
from app.models.user import User
from app.schemas.loyalty import (
    AdminRedemptionOut,
    CrewCreate,
    CrewInviteOut,
    CrewOut,
    DiscountRedeem,
    EntitlementOut,
    ExperienceCatalogue,
    ExperienceRedeem,
    InviteCreate,
    LeaveResult,
    MultiplierProgress,
    MultiplierRun,
    MultiplierRunResult,
    MyInviteOut,
    PointsSummary,
    RedemptionAction,
    RedemptionOut,
    TransactionPage,
)
from app.services import cms, crews, loyalty

router = APIRouter(prefix="/loyalty", tags=["Crew Rewards"])
Db = Annotated[AsyncSession, Depends(get_db, scope="function")]
Mutation = [Depends(mutation_limit())]


# ------------------------------------------------------------------------- points
@router.get("/points", response_model=PointsSummary)
async def get_points(user: CurrentUser, db: Db) -> dict:
    """Own balance, lifetime points, display-only tier and the Crew Wallet aggregate."""
    return await loyalty.points_summary(db, user.id)


@router.get("/transactions", response_model=TransactionPage)
async def list_transactions(
    user: CurrentUser,
    db: Db,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """The user's points ledger, newest first."""
    base = select(PointsTransaction).where(PointsTransaction.user_id == user.id)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    items = (
        (
            await db.execute(
                base.order_by(PointsTransaction.created_at.desc(), PointsTransaction.id).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {"items": list(items), "total": total, "limit": limit, "offset": offset}


@router.get("/multiplier", response_model=MultiplierProgress)
async def get_multiplier(user: CurrentUser, db: Db) -> dict:
    """Current Pacific/Auckland month crew progress (paid orders only)."""
    return await loyalty.multiplier_progress(db, user.id)


# -------------------------------------------------------------------------- crews
@router.get("/crews/mine", response_model=CrewOut)
async def my_crew(user: CurrentUser, db: Db) -> dict:
    return await crews.crew_view(db, user)


@router.post("/crews", response_model=CrewOut, status_code=status.HTTP_201_CREATED, dependencies=Mutation)
async def create_crew(body: CrewCreate, user: CurrentUser, db: Db) -> dict:
    """Create a crew; the creator becomes its captain."""
    await crews.create_crew(db, user, body.name)
    return await crews.crew_view(db, user)


@router.post("/crews/mine/leave", response_model=LeaveResult, dependencies=Mutation)
async def leave_crew(user: CurrentUser, db: Db) -> dict:
    return await crews.leave(db, user)


@router.delete("/crews/mine/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=Mutation)
async def remove_member(member_id: uuid.UUID, user: CurrentUser, db: Db) -> None:
    await crews.remove_member(db, user, member_id)


@router.get("/crews/mine/invites", response_model=list[CrewInviteOut])
async def crew_invites(user: CurrentUser, db: Db) -> list:
    """Pending invites of the captain's crew."""
    return await crews.team_invites(db, user)


@router.post(
    "/crews/mine/invites", response_model=CrewInviteOut, status_code=status.HTTP_201_CREATED, dependencies=Mutation
)
async def invite_member(body: InviteCreate, user: CurrentUser, db: Db):
    return await crews.invite(db, user, str(body.email))


@router.delete("/crews/mine/invites/{invite_id}", response_model=CrewInviteOut, dependencies=Mutation)
async def revoke_invite(invite_id: uuid.UUID, user: CurrentUser, db: Db):
    return await crews.revoke_invite(db, user, invite_id)


async def _my_invite_view(db: AsyncSession, invites) -> list[dict]:
    out = []
    for inv in invites:
        team = await db.get(CrewTeam, inv.team_id)
        inviter = await db.get(User, inv.invited_by)
        out.append(
            {
                "id": inv.id,
                "crew_id": inv.team_id,
                "crew_name": team.name if team else "",
                "invited_by_name": inviter.full_name if inviter else None,
                "status": inv.status,
                "expires_at": inv.expires_at,
                "created_at": inv.created_at,
            }
        )
    return out


@router.get("/invites", response_model=list[MyInviteOut])
async def my_invites(user: CurrentUser, principal: CurrentPrincipal, db: Db) -> list[dict]:
    """Pending invites addressed to the signed-in user's verified email."""
    return await _my_invite_view(db, await crews.my_invites(db, user, principal.email))


@router.post("/invites/{invite_id}/accept", response_model=CrewOut, dependencies=Mutation)
async def accept_invite(invite_id: uuid.UUID, user: CurrentUser, principal: CurrentPrincipal, db: Db) -> dict:
    await crews.accept(db, user, principal.email, invite_id)
    return await crews.crew_view(db, user)


@router.post("/invites/{invite_id}/decline", response_model=MyInviteOut, dependencies=Mutation)
async def decline_invite(invite_id: uuid.UUID, user: CurrentUser, principal: CurrentPrincipal, db: Db) -> dict:
    inv = await crews.decline(db, user, principal.email, invite_id)
    return (await _my_invite_view(db, [inv]))[0]


# ---------------------------------------------------------------------- discounts
@router.post(
    "/redeem/discount", response_model=EntitlementOut, status_code=status.HTTP_201_CREATED, dependencies=Mutation
)
async def redeem_discount(
    body: DiscountRedeem,
    user: CurrentUser,
    db: Db,
    idempotency_key: Annotated[str | None, Header(max_length=200)] = None,
) -> DiscountEntitlement:
    """Spend own points (multiple of 100; 100 CP = $1) for a single-use discount."""
    return await loyalty.redeem_discount(db, user.id, body.points, idempotency_key)


@router.get("/entitlements", response_model=list[EntitlementOut])
async def list_entitlements(user: CurrentUser, db: Db, status_filter: str | None = Query(None, alias="status")) -> list:
    q = select(DiscountEntitlement).where(DiscountEntitlement.user_id == user.id)
    if status_filter:
        q = q.where(DiscountEntitlement.status == status_filter)
    return list((await db.execute(q.order_by(DiscountEntitlement.created_at.desc()))).scalars())


@router.post("/entitlements/{entitlement_id}/void", response_model=EntitlementOut, dependencies=Mutation)
async def void_entitlement(entitlement_id: uuid.UUID, user: CurrentUser, db: Db) -> DiscountEntitlement:
    """Void an unused (issued) discount; its points are restored."""
    return await loyalty.void_entitlement(db, user.id, entitlement_id)


# -------------------------------------------------------------------- experiences
@router.get("/experiences", response_model=ExperienceCatalogue)
async def list_experiences(user: CurrentUser) -> dict:
    """The authoritative Signature Experiences catalogue (no defaults when unavailable)."""
    return (await cms.fetch_experiences()).as_dict()


@router.post(
    "/redeem/experience", response_model=RedemptionOut, status_code=status.HTTP_201_CREATED, dependencies=Mutation
)
async def redeem_experience(body: ExperienceRedeem, user: CurrentUser, db: Db) -> ExperienceRedemption:
    return await loyalty.redeem_experience(db, user.id, body.experience_id, body.note)


@router.get("/redemptions", response_model=list[RedemptionOut])
async def my_redemptions(user: CurrentUser, db: Db) -> list:
    q = (
        select(ExperienceRedemption)
        .where(ExperienceRedemption.user_id == user.id)
        .order_by(ExperienceRedemption.created_at.desc())
    )
    return list((await db.execute(q)).scalars())


# -------------------------------------------------------------------------- admin
@router.get("/admin/redemptions", response_model=list[AdminRedemptionOut])
async def admin_redemptions(
    admin: AdminUser,
    db: Db,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list:
    q = select(ExperienceRedemption).order_by(ExperienceRedemption.created_at).limit(limit)
    if status_filter:
        q = q.where(ExperienceRedemption.status == status_filter)
    return list((await db.execute(q)).scalars())


async def _redemption_action(action: str, redemption_id: uuid.UUID, body: RedemptionAction | None, admin: User, db):
    return await loyalty.update_experience_redemption(
        db, redemption_id, action, admin.id, body.staff_note if body else None
    )


@router.post("/admin/redemptions/{redemption_id}/confirm", response_model=AdminRedemptionOut)
async def confirm_redemption(redemption_id: uuid.UUID, admin: AdminUser, db: Db, body: RedemptionAction | None = None):
    return await _redemption_action("confirm", redemption_id, body, admin, db)


@router.post("/admin/redemptions/{redemption_id}/fulfil", response_model=AdminRedemptionOut)
async def fulfil_redemption(redemption_id: uuid.UUID, admin: AdminUser, db: Db, body: RedemptionAction | None = None):
    return await _redemption_action("fulfil", redemption_id, body, admin, db)


@router.post("/admin/redemptions/{redemption_id}/cancel", response_model=AdminRedemptionOut)
async def cancel_redemption(redemption_id: uuid.UUID, admin: AdminUser, db: Db, body: RedemptionAction | None = None):
    """Cancel a requested/confirmed redemption; the points are restored."""
    return await _redemption_action("cancel", redemption_id, body, admin, db)


@router.post("/admin/multipliers/run", response_model=MultiplierRunResult)
async def run_multipliers(body: MultiplierRun, admin: AdminUser, db: Db) -> dict:
    """Run the monthly multiplier calculation now (idempotent; default previous month)."""
    return await loyalty.calculate_monthly_multipliers(db, body.period)
