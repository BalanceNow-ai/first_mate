"""Crew Rewards loyalty programme router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.loyalty import CrewPoints, CrewTeam, CrewTeamMember
from app.schemas.loyalty import (
    CrewPointsResponse,
    CrewTeamCreate,
    CrewTeamMemberResponse,
    CrewTeamResponse,
    PointsMultiplier,
    RedeemPointsRequest,
)

router = APIRouter(prefix="/loyalty", tags=["Crew Rewards"])

# Points multiplier tiers (monthly collective crew spend)
MULTIPLIER_TIERS = [
    {"min_spend": 5000, "multiplier": 3.0},
    {"min_spend": 2000, "multiplier": 2.0},
    {"min_spend": 1000, "multiplier": 1.5},
    {"min_spend": 500, "multiplier": 1.25},
    {"min_spend": 0, "multiplier": 1.0},
]

# Points to NZD conversion rate: 100 CP = $1 NZD
POINTS_TO_NZD_RATE = 100


def _get_multiplier(monthly_spend: float) -> PointsMultiplier:
    """Calculate the points multiplier based on monthly spend."""
    for tier in MULTIPLIER_TIERS:
        if monthly_spend >= tier["min_spend"]:
            return PointsMultiplier(
                monthly_spend=monthly_spend,
                multiplier=tier["multiplier"],
                effective_rate=tier["multiplier"],
            )
    return PointsMultiplier(monthly_spend=monthly_spend, multiplier=1.0, effective_rate=1.0)


@router.get("/points", response_model=CrewPointsResponse)
async def get_points(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> CrewPoints:
    """Get the current user's Crew Points balance and tier."""
    result = await db.execute(select(CrewPoints).where(CrewPoints.user_id == user_id))
    points = result.scalar_one_or_none()
    if not points:
        # Auto-create points record for new users
        points = CrewPoints(user_id=user_id, points_balance=0, tier="deckhand")
        db.add(points)
        await db.flush()
    return points


@router.post("/points/redeem")
async def redeem_points(
    request: RedeemPointsRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Redeem Crew Points for product discounts or experiences.

    Rate: 100 CP = $1 NZD for product discounts.
    Experiences have fixed CP costs defined in the experience catalogue.
    """
    result = await db.execute(select(CrewPoints).where(CrewPoints.user_id == user_id))
    points = result.scalar_one_or_none()
    if not points:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No points balance found",
        )

    if points.points_balance < request.points:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient points. Balance: {points.points_balance}, "
            f"requested: {request.points}",
        )

    if request.redemption_type == "product_discount":
        discount_nzd = request.points / POINTS_TO_NZD_RATE
        points.points_balance -= request.points
        await db.flush()
        return {
            "redeemed_points": request.points,
            "discount_nzd": round(discount_nzd, 2),
            "remaining_balance": points.points_balance,
        }
    elif request.redemption_type == "experience":
        # TODO: Validate against experience catalogue in Strapi
        points.points_balance -= request.points
        await db.flush()
        return {
            "redeemed_points": request.points,
            "experience_id": str(request.experience_id),
            "remaining_balance": points.points_balance,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redemption type. Use 'product_discount' or 'experience'.",
        )


@router.get("/multiplier", response_model=PointsMultiplier)
async def get_current_multiplier(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> PointsMultiplier:
    """Get the current points multiplier for the user's crew.

    The multiplier is based on the collective monthly spend of all
    crew members.
    """
    # TODO: Calculate actual monthly spend from orders
    # For now, return base multiplier
    return _get_multiplier(0.0)


# --- Crew Team Management ---


@router.post("/teams", response_model=CrewTeamResponse, status_code=status.HTTP_201_CREATED)
async def create_crew_team(
    team_data: CrewTeamCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create a new crew team. The creator is automatically added as a member."""
    team = CrewTeam(name=team_data.name, created_by=user_id)
    db.add(team)
    await db.flush()

    # Add creator as a member
    member = CrewTeamMember(team_id=team.id, user_id=user_id)
    db.add(member)
    await db.flush()

    return {
        "id": team.id,
        "name": team.name,
        "created_by": team.created_by,
        "crew_wallet_balance": team.crew_wallet_balance,
        "member_count": 1,
        "created_at": team.created_at,
    }


@router.get("/teams", response_model=list[CrewTeamResponse])
async def list_my_teams(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all crew teams the user belongs to."""
    result = await db.execute(
        select(CrewTeam)
        .join(CrewTeamMember)
        .where(CrewTeamMember.user_id == user_id)
    )
    teams = result.scalars().all()

    team_responses = []
    for team in teams:
        member_count_result = await db.execute(
            select(func.count()).select_from(CrewTeamMember).where(
                CrewTeamMember.team_id == team.id
            )
        )
        member_count = member_count_result.scalar() or 0
        team_responses.append(
            {
                "id": team.id,
                "name": team.name,
                "created_by": team.created_by,
                "crew_wallet_balance": team.crew_wallet_balance,
                "member_count": member_count,
                "created_at": team.created_at,
            }
        )
    return team_responses


@router.post("/teams/{team_id}/members", status_code=status.HTTP_201_CREATED)
async def add_team_member(
    team_id: uuid.UUID,
    member_user_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a member to a crew team (max 10 members)."""
    # Verify team exists and user is the creator
    result = await db.execute(select(CrewTeam).where(CrewTeam.id == team_id))
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if team.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the team creator can add members",
        )

    # Check member limit
    member_count_result = await db.execute(
        select(func.count())
        .select_from(CrewTeamMember)
        .where(CrewTeamMember.team_id == team_id)
    )
    if (member_count_result.scalar() or 0) >= 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Team is full (max 10 members)",
        )

    # Check if already a member
    existing = await db.execute(
        select(CrewTeamMember).where(
            CrewTeamMember.team_id == team_id, CrewTeamMember.user_id == member_user_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this team",
        )

    member = CrewTeamMember(team_id=team_id, user_id=member_user_id)
    db.add(member)
    await db.flush()
    return {"message": "Member added to team"}
