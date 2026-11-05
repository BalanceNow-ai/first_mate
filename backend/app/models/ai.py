"""First Mate conversations and the RAG knowledge corpus."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, created_at_col, updated_at_col, uuid_pk

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small; the local substitute matches it


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    messages: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    user: Mapped["User"] = relationship("User", back_populates="ai_conversations")  # noqa: F821
    vessel: Mapped["Vessel | None"] = relationship(  # noqa: F821
        "Vessel", back_populates="ai_conversations"
    )


class KnowledgeSource(Base):
    """A document admitted (or not) to the knowledge corpus, with licence provenance."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "admission_status IN ('pending','admitted','revoked')", name="valid_admission"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String, nullable=False)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    licence: Mapped[str] = mapped_column(String, nullable=False)
    licence_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    admission_status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    domain: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Applicability, e.g. {"engine_make": "Yamaha", "engine_model": "F150"}; {} = general.
    applies_to: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    checksum: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str | None] = mapped_column(String, nullable=True)
    admitted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()

    chunks: Mapped[list["RAGDocument"]] = relationship(back_populates="knowledge_source")


class RAGDocument(Base):
    """A retrievable chunk of a knowledge source with its embedding."""

    __tablename__ = "rag_documents"
    __table_args__ = (
        Index(
            "ix_rag_documents_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_domain: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Legacy free-text source label from the Phase-7 schema.
    source: Mapped[str] = mapped_column(String, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    heading: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = created_at_col()

    knowledge_source: Mapped[KnowledgeSource | None] = relationship(back_populates="chunks")
