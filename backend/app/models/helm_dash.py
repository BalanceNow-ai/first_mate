"""Helm Dash on-demand maritime delivery model."""

import uuid
from datetime import datetime

from sqlalchemy import String, Numeric, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HelmDashDelivery(Base):
    __tablename__ = "helm_dash_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="pending"
    )  # pending, assigned, pickup, en_route, delivered, cancelled
    pickup_location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    delivery_coordinates: Mapped[dict] = mapped_column(
        JSONB, nullable=False
    )  # {lat, lng}
    delivery_location_name: Mapped[str | None] = mapped_column(String, nullable=True)
    nautical_miles: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    delivery_fee: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    estimated_delivery_minutes: Mapped[int | None] = mapped_column(nullable=True)
    operator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    operator_name: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
