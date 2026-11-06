"""Content-free service-job notifications through the existing outbox (spec §12)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import notifications
from app.services.notification_templates import SERVICE_JOB_UPDATES


async def notify(db: AsyncSession, user_id: uuid.UUID, kind: str, *, job_id: uuid.UUID | None, key: str) -> list[str]:
    """Queue "an update is available" for ``user_id``; ``key`` makes it idempotent.

    The payload holds only the update kind and the job id for the deep link."""
    if kind not in SERVICE_JOB_UPDATES:
        raise ValueError(f"unknown service-job update {kind}")
    return await notifications.enqueue(
        db,
        template="service_job_update",
        category="service",
        idempotency_key=f"service:{kind}:{key}",
        user_id=user_id,
        payload={"kind": kind, "job_id": str(job_id) if job_id else None},
    )
