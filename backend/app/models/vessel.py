"""Vessel (My Vessel Garage), installed equipment, service history and reminders."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, updated_at_col, uuid_pk


class Vessel(Base):
    __tablename__ = "vessels"
    __table_args__ = (
        CheckConstraint("year >= 1900 AND year <= 2100", name="year_range"),
        CheckConstraint("engine_hours IS NULL OR engine_hours >= 0", name="engine_hours_nonneg"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nickname: Mapped[str] = mapped_column(String, nullable=False)
    hin: Mapped[str | None] = mapped_column(String, nullable=True)
    # Outcome of HIN decoding at capture time: valid | invalid | unrecognised | null
    hin_status: Mapped[str | None] = mapped_column(String, nullable=True)
    hin_decoded: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    make: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    model_year_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_years.id", ondelete="SET NULL"), nullable=True
    )
    hull_type: Mapped[str | None] = mapped_column(String, nullable=True)
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    primary_use: Mapped[str | None] = mapped_column(String, nullable=True)
    propulsion_type: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_make: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_model: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_serial: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    user: Mapped["User"] = relationship("User", back_populates="vessels")  # noqa: F821
    ai_conversations: Mapped[list["AIConversation"]] = relationship(  # noqa: F821
        "AIConversation", back_populates="vessel", passive_deletes=True
    )
    equipment: Mapped[list["VesselEquipment"]] = relationship(
        back_populates="vessel", cascade="all, delete-orphan"
    )


class VesselEquipment(Base):
    """Equipment installed on a vessel (OEM or owner-added), with provenance."""

    __tablename__ = "vessel_equipment"
    __table_args__ = (
        CheckConstraint("origin IN ('oem','user_added')", name="valid_origin"),
        CheckConstraint(
            "verification_status IN ('unverified','pending_review','verified','rejected')",
            name="valid_verification",
        ),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 1", name="confidence_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    make: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String, nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    oem_equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("oem_equipment.id", ondelete="SET NULL"), nullable=True
    )
    # owner_declared | oem_database | staff_verified
    provenance: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    verification_status: Mapped[str] = mapped_column(String, nullable=False)
    installed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    vessel: Mapped[Vessel] = relationship(back_populates="equipment")
    category: Mapped["EquipmentCategory"] = relationship()  # noqa: F821


class EquipmentVerificationRequest(Base):
    """Crowdsourced profile completion submitted for staff review (spec §4.2)."""

    __tablename__ = "equipment_verification_requests"

    id: Mapped[uuid.UUID] = uuid_pk()
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending")
    submitted_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class ServiceRecord(Base):
    __tablename__ = "service_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessel_equipment.id", ondelete="SET NULL"), nullable=True
    )
    service_type: Mapped[str] = mapped_column(String, nullable=False)
    performed_on: Mapped[date] = mapped_column(Date, nullable=False)
    engine_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class ServiceReminder(Base):
    __tablename__ = "service_reminders"
    __table_args__ = (
        CheckConstraint("status IN ('active','completed','dismissed')", name="valid_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    equipment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessel_equipment.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_engine_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    # owner | knowledge_source (an admitted source supplied the interval)
    source: Mapped[str] = mapped_column(String, nullable=False, default="owner", server_default="owner")
    knowledge_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="SET NULL"), nullable=True
    )
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
