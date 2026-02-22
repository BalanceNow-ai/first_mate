"""AI chat Pydantic schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # user, assistant
    content: str


class ChatRequest(BaseModel):
    message: str
    vessel_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: ChatMessage
    product_recommendations: list[uuid.UUID] | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    vessel_id: uuid.UUID | None
    messages: list[dict]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
