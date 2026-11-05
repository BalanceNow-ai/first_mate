"""Knowledge corpus administration schemas."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import APIModel, StrictInput


class KnowledgeFact(StrictInput):
    key: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=120)
    heading: str | None = Field(default=None, max_length=200)


class KnowledgeIngestRequest(StrictInput):
    title: str = Field(min_length=1, max_length=300)
    publisher: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    licence: str = Field(min_length=1, max_length=500)
    licence_verified: bool = False
    domain: str = Field(min_length=1, max_length=40)
    applies_to: dict[str, str | list[str]] = {}
    is_synthetic: bool = False
    version: str | None = Field(default=None, max_length=40)
    facts: list[KnowledgeFact] = Field(default=[], max_length=100)
    format: Literal["markdown", "text"] = "markdown"
    # Bounded again by KNOWLEDGE_MAX_DOCUMENT_CHARS in the service.
    content: str = Field(min_length=1, max_length=1_000_000)


class KnowledgeAdmitRequest(StrictInput):
    licence_verified: bool | None = None


class KnowledgeSourceResponse(APIModel):
    id: uuid.UUID
    title: str
    publisher: str | None
    url: str | None
    licence: str
    licence_verified: bool
    admission_status: Literal["pending", "admitted", "revoked"]
    is_synthetic: bool
    domain: str
    applies_to: dict
    checksum: str
    version: str | None
    admitted_by: uuid.UUID | None
    admitted_at: datetime | None
    chunk_count: int = 0
    embedding_models: list[str] = []
    created_at: datetime
    updated_at: datetime


class KnowledgeIngestResponse(APIModel):
    status: Literal["created", "unchanged", "new_version"]
    source: KnowledgeSourceResponse
    superseded_source_ids: list[uuid.UUID]


class KnowledgeReembedResponse(APIModel):
    source: KnowledgeSourceResponse
    chunks_embedded: int
