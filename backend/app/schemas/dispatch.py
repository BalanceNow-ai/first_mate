"""Helm Dash dispatch, operator and payout contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel, StrictInput
from app.schemas.helm_dash import ReportedLocation


class AreaCreate(StrictInput):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=2, max_length=120)
    center_lat: float = Field(ge=-90, le=90)
    center_lng: float = Field(ge=-180, le=180)
    radius_nm: float = Field(gt=0, le=200)
    enabled: bool = False


class AreaUpdate(StrictInput):
    name: str | None = Field(None, min_length=2, max_length=120)
    center_lat: float | None = Field(None, ge=-90, le=90)
    center_lng: float | None = Field(None, ge=-180, le=180)
    radius_nm: float | None = Field(None, gt=0, le=200)
    enabled: bool | None = None


class AreaOut(APIModel):
    id: str
    name: str
    center_lat: float
    center_lng: float
    radius_nm: float
    enabled: bool
    created_at: datetime


class OperatorCreate(StrictInput):
    user_id: uuid.UUID
    display_name: str = Field(min_length=2, max_length=80)
    vessel_name: str | None = Field(None, max_length=80)
    area_id: str
    certification_reference: str | None = Field(
        None, max_length=200, description="Free text recorded as unverified; the platform does not certify operators"
    )


class OperatorOut(APIModel):
    user_id: uuid.UUID
    display_name: str
    vessel_name: str | None
    area_id: str
    is_online: bool
    active: bool
    certification_reference: str | None
    certification_verified: bool = False
    created_at: datetime


class Availability(StrictInput):
    is_online: bool


class AssignBody(StrictInput):
    operator_id: uuid.UUID
    note: str | None = Field(None, max_length=500)


class ReasonBody(StrictInput):
    reason: str | None = Field(None, max_length=500)


class OperatorStatusBody(StrictInput):
    status: str = Field(pattern="^(picked_up|en_route|delivered|failed)$")
    note: str | None = Field(None, max_length=500)


class LocationBody(StrictInput):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0, le=100_000)
    heading_deg: float | None = Field(None, ge=0, lt=360)
    speed_knots: float | None = Field(None, ge=0, le=100)
    recorded_at: datetime


class LocationOut(APIModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    lat: float
    lng: float
    recorded_at: datetime
    source: str


class StatusEventOut(APIModel):
    from_status: str | None
    to_status: str
    actor_role: str
    actor_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class DeliveryOut(APIModel):
    """Dispatcher / operator view of a delivery job."""

    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str | None = None
    area_id: str | None
    status: str
    pickup_location: dict | None
    delivery_coordinates: dict
    delivery_location_name: str | None
    nautical_miles: float | None
    delivery_fee_cents: int
    currency: str = "NZD"
    estimated_delivery_minutes: int | None
    operator_id: uuid.UUID | None
    operator_name: str | None
    assigned_at: datetime | None
    accepted_at: datetime | None
    picked_up_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeliveryDetailOut(DeliveryOut):
    events: list[StatusEventOut]
    latest_location: ReportedLocation | None


class PayoutOut(APIModel):
    id: uuid.UUID
    delivery_id: uuid.UUID
    operator_id: uuid.UUID
    gross_fee_cents: int
    share_bps: int | None
    amount_cents: int | None
    status: str
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    paid_at: datetime | None
    created_at: datetime
    currency: str = "NZD"


class PayoutStatusTotal(APIModel):
    status: str
    count: int
    amount_cents: int
    gross_fee_cents: int


class Reconciliation(APIModel):
    period: str
    currency: str
    delivered_count: int
    delivery_fees_cents: int
    payouts_by_status: list[PayoutStatusTotal]
    operator_share_bps: int | None
    live_payouts_enabled: bool
