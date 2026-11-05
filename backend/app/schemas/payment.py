"""Payment schemas. Card details never pass through this API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, StrictInput


class PaymentIntentRequest(StrictInput):
    # Only "card" is offered (Afterpay / Laybuy are not available, decision D7).
    payment_method: str = Field("card", max_length=32)


class PaymentIntentResponse(APIModel):
    order_id: uuid.UUID
    provider: Literal["stripe", "local"]
    payment_intent_id: str
    client_secret: str
    status: str
    amount_cents: int
    currency: str = "NZD"
    publishable_key: str | None = None  # stripe only
    test_mode: bool  # true for the local test provider: no real payment happens
    expires_at: datetime | None = None


class LocalConfirmRequest(StrictInput):
    outcome: Literal["succeed", "decline", "requires_action", "authenticate", "processing"]


class LocalConfirmResponse(APIModel):
    test_mode: bool = True
    outcome: str
    event_id: str
    event_type: str
    event_outcome: str
    order_id: uuid.UUID
    order_status: str
    payment_status: str


class WebhookResponse(APIModel):
    received: bool
    event_id: str
    outcome: str  # applied | ignored | stale | mismatch | duplicate
