"""Boat OEM database (Helm_Boat_Database_Design_Specification §5)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, uuid_pk

# data_source values and the default confidence they carry (spec §5).
DATA_SOURCE_CONFIDENCE = {
    "manufacturer": Decimal("1.0"),
    "dealer": Decimal("0.9"),
    "internal_curation": Decimal("0.8"),
    "crowdsourced_verified": Decimal("0.8"),
    "crowdsourced_unverified": Decimal("0.3"),
    "synthetic_fixture": Decimal("0.0"),
}


class Manufacturer(Base):
    __tablename__ = "manufacturers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    # Manufacturer Identification Codes (first 3 chars of a HIN). Only recorded from
    # an attributable source; never guessed.
    mic_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    models: Mapped[list["BoatModel"]] = relationship(back_populates="manufacturer")


class BoatModel(Base):
    __tablename__ = "boat_models"
    __table_args__ = (UniqueConstraint("manufacturer_id", "name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    manufacturer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("manufacturers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    hull_type: Mapped[str | None] = mapped_column(String, nullable=True)
    propulsion_type: Mapped[str | None] = mapped_column(String, nullable=True)
    length_ft: Mapped[Decimal | None] = mapped_column(Numeric(5, 1), nullable=True)
    beam_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    manufacturer: Mapped[Manufacturer] = relationship(back_populates="models")
    years: Mapped[list["ModelYear"]] = relationship(back_populates="boat_model")


class ModelYear(Base):
    __tablename__ = "model_years"
    __table_args__ = (UniqueConstraint("boat_model_id", "year"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    boat_model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("boat_models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    brochure_url: Mapped[str | None] = mapped_column(String, nullable=True)
    hin_prefix: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    boat_model: Mapped[BoatModel] = relationship(back_populates="years")
    equipment: Mapped[list["OEMEquipment"]] = relationship(back_populates="model_year")


class EquipmentCategory(Base):
    __tablename__ = "equipment_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=True
    )


class OEMEquipment(Base):
    __tablename__ = "oem_equipment"
    __table_args__ = (
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 1", name="confidence_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    model_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_years.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=False
    )
    equipment_make: Mapped[str] = mapped_column(String, nullable=False)
    equipment_model: Mapped[str | None] = mapped_column(String, nullable=True)
    part_sku: Mapped[str | None] = mapped_column(String, nullable=True)
    is_standard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    data_source: Mapped[str] = mapped_column(String, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String, nullable=False, default="unverified", server_default="unverified"
    )
    created_at: Mapped[datetime] = created_at_col()

    model_year: Mapped[ModelYear] = relationship(back_populates="equipment")
    category: Mapped[EquipmentCategory] = relationship()
