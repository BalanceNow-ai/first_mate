"""Evidence revision bookkeeping shared by every capability.

Any change to supporting material (asset added/removed, measurement or observation
changed, equipment/vessel context corrected) calls :func:`bump`. It increments the job's
``evidence_revision`` — which makes earlier analysis runs stale at publication — marks
pending/draft analysis superseded, and invalidates confirmations that depended on the
changed material (SJ-09). Callers hold the job row lock (``access.job_for(lock=True)``).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.service_jobs import ServiceJob
from app.services.service_jobs import runs


async def bump(db: AsyncSession, job: ServiceJob, *, reason: str) -> int:  # noqa: ARG001 - reason for audit callers
    job.evidence_revision += 1
    await runs.supersede_for_job(db, job.id)
    await db.flush()
    return job.evidence_revision
