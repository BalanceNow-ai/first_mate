"""Crew Rewards request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel, StrictInput


class PointsSummary(APIModel):
    points_balance: int
    lifetime_earned: int
    points_owed: int = 0
    points_value_cents: int
    currency: str
    tier: str
    tier_is_display_only: bool
    trailing_12_month_spend_cents: int
    next_tier: str | None
    next_tier_threshold_cents: int | None
    crew_id: uuid.UUID | None
    crew_wallet_points: int | None


class PointsTransactionOut(APIModel):
    id: uuid.UUID
    kind: str
    points: int
    balance_after: int
    description: str | None
    order_id: uuid.UUID | None
    entitlement_id: uuid.UUID | None
    redemption_id: uuid.UUID | None
    team_id: uuid.UUID | None
    period: str | None
    eligible_spend_cents: int | None
    created_at: datetime


class TransactionPage(APIModel):
    items: list[PointsTransactionOut]
    total: int
    limit: int
    offset: int


class MultiplierTier(APIModel):
    min_spend_cents: int
    multiplier: float


class MultiplierProgress(APIModel):
    period: str
    crew_id: uuid.UUID | None
    member_count: int
    eligible_for_multiplier: bool
    min_members: int
    crew_spend_cents: int
    currency: str
    current_multiplier: float
    spend_multiplier: float
    next_threshold_cents: int | None
    next_multiplier: float | None
    remaining_to_next_cents: int | None
    tiers: list[MultiplierTier]


class CrewCreate(StrictInput):
    name: str = Field(min_length=2, max_length=60)


class CrewMemberOut(APIModel):
    user_id: uuid.UUID
    display_name: str
    role: str
    joined_at: datetime
    points_balance: int
    is_you: bool


class CrewOut(APIModel):
    id: uuid.UUID
    name: str
    my_role: str
    members: list[CrewMemberOut]
    member_count: int
    pending_invite_count: int
    max_members: int
    wallet_points: int
    wallet_note: str
    created_at: datetime


class InviteCreate(StrictInput):
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CrewInviteOut(APIModel):
    """Invite as seen by the crew captain."""

    id: uuid.UUID
    invited_email: str
    status: str
    expires_at: datetime
    created_at: datetime


class MyInviteOut(APIModel):
    """Invite as seen by the invitee."""

    id: uuid.UUID
    crew_id: uuid.UUID
    crew_name: str
    invited_by_name: str | None
    status: str
    expires_at: datetime
    created_at: datetime


class LeaveResult(APIModel):
    left_crew_id: uuid.UUID
    disbanded: bool
    new_captain_id: uuid.UUID | None


class DiscountRedeem(StrictInput):
    points: int = Field(ge=100, description="A multiple of 100 (100 CP = $1 NZD)")


class EntitlementOut(APIModel):
    id: uuid.UUID
    code: str
    amount_cents: int
    points_cost: int
    status: str
    order_id: uuid.UUID | None
    created_at: datetime
    reserved_at: datetime | None
    consumed_at: datetime | None
    voided_at: datetime | None
    currency: str = "NZD"


class Experience(APIModel):
    id: str
    title: str
    description: str
    points_cost: int
    location: str | None = None
    capacity: int | None = None
    available: bool
    image_url: str | None = None
    is_synthetic: bool


class ExperienceCatalogue(APIModel):
    available: bool
    provider: str
    items: list[Experience]
    reason: str | None


class ExperienceRedeem(StrictInput):
    experience_id: str = Field(min_length=1, max_length=200)
    note: str | None = Field(None, max_length=1000)


class RedemptionOut(APIModel):
    id: uuid.UUID
    experience_id: str
    experience_title: str
    points_cost: int
    cms_provider: str
    is_synthetic: bool
    status: str
    customer_note: str | None
    fulfilled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AdminRedemptionOut(RedemptionOut):
    user_id: uuid.UUID
    staff_note: str | None
    handled_by: uuid.UUID | None


class RedemptionAction(StrictInput):
    staff_note: str | None = Field(None, max_length=1000)


class MultiplierRun(StrictInput):
    period: str | None = Field(None, pattern=r"^\d{4}-\d{2}$")


class MultiplierRunResult(APIModel):
    period: str
    crews: int
    bonuses_awarded: int
    points_awarded: int
