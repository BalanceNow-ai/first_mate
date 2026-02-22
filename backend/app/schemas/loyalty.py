"""Crew Rewards loyalty Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CrewPointsResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    points_balance: int
    tier: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class CrewTeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CrewTeamResponse(BaseModel):
    id: uuid.UUID
    name: str
    created_by: uuid.UUID
    crew_wallet_balance: int
    member_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class CrewTeamMemberResponse(BaseModel):
    team_id: uuid.UUID
    user_id: uuid.UUID
    joined_at: datetime

    model_config = {"from_attributes": True}


class RedeemPointsRequest(BaseModel):
    points: int = Field(gt=0)
    redemption_type: str  # product_discount, experience
    experience_id: str | None = None


class PointsMultiplier(BaseModel):
    monthly_spend: float
    multiplier: float
    effective_rate: float


class SignatureExperience(BaseModel):
    id: str
    title: str
    description: str
    cost_cp: int = Field(gt=0)
    image_url: str | None = None
    location: str | None = None
    duration_hours: float | None = None
    available: bool = True
