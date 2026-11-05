"""Server-owned delivery quotes and courier shipments."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, created_at_col, uuid_pk


class DeliveryQuote(Base):
    __tablename__ = "delivery_quotes"
    __table_args__ = (
        CheckConstraint("delivery_type IN ('courier','helm_dash')", name="valid_delivery_type"),
        CheckConstraint("price_cents >= 0", name="price_nonnegative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    delivery_type: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    service_name: Mapped[str] = mapped_column(String, nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="NZD", server_default="NZD")
    destination: Mapped[dict] = mapped_column(JSONB, nullable=False)
    parcel_weight_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    cart_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    operating_area_id: Mapped[str | None] = mapped_column(String, ForeignKey("operating_areas.id"), nullable=True)
    nautical_miles: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_by_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL", use_alter=True), nullable=True, unique=True
    )
    created_at: Mapped[datetime] = created_at_col()


class CourierShipment(Base):
    __tablename__ = "courier_shipments"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False)
    service_name: Mapped[str | None] = mapped_column(String, nullable=True)
    label_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="label_pending")
    # True when created by the local contract adapter (never a real booking).
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()
