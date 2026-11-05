import asyncio

from sqlalchemy import select

from app.database import async_session
from app.models.ops import WorkerHeartbeat
from app.tasks import ops


async def test_heartbeat_task_upserts_and_ready_reports(client):
    # Celery tasks run synchronously in a worker thread with their own event loop.
    await asyncio.to_thread(ops.heartbeat.run)
    await asyncio.to_thread(ops.heartbeat.run)
    async with async_session() as s:
        beats = (await s.execute(select(WorkerHeartbeat))).scalars().all()
    assert [b.name for b in beats] == ["celery"]
    body = (await client.get("/ready")).json()
    assert body["checks"]["workers"]["celery"]["fresh"] is True
