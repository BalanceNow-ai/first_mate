"""Notification preference, push device and history contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import APIModel, StrictInput


class PreferencesOut(APIModel):
    email_enabled: bool
    push_enabled: bool
    order_updates: bool
    delivery_updates: bool
    service_reminders: bool
    rewards_updates: bool
    marketing: bool
    transactional_note: str = "Order confirmations and refund receipts are always sent by email."


class PreferencesUpdate(StrictInput):
    email_enabled: bool | None = None
    push_enabled: bool | None = None
    order_updates: bool | None = None
    delivery_updates: bool | None = None
    service_reminders: bool | None = None
    rewards_updates: bool | None = None
    marketing: bool | None = None


class PushDeviceCreate(StrictInput):
    token: str = Field(min_length=10, max_length=4096)
    platform: str = Field(pattern="^(ios|android|web)$")


class PushDeviceOut(APIModel):
    id: uuid.UUID
    platform: str
    created_at: datetime
    last_seen_at: datetime


class NotificationOut(APIModel):
    id: uuid.UUID
    channel: str
    category: str
    template: str
    subject: str
    status: str
    created_at: datetime
    sent_at: datetime | None
