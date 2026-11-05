"""Order / checkout schemas. Money is integer NZD cents; the server computes all of it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, StrictInput
from app.schemas.shipping import POSTCODE_PATTERN

PHONE_PATTERN = r"^\+?[0-9 ()\-]{6,20}$"


class ShippingAddress(StrictInput):
    name: str = Field(min_length=1, max_length=100)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(None, max_length=200)
    suburb: str | None = Field(None, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    postcode: str = Field(pattern=POSTCODE_PATTERN)
    phone: str = Field(pattern=PHONE_PATTERN)


class HelmDashContact(StrictInput):
    vessel_name: str = Field(min_length=1, max_length=100)
    phone: str = Field(pattern=PHONE_PATTERN)
    note: str | None = Field(None, max_length=500)


class CheckoutRequest(StrictInput):
    delivery_type: Literal["courier", "helm_dash", "click_and_collect"]
    quote_id: uuid.UUID | None = None
    shipping_address: ShippingAddress | None = None
    helm_dash_contact: HelmDashContact | None = None
    discount_entitlement_id: uuid.UUID | None = None
    notes: str | None = Field(None, max_length=1000)
    # Only "card" is offered (Afterpay / Laybuy are not available, decision D7).
    payment_method: str = Field("card", max_length=32)


class CheckoutPreview(APIModel):
    currency: str = "NZD"
    delivery_type: str
    quote_id: uuid.UUID | None
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    total_cents: int
    free_shipping_applied: bool
    free_shipping_threshold_cents: int
    min_charge_cents: int
    pickup_location: str | None = None


class OrderItemResponse(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    sku: str
    quantity: int
    list_price_cents: int
    unit_price_cents: int
    line_total_cents: int


class TrackingInfo(APIModel):
    tracking_number: str | None = None
    courier: str | None = None
    shipment_status: str | None = None
    is_test: bool = False


class DeliveryInfo(APIModel):
    delivery_type: str | None
    shipping_address: dict | None = None
    helm_dash: dict | None = None
    pickup_location: str | None = None
    quote_id: uuid.UUID | None = None
    service_name: str | None = None
    estimated_days: int | None = None
    estimated_minutes: int | None = None
    free_shipping_applied: bool = False


class OrderResponse(APIModel):
    id: uuid.UUID
    order_number: str
    status: str
    payment_status: str
    currency: str
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    total_cents: int
    refunded_cents: int
    discount_entitlement_id: uuid.UUID | None
    payment_provider: str | None
    payment_intent_id: str | None
    delivery: DeliveryInfo
    items: list[OrderItemResponse]
    expires_at: datetime | None
    paid_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    notes: str | None
    can_cancel: bool
    can_retry_payment: bool
    tracking: TrackingInfo
    created_at: datetime
    updated_at: datetime


class StaffOrderResponse(OrderResponse):
    user_id: uuid.UUID
    review_reason: str | None


class OrderSummary(APIModel):
    id: uuid.UUID
    order_number: str
    status: str
    payment_status: str
    currency: str
    total_cents: int
    refunded_cents: int
    delivery_type: str | None
    item_count: int
    expires_at: datetime | None
    created_at: datetime


class StaffOrderSummary(OrderSummary):
    user_id: uuid.UUID
    review_reason: str | None


class OrderListResponse(APIModel):
    items: list[OrderSummary]
    total: int
    page: int
    page_size: int


class StaffOrderListResponse(APIModel):
    items: list[StaffOrderSummary]
    total: int
    page: int
    page_size: int


class FulfilmentUpdate(StrictInput):
    status: Literal["ready_for_dispatch", "dispatched", "delivered", "collected"]
    tracking_number: str | None = Field(None, max_length=100)
    courier: str | None = Field(None, max_length=100)


class RefundRequest(StrictInput):
    amount_cents: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class RefundResponse(APIModel):
    order_id: uuid.UUID
    provider: str
    refund_id: str
    status: str
    amount_cents: int
    currency: str = "NZD"
    test_mode: bool
    # local provider only: what the signed charge.refunded event did
    event_outcome: str | None = None
    refunded_cents: int
    payment_status: str
    order_status: str


class ShipmentResponse(APIModel):
    id: uuid.UUID
    order_id: uuid.UUID
    provider: str
    service_name: str | None
    label_reference: str | None
    tracking_number: str | None
    status: str
    is_test: bool
    created_at: datetime
