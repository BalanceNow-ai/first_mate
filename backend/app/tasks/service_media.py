"""Asset scanning/decoding/derivatives, recovery and retention sweeps (workstream A1).

* ``process_asset`` — claim (lease + fencing token) → scan/decode/derive with no
  transaction open → publish only while still holding the lease.
* ``recover_assets`` — re-processes quarantined assets that were never processed (broker
  outage, scanner failure with attempts left) and ``processing`` assets whose worker lease
  expired (crash); a stale worker's later publication is refused by its fencing token.
* ``retention_sweep`` — removes abandoned upload intents (``SERVICE_UPLOAD_INTENT_HOURS``),
  retries object deletion for deleted assets, and notices-then-deletes never-assigned
  inactive drafts (``SERVICE_DRAFT_RETENTION_DAYS``; never with a retention hold, an open
  moderation case or a linked invoice).
"""

from __future__ import annotations

import uuid

from app.celery_app import celery
from app.tasks import run_async


@celery.task(name="app.tasks.service_media.process_asset")
def process_asset(asset_id: str) -> dict:
    from app.services.service_jobs import media

    async def _run(session):
        return {"asset_id": asset_id, "result": await media.process_asset(session, uuid.UUID(asset_id))}

    return run_async(_run)


@celery.task(name="app.tasks.service_media.recover_assets")
def recover_assets() -> dict:
    from app.services.service_jobs import media

    async def _run(session):
        ids = await media.recoverable_assets(session)
        queued = sum(1 for asset_id in ids if media.enqueue_processing(asset_id))
        return {"found": len(ids), "queued": queued}

    return run_async(_run)


@celery.task(name="app.tasks.service_media.retention_sweep")
def retention_sweep() -> dict:
    from app.services.service_jobs import media

    async def _run(session):
        return {
            "abandoned_intents_removed": await media.sweep_abandoned_intents(session),
            "deleted_objects_purged": await media.sweep_deleted_objects(session),
            "drafts": await media.sweep_inactive_drafts(session),
        }

    return run_async(_run)
