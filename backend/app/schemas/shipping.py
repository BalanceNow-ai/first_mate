"""Delivery quote / shipping option schemas (money in integer NZD cents)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, StrictInput

POSTCODE_PATTERN = r"^\d{4}$"


class CourierDestination(StrictInput):
    """Courier destination. The rate card is weight based; the postcode binds the quote
    to the checkout shipping address."""

    postcode: str = Field(pattern=POSTCODE_PATTERN)
    city: str | None = Field(None, max_length=100)
    suburb: str | None = Field(None, max_length=100)


class HelmDashDestination(StrictInput):
    """Helm Dash destination: a vessel position (WGS84 decimal degrees)."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    location_name: str | None = Field(None, max_length=200)


class QuoteRequest(StrictInput):
    delivery_type: Literal["courier", "helm_dash"]
    destination: CourierDestination | HelmDashDestination


class QuoteResponse(APIModel):
    id: uuid.UUID
    delivery_type: str
    provider: str
    service_name: str
    price_cents: int
    currency: str = "NZD"
    destination: dict
    parcel_weight_grams: int
    merchandise_subtotal_cents: int
    free_shipping_threshold_cents: int | None = None
    operating_area_id: str | None = None
    operating_area_name: str | None = None
    nautical_miles: float | None = None
    estimated_minutes: int | None = None
    estimated_days: int | None = None
    development_rate_card: bool = False
    expires_at: datetime
    created_at: datetime


class OperatingAreaSummary(APIModel):
    id: str
    name: str
    center_lat: float
    center_lng: float
    radius_nm: float


class DeliveryOption(APIModel):
    delivery_type: Literal["courier", "helm_dash", "click_and_collect"]
    available: bool
    reason_code: str | None = None
    reason: str | None = None
    requires_quote: bool
    # Indicative price for the current cart (courier rate card / click & collect 0).
    # Helm Dash depends on the destination: request a quote.
    price_cents: int | None = None
    service_name: str | None = None
    estimated_days: int | None = None
    pickup_location: str | None = None
    development_rate_card: bool = False
    operating_areas: list[OperatingAreaSummary] = []


class RestrictedProduct(APIModel):
    product_id: uuid.UUID
    name: str
    sku: str


class DeliveryOptionsResponse(APIModel):
    currency: str = "NZD"
    merchandise_subtotal_cents: int
    total_weight_grams: int | None
    missing_weight_products: list[RestrictedProduct] = []
    dangerous_goods_products: list[RestrictedProduct] = []
    free_shipping_threshold_cents: int
    options: list[DeliveryOption]


class EstimateItem(StrictInput):
    product_id: uuid.UUID
    quantity: int = Field(1, ge=1, le=99)


class EstimateRequest(StrictInput):
    delivery_type: Literal["courier", "helm_dash"]
    items: list[EstimateItem] = Field(min_length=1, max_length=50)
    destination: HelmDashDestination | None = None


class EstimateResponse(APIModel):
    delivery_type: str
    available: bool
    reason_code: str | None = None
    reason: str | None = None
    price_cents: int | None = None
    currency: str = "NZD"
    service_name: str | None = None
    estimated_days: int | None = None
    estimated_minutes: int | None = None
    nautical_miles: float | None = None
    development_rate_card: bool = False
    # Estimates are informational only and cannot be used at checkout.
    bindable: bool = False
