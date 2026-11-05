"""Vector retrieval over admitted knowledge with vessel applicability filtering.

Only chunks that (a) belong to an ``admitted`` source, (b) were embedded with the
active embedding model and (c) do not contradict the vessel's known facts are
returned. Legacy ``rag_documents`` rows without a ``source_id`` are never returned
(the inner join on ``knowledge_sources`` excludes them).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.ai import KnowledgeSource, RAGDocument
from app.services.fitment import VesselProfile, norm
from app.services.rag.embeddings import EmbeddingProvider, get_embedder

MATCH_BOOST = 0.03


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    title: str
    publisher: str | None
    url: str | None
    licence: str
    is_synthetic: bool
    domain: str
    heading: str | None
    content: str
    similarity: float
    applies_to: dict
    applicability: str  # general | matches | unconfirmed
    facts: list[dict] = field(default_factory=list)


def _values(raw) -> list[str]:
    values = raw if isinstance(raw, list) else [raw]
    return [norm(str(v)) for v in values if v]


def applicability(applies_to: dict | None, profile: VesselProfile | None) -> str | None:
    """Return ``general``/``matches``/``unconfirmed``, or ``None`` when the source
    contradicts the vessel's known facts and must be excluded."""
    applies_to = applies_to or {}
    if not applies_to:
        return "general"
    if profile is None:
        return "unconfirmed"
    outcome = "matches"
    vessel_makes = _values(applies_to.get("vessel_make"))
    vessel_models = _values(applies_to.get("vessel_model"))
    if vessel_makes and norm(profile.make) not in vessel_makes:
        return None
    if vessel_models and norm(profile.model) not in vessel_models:
        return None
    engine_makes = _values(applies_to.get("engine_make"))
    engine_models = _values(applies_to.get("engine_model"))
    if engine_makes or engine_models:
        engines = profile.engines
        if not engines:
            return "unconfirmed"
        best = None
        for engine in engines:
            if engine_makes and norm(engine.make) not in engine_makes:
                continue  # this engine contradicts the make
            if engine_models:
                if not engine.model:
                    best = best or "unconfirmed"
                    continue
                if norm(engine.model) not in engine_models:
                    continue
            best = "matches"
            break
        if best is None:
            return None
        if best == "unconfirmed":
            outcome = "unconfirmed"
    return outcome


async def retrieve(
    db: AsyncSession,
    query: str,
    profile: VesselProfile | None,
    *,
    domains: list[str] | None = None,
    top_k: int | None = None,
    min_similarity: float | None = None,
    embedder: EmbeddingProvider | None = None,
) -> list[RetrievedChunk]:
    settings = get_settings()
    embedder = embedder or get_embedder(settings)
    top_k = top_k or settings.rag_top_k
    threshold = settings.rag_min_similarity if min_similarity is None else min_similarity
    pool = max(settings.rag_candidate_pool, top_k * 4)
    [vector] = await embedder.embed([query])

    distance = RAGDocument.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(RAGDocument, KnowledgeSource, distance)
        .join(KnowledgeSource, KnowledgeSource.id == RAGDocument.source_id)
        .where(
            KnowledgeSource.admission_status == "admitted",
            RAGDocument.embedding_model == embedder.model_id,
            RAGDocument.embedding.isnot(None),
        )
        .order_by(distance)
        .limit(pool)
    )
    if domains:
        stmt = stmt.where(KnowledgeSource.domain.in_(domains))
    # HNSW search candidate list must cover the filtered pool.
    await db.execute(text(f"SET LOCAL hnsw.ef_search = {int(max(pool, 40))}"))
    rows = (await db.execute(stmt)).all()

    results: list[RetrievedChunk] = []
    for chunk, source, dist in rows:
        similarity = 1.0 - float(dist)
        if similarity < threshold:
            break  # ordered by distance
        fit = applicability(source.applies_to, profile)
        if fit is None:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                source_id=source.id,
                title=source.title,
                publisher=source.publisher,
                url=source.url,
                licence=source.licence,
                is_synthetic=source.is_synthetic,
                domain=source.domain,
                heading=chunk.heading,
                content=chunk.content,
                similarity=round(similarity, 4),
                applies_to=dict(source.applies_to or {}),
                applicability=fit,
                facts=list((chunk.metadata_ or {}).get("facts") or []),
            )
        )
    # Sources confirmed for this vessel rank slightly ahead of general ones at similar
    # similarity; the evidence threshold above is always applied to the raw similarity.
    results.sort(key=lambda c: -(c.similarity + (MATCH_BOOST if c.applicability == "matches" else 0.0)))
    return results[:top_k]
