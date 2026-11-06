"""Invoice extraction runs (workstream C).

``extract_invoice`` runs one claimed extraction (no DB lock or transaction is held while
the provider runs; publication re-checks the invoice revision and asset version).
``sweep_invoice_extractions`` re-runs pending runs whose broker message was lost or whose
lease expired (a retry after a provider outage).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select

from app.celery_app import celery
from app.database import utcnow
from app.models.service_jobs import AnalysisRun
from app.services.service_jobs import invoices
from app.tasks import run_async


@celery.task(name="app.tasks.service_invoices.extract_invoice")
def extract_invoice(run_id: str) -> dict:
    status = run_async(lambda db: invoices.execute_extraction_run(db, uuid.UUID(run_id)))
    return {"run_id": run_id, "status": status}


async def sweep(db, *, older_than_seconds: int = 60, limit: int = 50) -> list[str]:
    now = utcnow()
    ids = (
        await db.execute(
            select(AnalysisRun.id)
            .where(
                AnalysisRun.kind == "invoice_extraction",
                or_(
                    (AnalysisRun.status == "pending")
                    & (AnalysisRun.updated_at < now - timedelta(seconds=older_than_seconds)),
                    (AnalysisRun.status == "running") & (AnalysisRun.lease_expires_at < now),
                ),
            )
            .order_by(AnalysisRun.created_at)
            .limit(limit)
        )
    ).scalars()
    ids = list(ids)
    await db.commit()
    results = []
    for run_id in ids:
        results.append(f"{run_id}:{await invoices.execute_extraction_run(db, run_id)}")
    return results


@celery.task(name="app.tasks.service_invoices.sweep_invoice_extractions")
def sweep_invoice_extractions() -> dict:
    return {"runs": run_async(lambda db: sweep(db))}
