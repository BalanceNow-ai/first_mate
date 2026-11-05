"""Crew Rewards: balance cache, auditable ledger, crews, invites and redemptions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, updated_at_col, uuid_pk


class CrewPoints(Base):
    """Per-user balance cache. Always updated in the same transaction as the ledger."""

    __tablename__ = "crew_points"
    __table_args__ = (
        CheckConstraint("points_balance >= 0", name="balance_nonnegative"),
        CheckConstraint("points_owed >= 0", name="owed_nonnegative"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    points_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lifetime_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Points that refunds should have reversed but had already been spent; settled from
    # the next credits (voids, cancellations, new earnings) before they become spendable.
    points_owed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Display-only tier from trailing-12-month eligible paid spend.
    tier: Mapped[str] = mapped_column(String, nullable=False, default="deckhand", server_default="deckhand")
    updated_at: Mapped[datetime] = updated_at_col()

    user: Mapped["User"] = relationship("User", back_populates="crew_points")  # noqa: F821


class PointsTransaction(Base):
    """Immutable ledger entry. ``idempotency_key`` makes every effect happen once."""

    __tablename__ = "points_transactions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('earn','earn_reversal','monthly_bonus','redeem_discount','redeem_experience',"
            "'redemption_reversal','profile_verification_bonus','adjustment',"
            "'monthly_bonus_reversal','owed_settlement')",
            name="valid_kind",
        ),
        CheckConstraint("points <> 0", name="points_nonzero"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crew_teams.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    points: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entitlement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discount_entitlements.id", ondelete="SET NULL"), nullable=True
    )
    redemption_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("experience_redemptions.id", ondelete="SET NULL"), nullable=True
    )
    # Pacific/Auckland business period, e.g. "2026-11".
    period: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    eligible_spend_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class CrewTeam(Base):
    __tablename__ = "crew_teams"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_col()

    members: Mapped[list["CrewTeamMember"]] = relationship(
        "CrewTeamMember", back_populates="team", cascade="all, delete-orphan"
    )


class CrewTeamMember(Base):
    """Membership. A user belongs to at most one crew (unique user_id)."""

    __tablename__ = "crew_team_members"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crew_teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, unique=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False, default="member", server_default="member")
    joined_at: Mapped[datetime] = created_at_col()

    team: Mapped[CrewTeam] = relationship("CrewTeam", back_populates="members")


class CrewInvite(Base):
    __tablename__ = "crew_invites"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','accepted','declined','revoked','expired')", name="valid_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("crew_teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invited_email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class DiscountEntitlement(Base):
    """A single-use checkout discount bought with points (100 CP = $1)."""

    __tablename__ = "discount_entitlements"
    __table_args__ = (
        CheckConstraint("status IN ('issued','reserved','consumed','voided')", name="valid_status"),
        CheckConstraint("amount_cents > 0", name="amount_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="issued", server_default="issued")
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class ExperienceRedemption(Base):
    """Durable fulfilment record for a Signature Experience redemption."""

    __tablename__ = "experience_redemptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested','confirmed','fulfilled','cancelled')", name="valid_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    experience_id: Mapped[str] = mapped_column(String, nullable=False)
    experience_title: Mapped[str] = mapped_column(String, nullable=False)
    points_cost: Mapped[int] = mapped_column(Integer, nullable=False)
    cms_provider: Mapped[str] = mapped_column(String, nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String, nullable=False, default="requested", server_default="requested")
    customer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    staff_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    handled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
