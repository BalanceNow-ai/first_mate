"""Crew Rewards loyalty programme router."""

import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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
    SignatureExperience,
)

logger = logging.getLogger(__name__)

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

# Default experiences returned when Strapi is unavailable
DEFAULT_EXPERIENCES = [
    SignatureExperience(
        id="exp-harbour-cruise",
        title="Harbour Cruise",
        description="A guided harbour cruise around Auckland's Waitematā Harbour",
        cost_cp=5000,
        location="Auckland Harbour",
        duration_hours=3.0,
    ),
    SignatureExperience(
        id="exp-fishing-charter",
        title="Fishing Charter",
        description="Full-day deep-sea fishing charter in the Hauraki Gulf",
        cost_cp=15000,
        location="Hauraki Gulf",
        duration_hours=8.0,
    ),
    SignatureExperience(
        id="exp-marine-detailing",
        title="Marine Detailing",
        description="Professional hull and topside detail for vessels up to 30ft",
        cost_cp=8000,
        location="Westhaven Marina",
        duration_hours=4.0,
    ),
]


async def _fetch_experiences_from_strapi() -> list[SignatureExperience]:
    """Fetch signature experiences from Strapi CMS.

    Falls back to DEFAULT_EXPERIENCES if Strapi is unavailable.
    """
    settings = get_settings()
    if not settings.strapi_url or not settings.strapi_api_token:
        return DEFAULT_EXPERIENCES

    headers = {"Authorization": f"Bearer {settings.strapi_api_token}"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                f"{settings.strapi_url}/api/signature-experiences",
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            experiences = []
            for item in data.get("data", []):
                attrs = item.get("attributes", item)
                experiences.append(
                    SignatureExperience(
                        id=str(item.get("id", attrs.get("id", ""))),
                        title=attrs.get("title", ""),
                        description=attrs.get("description", ""),
                        cost_cp=attrs.get("cost_cp", 0),
                        image_url=attrs.get("image_url"),
                        location=attrs.get("location"),
                        duration_hours=attrs.get("duration_hours"),
                        available=attrs.get("available", True),
                    )
                )
            return experiences if experiences else DEFAULT_EXPERIENCES
    except Exception as exc:
        logger.warning("Failed to fetch experiences from Strapi: %s", exc)
        return DEFAULT_EXPERIENCES


async def _fetch_experience_by_id(experience_id: str) -> SignatureExperience | None:
    """Fetch a single experience by ID from Strapi (or fallback list)."""
    experiences = await _fetch_experiences_from_strapi()
    for exp in experiences:
        if exp.id == experience_id:
            return exp
    return None


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


@router.get("/experiences", response_model=list[SignatureExperience])
async def get_experiences() -> list[SignatureExperience]:
    """Get available Signature Experiences from Strapi CMS.

    Returns cached default list if the Strapi service is unavailable.
    """
    return await _fetch_experiences_from_strapi()


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
        if not request.experience_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="experience_id is required for experience redemptions",
            )

        # Validate against Strapi experience catalogue
        experience = await _fetch_experience_by_id(str(request.experience_id))
        if not experience:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Experience '{request.experience_id}' not found",
            )
        if not experience.available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Experience '{experience.title}' is currently unavailable",
            )
        if points.points_balance < experience.cost_cp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Insufficient points for '{experience.title}'. "
                f"Requires: {experience.cost_cp}, balance: {points.points_balance}",
            )

        points.points_balance -= experience.cost_cp
        await db.flush()
        return {
            "redeemed_points": experience.cost_cp,
            "experience_id": experience.id,
            "experience_title": experience.title,
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
    crew members in the current calendar month.
    """
    from datetime import datetime
    from app.models.order import Order

    # Find the user's crew team(s) — use the first team found
    team_result = await db.execute(
        select(CrewTeam)
        .join(CrewTeamMember)
        .where(CrewTeamMember.user_id == user_id)
    )
    team = team_result.scalar_one_or_none()

    if not team:
        # User not in any crew team — return base multiplier with solo spend
        now = datetime.utcnow()
        month_start = datetime(now.year, now.month, 1)
        solo_spend_result = await db.execute(
            select(func.coalesce(func.sum(Order.total), 0)).where(
                Order.user_id == user_id,
                Order.created_at >= month_start,
                Order.status.notin_(["cancelled"]),
            )
        )
        solo_spend = float(solo_spend_result.scalar() or 0)
        return _get_multiplier(solo_spend)

    # Get all member IDs of the crew team
    members_result = await db.execute(
        select(CrewTeamMember.user_id).where(CrewTeamMember.team_id == team.id)
    )
    member_ids = [row[0] for row in members_result.all()]

    # Calculate collective monthly spend from orders
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    spend_result = await db.execute(
        select(func.coalesce(func.sum(Order.total), 0)).where(
            Order.user_id.in_(member_ids),
            Order.created_at >= month_start,
            Order.status.notin_(["cancelled"]),
        )
    )
    monthly_spend = float(spend_result.scalar() or 0)

    return _get_multiplier(monthly_spend)


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
