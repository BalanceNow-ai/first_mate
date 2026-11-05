"""First Mate chat schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, StrictInput
from app.schemas.product import FitmentResult

GroundingStatus = Literal["grounded", "insufficient_evidence", "conflicting"]


class ChatRequest(StrictInput):
    # Hard transport cap; the configurable limit (AI_MAX_MESSAGE_CHARS) is enforced in the router.
    message: str = Field(min_length=1, max_length=20_000)
    vessel_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None


class AssistantMessage(APIModel):
    role: Literal["assistant"] = "assistant"
    content: str
    created_at: datetime


class Grounding(APIModel):
    status: GroundingStatus
    specialists_consulted: list[str]
    note: str


class Citation(APIModel):
    index: int
    source_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    publisher: str | None
    url: str | None
    licence: str
    excerpt: str
    is_synthetic: bool


class ProductReference(APIModel):
    id: uuid.UUID
    name: str
    sku: str
    brand: str | None
    effective_price_cents: int
    currency: str
    in_stock: bool
    image: str | None
    fitment: FitmentResult


class CartAction(APIModel):
    type: Literal["add_to_cart"]
    product_id: uuid.UUID
    quantity: int
    label: str


class VesselRef(APIModel):
    id: uuid.UUID
    label: str


class ChatResponse(APIModel):
    conversation_id: uuid.UUID
    message: AssistantMessage
    grounding: Grounding
    citations: list[Citation]
    products: list[ProductReference]
    actions: list[CartAction]
    vessel: VesselRef | None
    mode: Literal["openai", "local_extractive"]


class StoredMessage(APIModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    grounding: Grounding | None = None
    citations: list[Citation] = []
    products: list[ProductReference] = []
    actions: list[CartAction] = []
    vessel: VesselRef | None = None
    mode: str | None = None


class ConversationSummary(APIModel):
    id: uuid.UUID
    title: str | None
    vessel_id: uuid.UUID | None
    message_count: int
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[StoredMessage]


class SpecialistInfo(APIModel):
    key: str
    name: str
    description: str
