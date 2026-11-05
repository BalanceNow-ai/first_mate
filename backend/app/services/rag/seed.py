"""Ingest the synthetic knowledge fixtures in ``app/seed/knowledge`` (local/test only).

Every fixture is synthetic: publisher "Helm synthetic test fixture", licence
"Synthetic test fixture (no third-party content)", ``is_synthetic: true``. None of it
is real maintenance, safety or regulatory guidance.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.services.rag.chunking import parse_front_matter
from app.services.rag.ingestion import IngestResult, SourceMetadata, admit, ingest

SEED_DIR = Path(__file__).resolve().parents[2] / "seed" / "knowledge"
SYNTHETIC_PUBLISHER = "Helm synthetic test fixture"
SYNTHETIC_LICENCE = "Synthetic test fixture (no third-party content)"


def load_fixture(path: Path) -> tuple[SourceMetadata, str]:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    source = SourceMetadata.from_mapping(meta)
    if not (source.is_synthetic and source.publisher == SYNTHETIC_PUBLISHER and source.licence == SYNTHETIC_LICENCE):
        raise AppError(422, "not_synthetic", f"{path.name} is not a synthetic fixture")
    return source, body


def fixture_paths(directory: Path = SEED_DIR) -> list[Path]:
    return sorted(directory.glob("*.md"))


async def ingest_synthetic_corpus(
    db: AsyncSession,
    *,
    admit_sources: bool = False,
    actor_id: uuid.UUID | None = None,
    paths: list[Path] | None = None,
) -> list[IngestResult]:
    """Ingest (and optionally admit) the synthetic fixtures. Refused outside dev/test."""
    if not get_settings().is_local:
        raise AppError(409, "local_only", "Synthetic fixtures may only be ingested in development/test")
    results: list[IngestResult] = []
    for path in paths or fixture_paths():
        meta, body = load_fixture(path)
        result = await ingest(db, meta, body, actor_id=actor_id)
        if admit_sources and result.source.admission_status != "admitted":
            await admit(db, result.source.id, actor_id)
        results.append(result)
    return results
