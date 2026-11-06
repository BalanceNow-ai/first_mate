"""Evidence observation analysis runs (workstream B).

``analyse_evidence`` executes one run: claim with a lease and fencing token, read the
authorised derivatives and call the vision provider with no transaction open, then
publish only if access and every bound version are still current
(``services/service_jobs/observations.execute``). ``sweep_pending`` re-queues runs whose
dispatch was lost or whose lease expired (schedule it in the beat to enable it).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select

from app.celery_app import celery
from app.database import utcnow
from app.models.service_jobs import AnalysisRun
from app.services.service_jobs import observations
from app.tasks import run_async

TASK_NAME = observations.ANALYSIS_TASK


@celery.task(name=TASK_NAME, acks_late=True)
def analyse_evidence(run_id: str) -> str:
    return run_async(lambda db: observations.execute(db, uuid.UUID(run_id)))


async def _pending_ids(db, older_than_seconds: int = 60, limit: int = 50) -> list[str]:
    now = utcnow()
    rows = await db.execute(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.kind == observations.ANALYSIS_KIND,
            or_(
                (AnalysisRun.status == "pending")
                & (AnalysisRun.updated_at < now - timedelta(seconds=older_than_seconds)),
                (AnalysisRun.status == "running") & (AnalysisRun.lease_expires_at < now),
            ),
        )
        .order_by(AnalysisRun.created_at)
        .limit(limit)
    )
    return [str(r[0]) for r in rows]


@celery.task(name="app.tasks.service_analysis.sweep_pending")
def sweep_pending() -> int:
    ids = run_async(_pending_ids)
    for run_id in ids:
        celery.send_task(TASK_NAME, args=[run_id], retry=False, ignore_result=True)
    return len(ids)
