"""Voyage checklist models (tiered, with inheritance by tier level)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, uuid_pk

TIERS = ("grab_and_go", "coastal_cruising", "offshore_passage")


class VoyageChecklist(Base):
    __tablename__ = "voyage_checklists"
    __table_args__ = (
        UniqueConstraint("vessel_id", "tier"),
        CheckConstraint("tier IN ('grab_and_go','coastal_cruising','offshore_passage')", name="valid_tier"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    vessel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    template_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    items: Mapped[list[ChecklistItem]] = relationship(
        "ChecklistItem",
        back_populates="checklist",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.position",
    )


class ChecklistItem(Base):
    """Item introduced at its checklist's tier; inherited by higher tiers."""

    __tablename__ = "checklist_items"
    __table_args__ = (
        CheckConstraint(
            "link_status IN ('verified_fit','universal','user_linked_unverified','unlinked')",
            name="valid_link_status",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    checklist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voyage_checklists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_key: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    system: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    part_role: Mapped[str | None] = mapped_column(String, nullable=True)
    # applies | if_fitted (equipment presence unknown)
    applicability: Mapped[str] = mapped_column(String, nullable=False, default="applies", server_default="applies")
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    link_status: Mapped[str] = mapped_column(String, nullable=False, default="unlinked", server_default="unlinked")
    is_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    checklist: Mapped[VoyageChecklist] = relationship("VoyageChecklist", back_populates="items")
