"""User model — the local profile bound to a verified Supabase Auth subject."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, updated_at_col

ROLES = ("customer", "operator", "dispatcher", "admin", "moderator")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('customer','operator','dispatcher','admin','moderator')", name="valid_role"),
    )

    # Primary key == the verified `sub` claim of the Supabase access token.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    # Authorization role. Only changed by an admin action / CLI; never from a token
    # claim, user metadata or the profile endpoints.
    role: Mapped[str] = mapped_column(String, nullable=False, default="customer", server_default="customer")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    vessels: Mapped[list[Vessel]] = relationship(  # noqa: F821
        "Vessel", back_populates="user", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship("Order", back_populates="user")  # noqa: F821
    cart_items: Mapped[list[CartItem]] = relationship(  # noqa: F821
        "CartItem", back_populates="user", cascade="all, delete-orphan"
    )
    crew_points: Mapped[CrewPoints | None] = relationship(  # noqa: F821
        "CrewPoints", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    ai_conversations: Mapped[list[AIConversation]] = relationship(  # noqa: F821
        "AIConversation", back_populates="user", cascade="all, delete-orphan"
    )
