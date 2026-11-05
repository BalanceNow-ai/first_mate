"""Transactional notification outbox, preferences and push devices."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, created_at_col, updated_at_col, uuid_pk


class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    __table_args__ = (
        CheckConstraint("channel IN ('email','push')", name="valid_channel"),
        CheckConstraint("status IN ('pending','sending','sent','failed','dead','suppressed')", name="valid_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    channel: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)  # order | delivery | reminder | rewards
    template: Mapped[str] = mapped_column(String, nullable=False)
    recipient: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    push_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    order_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    delivery_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    service_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    rewards_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    marketing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    updated_at: Mapped[datetime] = updated_at_col()


class PushDevice(Base):
    __tablename__ = "push_devices"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = created_at_col()
    last_seen_at: Mapped[datetime] = updated_at_col()
