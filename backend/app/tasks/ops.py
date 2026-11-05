"""Operational tasks: worker/beat heartbeat recorded for the readiness endpoint."""

from __future__ import annotations

import socket

from sqlalchemy.dialects.postgresql import insert

from app.celery_app import celery
from app.database import utcnow
from app.models.ops import WorkerHeartbeat
from app.tasks import run_async


async def record_heartbeat(session, name: str) -> None:
    stmt = insert(WorkerHeartbeat).values(name=name, last_seen_at=utcnow(), details={"host": socket.gethostname()})
    stmt = stmt.on_conflict_do_update(
        index_elements=[WorkerHeartbeat.name],
        set_={"last_seen_at": stmt.excluded.last_seen_at, "details": stmt.excluded.details},
    )
    await session.execute(stmt)


@celery.task(name="app.tasks.ops.heartbeat")
def heartbeat() -> str:
    """Scheduled by beat, executed by a worker: proves both are alive."""
    run_async(lambda s: record_heartbeat(s, "celery"))
    return "ok"
