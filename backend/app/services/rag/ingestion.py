"""Knowledge-source ingestion, versioning, admission and re-embedding.

A source is ingested as ``pending``. Only an admin can admit it, and only when its
licence has been verified (synthetic fixtures are exempt in development/test only).
Only ``admitted`` sources are ever retrieved.

Versioning: a source's logical identity is (title, publisher). Re-ingesting content
with an identical checksum is a no-op. Changed content for the same identity
creates a new ``pending`` version and revokes every older version, so superseded
text can no longer be retrieved.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.database import utcnow
from app.models.ai import KnowledgeSource, RAGDocument
from app.services.rag.chunking import Chunk, attach_facts, chunk_document
from app.services.rag.embeddings import EmbeddingProvider, get_embedder

APPLIES_TO_KEYS = ("engine_make", "engine_model", "vessel_make", "vessel_model")
_FACT_KEY_MAX = 64
_FACT_VALUE_MAX = 120


@dataclass
class SourceMetadata:
    title: str
    licence: str
    domain: str
    publisher: str | None = None
    url: str | None = None
    licence_verified: bool = False
    applies_to: dict[str, Any] = field(default_factory=dict)
    is_synthetic: bool = False
    version: str | None = None
    facts: list[dict] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict, **overrides: Any) -> SourceMetadata:
        merged = {**data, **{k: v for k, v in overrides.items() if v is not None}}
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(merged) - known
        if unknown:
            raise AppError(422, "invalid_metadata", f"Unknown metadata fields: {sorted(unknown)}")
        for required in ("title", "licence", "domain"):
            if not merged.get(required):
                raise AppError(422, "invalid_metadata", f"Metadata field {required!r} is required")
        if merged.get("version") is not None:
            merged["version"] = str(merged["version"])
        return cls(**merged)


@dataclass
class IngestResult:
    status: str  # created | unchanged | new_version
    source: KnowledgeSource
    chunk_count: int
    superseded_ids: list[uuid.UUID] = field(default_factory=list)


def validate_metadata(meta: SourceMetadata) -> None:
    from app.services.ai.specialists import SPECIALISTS

    if meta.domain not in SPECIALISTS:
        raise AppError(422, "invalid_domain", f"Unknown knowledge domain {meta.domain!r}")
    if not isinstance(meta.applies_to, dict):
        raise AppError(422, "invalid_metadata", "applies_to must be an object")
    for key, value in meta.applies_to.items():
        if key not in APPLIES_TO_KEYS:
            raise AppError(422, "invalid_metadata", f"Unsupported applies_to key {key!r}")
        values = value if isinstance(value, list) else [value]
        if not values or not all(isinstance(v, str) and v.strip() for v in values):
            raise AppError(
                422, "invalid_metadata", f"applies_to.{key} must be a string or list of strings"
            )
    if not isinstance(meta.facts, list):
        raise AppError(422, "invalid_metadata", "facts must be a list")
    for fact in meta.facts:
        if (
            not isinstance(fact, dict)
            or not isinstance(fact.get("key"), str)
            or not fact["key"].strip()
            or len(fact["key"]) > _FACT_KEY_MAX
            or not isinstance(fact.get("value"), str | int | float)
            or len(str(fact["value"])) > _FACT_VALUE_MAX
            or set(fact) - {"key", "value", "label", "heading"}
        ):
            raise AppError(422, "invalid_metadata", "Each fact needs a short 'key' and 'value'")


def checksum(meta: SourceMetadata, body: str) -> str:
    canonical = json.dumps(
        {
            "body": body.strip(),
            "domain": meta.domain,
            "applies_to": meta.applies_to,
            "facts": meta.facts,
            "licence": meta.licence,
            "url": meta.url,
            "is_synthetic": meta.is_synthetic,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _embedding_text(title: str, chunk_heading: str | None, content: str) -> str:
    return "\n".join(p for p in (title, chunk_heading, content) if p)


async def _embed_chunks(
    embedder: EmbeddingProvider, title: str, chunks: list[tuple[str | None, str]]
) -> list[list[float]]:
    return await embedder.embed([_embedding_text(title, h, c) for h, c in chunks])


def _identity(meta: SourceMetadata):
    return (
        func.lower(KnowledgeSource.title) == meta.title.strip().lower(),
        func.coalesce(func.lower(KnowledgeSource.publisher), "")
        == (meta.publisher or "").strip().lower(),
    )


async def ingest(
    db: AsyncSession,
    meta: SourceMetadata,
    body: str,
    *,
    embedder: EmbeddingProvider | None = None,
    actor_id: uuid.UUID | None = None,
) -> IngestResult:
    """Ingest a text/markdown document as a pending knowledge source."""
    settings = get_settings()
    validate_metadata(meta)
    if not body or not body.strip():
        raise AppError(422, "empty_document", "The document has no content")
    if len(body) > settings.knowledge_max_document_chars:
        raise AppError(413, "document_too_large", "The document exceeds the maximum size")
    embedder = embedder or get_embedder(settings)
    digest = checksum(meta, body)

    previous = list(
        (
            await db.execute(
                select(KnowledgeSource).where(*_identity(meta)).order_by(KnowledgeSource.created_at)
            )
        ).scalars()
    )
    for existing in previous:
        if existing.checksum == digest:
            count = await db.scalar(
                select(func.count()).where(RAGDocument.source_id == existing.id)
            )
            return IngestResult("unchanged", existing, int(count or 0))

    chunks: list[Chunk] = chunk_document(
        body, settings.knowledge_chunk_chars, settings.knowledge_chunk_overlap_chars
    )
    if not chunks:
        raise AppError(422, "empty_document", "The document has no content")
    if len(chunks) > settings.knowledge_max_chunks_per_source:
        raise AppError(413, "document_too_large", "The document produces too many chunks")
    attach_facts(chunks, meta.facts)
    vectors = await _embed_chunks(embedder, meta.title, [(c.heading, c.content) for c in chunks])

    version = meta.version or str(len(previous) + 1)
    source = KnowledgeSource(
        title=meta.title.strip(),
        publisher=(meta.publisher or None),
        url=meta.url or None,
        licence=meta.licence,
        licence_verified=bool(meta.licence_verified),
        admission_status="pending",
        is_synthetic=bool(meta.is_synthetic),
        domain=meta.domain,
        applies_to=meta.applies_to,
        checksum=digest,
        version=version,
    )
    db.add(source)
    await db.flush()
    for chunk, vector in zip(chunks, vectors, strict=True):
        db.add(
            RAGDocument(
                source_id=source.id,
                agent_domain=meta.domain,
                source=meta.title[:200],
                chunk_index=chunk.index,
                heading=chunk.heading,
                content=chunk.content,
                embedding=vector,
                embedding_model=embedder.model_id,
                metadata_={"facts": chunk.facts, "version": version},
            )
        )
    superseded: list[uuid.UUID] = []
    for old in previous:
        if old.admission_status != "revoked":
            old.admission_status = "revoked"
            superseded.append(old.id)
    await db.flush()
    from app.services import audit

    await audit.record(
        db,
        actor_id,
        "knowledge_ingest",
        "knowledge_source",
        source.id,
        {"title": source.title, "version": version, "superseded": [str(s) for s in superseded]},
    )
    return IngestResult("new_version" if previous else "created", source, len(chunks), superseded)


async def get_source(db: AsyncSession, source_id: uuid.UUID) -> KnowledgeSource:
    source = await db.get(KnowledgeSource, source_id, with_for_update=True)
    if source is None:
        raise AppError(404, "not_found", "Knowledge source not found")
    return source


def can_admit(source: KnowledgeSource) -> bool:
    if source.licence_verified:
        return True
    return source.is_synthetic and get_settings().is_local


async def admit(
    db: AsyncSession,
    source_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    licence_verified: bool | None = None,
) -> KnowledgeSource:
    source = await get_source(db, source_id)
    if licence_verified is not None:
        source.licence_verified = licence_verified
    if not can_admit(source):
        raise AppError(
            409,
            "licence_not_verified",
            "The source licence must be verified before it can be admitted",
        )
    source.admission_status = "admitted"
    source.admitted_by = actor_id
    source.admitted_at = utcnow()
    await db.flush()
    from app.services import audit

    await audit.record(
        db,
        actor_id,
        "knowledge_admit",
        "knowledge_source",
        source.id,
        {"title": source.title, "synthetic": source.is_synthetic},
    )
    return source


async def revoke(
    db: AsyncSession, source_id: uuid.UUID, actor_id: uuid.UUID | None
) -> KnowledgeSource:
    source = await get_source(db, source_id)
    source.admission_status = "revoked"
    await db.flush()
    from app.services import audit

    await audit.record(
        db, actor_id, "knowledge_revoke", "knowledge_source", source.id, {"title": source.title}
    )
    return source


async def delete_source(db: AsyncSession, source_id: uuid.UUID, actor_id: uuid.UUID | None) -> None:
    source = await get_source(db, source_id)
    title = source.title
    await db.execute(delete(RAGDocument).where(RAGDocument.source_id == source_id))
    await db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
    from app.services import audit

    await audit.record(
        db, actor_id, "knowledge_delete", "knowledge_source", source_id, {"title": title}
    )


async def reembed(
    db: AsyncSession,
    source_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    embedder: EmbeddingProvider | None = None,
) -> tuple[KnowledgeSource, int]:
    """Recompute every chunk embedding of a source with the active embedder."""
    embedder = embedder or get_embedder()
    source = await get_source(db, source_id)
    chunks = list(
        (
            await db.execute(
                select(RAGDocument)
                .where(RAGDocument.source_id == source_id)
                .order_by(RAGDocument.chunk_index)
            )
        ).scalars()
    )
    vectors = await _embed_chunks(embedder, source.title, [(c.heading, c.content) for c in chunks])
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_model = embedder.model_id
    await db.flush()
    from app.services import audit

    await audit.record(
        db,
        actor_id,
        "knowledge_reembed",
        "knowledge_source",
        source.id,
        {"model": embedder.model_id, "chunks": len(chunks)},
    )
    return source, len(chunks)


async def chunk_stats(
    db: AsyncSession, source_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, list[str]]]:
    if not source_ids:
        return {}
    rows = await db.execute(
        select(RAGDocument.source_id, RAGDocument.embedding_model, func.count())
        .where(RAGDocument.source_id.in_(source_ids))
        .group_by(RAGDocument.source_id, RAGDocument.embedding_model)
    )
    stats: dict[uuid.UUID, tuple[int, list[str]]] = {}
    for sid, model, count in rows:
        total, models = stats.get(sid, (0, []))
        stats[sid] = (total + int(count), sorted([*models, model]) if model else models)
    return stats
