"""Helm Dash customer tracking contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import APIModel


class AreaPublic(APIModel):
    id: str
    name: str
    center_lat: float
    center_lng: float
    radius_nm: float


class ReportedLocation(APIModel):
    lat: float
    lng: float
    accuracy_m: float | None
    heading_deg: float | None
    speed_knots: float | None
    recorded_at: datetime
    source: str
    is_simulated: bool
    source_label: str
    age_seconds: int


class TimelineEntry(APIModel):
    status: str
    label: str
    at: datetime


class TrackingOut(APIModel):
    id: uuid.UUID
    order_id: uuid.UUID
    order_number: str
    status: str
    status_label: str
    area_id: str | None
    pickup_location: dict | None
    delivery_coordinates: dict
    delivery_location_name: str | None
    nautical_miles: float | None
    delivery_fee_cents: int
    currency: str = "NZD"
    estimated_delivery_minutes: int | None
    operator_display_name: str | None
    operator_vessel_name: str | None
    timeline: list[TimelineEntry]
    latest_location: ReportedLocation | None
    location_message: str | None
    created_at: datetime
    updated_at: datetime
