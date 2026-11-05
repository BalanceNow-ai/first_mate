"""Product catalogue and fitment rules."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price_cents > 0", name="price_positive"),
        CheckConstraint(
            "sale_price_cents IS NULL OR (sale_price_cents > 0 AND sale_price_cents < price_cents)",
            name="sale_price_valid",
        ),
        CheckConstraint("stock_quantity >= 0", name="stock_nonnegative"),
        CheckConstraint("fitment_scope IN ('universal','specific','unspecified')", name="valid_fitment_scope"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    category: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sub_category: Mapped[str | None] = mapped_column(String, nullable=True)
    # Money is stored as integer NZD cents.
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    sale_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    weight_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    images: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    specifications: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    oem_part_numbers: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # Functional role used for checklist linking (e.g. spark_plug, fuel_filter).
    part_role: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # universal: verified to suit any vessel (e.g. zip ties); specific: fit is decided by
    # verified fitment rules; unspecified: no fitment knowledge (always "unknown").
    fitment_scope: Mapped[str] = mapped_column(
        String, nullable=False, default="unspecified", server_default="unspecified"
    )
    dangerous_goods: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    compatibilities: Mapped[list[ProductCompatibility]] = relationship(
        "ProductCompatibility", back_populates="product", cascade="all, delete-orphan"
    )


FITMENT_SCOPE_CHECKS = {
    "nonblank_scope": (
        "btrim(coalesce(vessel_make, '')) <> '' OR btrim(coalesce(engine_make, '')) <> '' "
        "OR equipment_category_id IS NOT NULL"
    ),
    "vessel_dependents": (
        "btrim(coalesce(vessel_make, '')) <> '' OR (vessel_model IS NULL AND year_from IS NULL AND year_to IS NULL)"
    ),
    "engine_dependents": (
        "btrim(coalesce(engine_make, '')) <> '' "
        "OR (engine_model IS NULL AND engine_year_from IS NULL AND engine_year_to IS NULL)"
    ),
    "equipment_dependents": "equipment_category_id IS NOT NULL OR (equipment_make IS NULL AND equipment_model IS NULL)",
    "vessel_year_order": "year_from IS NULL OR year_to IS NULL OR year_from <= year_to",
    "engine_year_order": "engine_year_from IS NULL OR engine_year_to IS NULL OR engine_year_from <= engine_year_to",
}


class ProductCompatibility(Base):
    """A fitment rule linking a product to a vessel, engine or equipment specification.

    A rule only supports a positive "fits" result when it is ``verified`` and its
    confidence meets ``FITMENT_MIN_CONFIDENCE``.
    """

    __tablename__ = "product_compatibility"
    __table_args__ = (
        CheckConstraint("verification_status IN ('unverified','verified','rejected')", name="valid_verification"),
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 1", name="confidence_range"),
        CheckConstraint(
            "vessel_make IS NOT NULL OR engine_make IS NOT NULL OR equipment_category_id IS NOT NULL",
            name="has_scope",
        ),
        # FM-02 scope contract (app.core.fitment_rules); added NOT VALID by migration 0004.
        *(CheckConstraint(sql, name=name) for name, sql in FITMENT_SCOPE_CHECKS.items()),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vessel_make: Mapped[str | None] = mapped_column(String, nullable=True)
    vessel_model: Mapped[str | None] = mapped_column(String, nullable=True)
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_make: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_model: Mapped[str | None] = mapped_column(String, nullable=True)
    engine_year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine_year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    equipment_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("equipment_categories.id"), nullable=True
    )
    equipment_make: Mapped[str | None] = mapped_column(String, nullable=True)
    equipment_model: Mapped[str | None] = mapped_column(String, nullable=True)
    # service_part | consumable | upgrade | accessory
    fitment_type: Mapped[str] = mapped_column(
        String, nullable=False, default="service_part", server_default="service_part"
    )
    verification_status: Mapped[str] = mapped_column(
        String, nullable=False, default="unverified", server_default="unverified"
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.30"), server_default="0.30"
    )
    data_source: Mapped[str | None] = mapped_column(String, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    product: Mapped[Product] = relationship("Product", back_populates="compatibilities")
