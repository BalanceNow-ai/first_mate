"""Knowledge corpus administration (admin only).

Sources are ingested as ``pending`` and are never retrieved until an admin admits
them; admission requires a verified licence (synthetic fixtures are exempt only in
development/test). Revoked and deleted sources are excluded from retrieval at once.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import AdminUser
from app.models.ai import KnowledgeSource
from app.schemas.knowledge import (
    KnowledgeAdmitRequest,
    KnowledgeIngestRequest,
    KnowledgeIngestResponse,
    KnowledgeReembedResponse,
    KnowledgeSourceResponse,
)
from app.services.rag import ingestion

router = APIRouter(prefix="/knowledge", tags=["Knowledge Corpus"])


async def _responses(db: AsyncSession, sources: list[KnowledgeSource]) -> list[KnowledgeSourceResponse]:
    stats = await ingestion.chunk_stats(db, [s.id for s in sources])
    out = []
    for s in sources:
        count, models = stats.get(s.id, (0, []))
        out.append(
            KnowledgeSourceResponse.model_validate(
                {
                    **{c: getattr(s, c) for c in KnowledgeSourceResponse.model_fields if hasattr(s, c)},
                    "chunk_count": count,
                    "embedding_models": models,
                }
            )
        )
    return out


async def _one(db: AsyncSession, source: KnowledgeSource) -> KnowledgeSourceResponse:
    await db.refresh(source)
    return (await _responses(db, [source]))[0]


@router.get("/sources", response_model=list[KnowledgeSourceResponse])
async def list_sources(
    _: AdminUser,
    db: AsyncSession = Depends(get_db, scope="function"),
    admission_status: Literal["pending", "admitted", "revoked"] | None = Query(None, alias="status"),
    domain: str | None = Query(None, max_length=40),
    limit: int = Query(100, ge=1, le=500),
) -> list[KnowledgeSourceResponse]:
    """List knowledge sources with admission status, licence and synthetic flag."""
    stmt = select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc()).limit(limit)
    if admission_status:
        stmt = stmt.where(KnowledgeSource.admission_status == admission_status)
    if domain:
        stmt = stmt.where(KnowledgeSource.domain == domain)
    return await _responses(db, list((await db.execute(stmt)).scalars()))


@router.get("/sources/{source_id}", response_model=KnowledgeSourceResponse)
async def get_source(source_id: uuid.UUID, _: AdminUser, db: AsyncSession = Depends(get_db, scope="function")):
    return await _one(db, await ingestion.get_source(db, source_id))


@router.post(
    "/sources",
    response_model=KnowledgeIngestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def ingest_source(
    body: KnowledgeIngestRequest,
    admin: AdminUser,
    response: Response,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> KnowledgeIngestResponse:
    """Ingest a text/markdown document as a *pending* source (re-ingesting identical
    content is a no-op; changed content creates a new version and revokes the old)."""
    meta = ingestion.SourceMetadata(
        title=body.title,
        publisher=body.publisher,
        url=body.url,
        licence=body.licence,
        licence_verified=body.licence_verified,
        domain=body.domain,
        applies_to=dict(body.applies_to),
        is_synthetic=body.is_synthetic,
        version=body.version,
        facts=[f.model_dump(exclude_none=True) for f in body.facts],
    )
    result = await ingestion.ingest(db, meta, body.content, actor_id=admin.id)
    if result.status == "unchanged":
        response.status_code = status.HTTP_200_OK
    return KnowledgeIngestResponse(
        status=result.status,
        source=await _one(db, result.source),
        superseded_source_ids=result.superseded_ids,
    )


@router.post(
    "/sources/{source_id}/admit",
    response_model=KnowledgeSourceResponse,
    dependencies=[Depends(mutation_limit())],
)
async def admit_source(
    source_id: uuid.UUID,
    admin: AdminUser,
    body: KnowledgeAdmitRequest | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> KnowledgeSourceResponse:
    """Admit a source to retrieval (requires a verified licence)."""
    source = await ingestion.admit(db, source_id, admin.id, body.licence_verified if body else None)
    return await _one(db, source)


@router.post(
    "/sources/{source_id}/revoke",
    response_model=KnowledgeSourceResponse,
    dependencies=[Depends(mutation_limit())],
)
async def revoke_source(source_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")):
    """Revoke a source: it is excluded from retrieval immediately."""
    return await _one(db, await ingestion.revoke(db, source_id, admin.id))


@router.delete(
    "/sources/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def delete_source(
    source_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> Response:
    """Delete a source and all of its chunks."""
    await ingestion.delete_source(db, source_id, admin.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sources/{source_id}/reembed",
    response_model=KnowledgeReembedResponse,
    dependencies=[Depends(mutation_limit())],
)
async def reembed_source(source_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")):
    """Recompute the source's chunk embeddings with the active embedding model."""
    source, count = await ingestion.reembed(db, source_id, admin.id)
    return KnowledgeReembedResponse(source=await _one(db, source), chunks_embedded=count)
