"""Helm Dash maritime delivery: areas, operators, deliveries, tracking and payouts."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, created_at_col, updated_at_col, uuid_pk

DELIVERY_STATUSES = (
    "awaiting_dispatch",
    "assigned",
    "accepted",
    "picked_up",
    "en_route",
    "delivered",
    "failed",
    "cancelled",
)


class OperatingArea(Base):
    __tablename__ = "operating_areas"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # slug, e.g. hauraki-gulf
    name: Mapped[str] = mapped_column(String, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lng: Mapped[float] = mapped_column(Float, nullable=False)
    radius_nm: Mapped[float] = mapped_column(Float, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()


class DeliveryOperator(Base):
    """A Helm Dash skipper account. ``active`` is set by an admin after vetting; the
    platform does not itself certify operators or dangerous-goods carriage."""

    __tablename__ = "delivery_operators"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    vessel_name: Mapped[str | None] = mapped_column(String, nullable=True)
    area_id: Mapped[str] = mapped_column(String, ForeignKey("operating_areas.id"), nullable=False)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    certification_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class HelmDashDelivery(Base):
    __tablename__ = "helm_dash_deliveries"
    __table_args__ = (
        CheckConstraint("status IN (" + ",".join(f"'{s}'" for s in DELIVERY_STATUSES) + ")", name="valid_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, unique=True
    )
    area_id: Mapped[str | None] = mapped_column(String, ForeignKey("operating_areas.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="awaiting_dispatch")
    pickup_location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    delivery_coordinates: Mapped[dict] = mapped_column(JSONB, nullable=False)
    delivery_location_name: Mapped[str | None] = mapped_column(String, nullable=True)
    nautical_miles: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    delivery_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_delivery_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    operator_name: Mapped[str | None] = mapped_column(String, nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class DeliveryStatusEvent(Base):
    __tablename__ = "delivery_status_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("helm_dash_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String, nullable=True)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class DeliveryLocationUpdate(Base):
    """A position *reported* by the assigned operator's device. Never interpolated."""

    __tablename__ = "delivery_location_updates"
    __table_args__ = (
        CheckConstraint("lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180", name="valid_coords"),
        CheckConstraint("source IN ('operator_device','simulated')", name="valid_source"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("helm_dash_deliveries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_knots: Mapped[float | None] = mapped_column(Float, nullable=True)
    # simulated: posted by the local simulation tool; always labelled as such.
    source: Mapped[str] = mapped_column(String, nullable=False, default="operator_device")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class OperatorPayout(Base):
    """Partner payout record. Live payouts are disabled; records support reconciliation."""

    __tablename__ = "operator_payouts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('rate_unconfigured','pending_review','approved','paid','cancelled')",
            name="valid_status",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("helm_dash_deliveries.id"), nullable=False, unique=True
    )
    operator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    gross_fee_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    share_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
