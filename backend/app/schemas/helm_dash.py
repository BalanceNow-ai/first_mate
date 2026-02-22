"""Helm Dash delivery Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class HelmDashQuoteRequest(BaseModel):
    delivery_lat: float
    delivery_lng: float


class HelmDashQuoteResponse(BaseModel):
    delivery_fee: float
    estimated_minutes: int
    nautical_miles: float
    location_name: str | None = None


class HelmDashDeliveryResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    status: str
    delivery_coordinates: dict
    delivery_location_name: str | None
    nautical_miles: float | None
    delivery_fee: float
    estimated_delivery_minutes: int | None
    operator_name: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HelmDashStatusUpdate(BaseModel):
    status: str  # assigned, pickup, en_route, delivered, cancelled
    operator_name: str | None = None
