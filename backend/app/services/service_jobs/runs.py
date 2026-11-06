"""Background analysis runs bound to exact inputs (spec §10; SJ-07, SJ-21).

Life cycle: ``create`` (idempotent, records the job evidence revision, asset versions,
invoice revision, assignment, provider/model/config and an input digest) → ``claim``
(short UPDATE … RETURNING with a lease and a fencing token; no lock is held while the
provider runs) → provider call outside any transaction → ``publish`` (locks the job or invoice row, then the run,
checks the fencing token, then re-checks authorization and every bound version; stale
output is stored only as a ``superseded`` diagnostic and never published).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import case, literal, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import utcnow
from app.models.service_jobs import AnalysisRun, EvidenceAsset, Invoice, ServiceJob
from app.services.service_jobs import access


def digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def create(
    db: AsyncSession,
    *,
    kind: str,
    requested_by: uuid.UUID,
    job: ServiceJob | None = None,
    invoice: Invoice | None = None,
    assets: list[EvidenceAsset] = (),
    assignment_id: uuid.UUID | None = None,
    provider: str | None = None,
    model: str | None = None,
    config_version: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[AnalysisRun, bool]:
    """Create (or return the existing, for a repeated idempotency key) run. Flushes only."""
    if idempotency_key:
        existing = (
            await db.execute(
                select(AnalysisRun).where(
                    AnalysisRun.requested_by == requested_by, AnalysisRun.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    asset_versions = {str(a.id): a.version for a in assets}
    bindings = {
        "kind": kind,
        "job": str(job.id) if job else None,
        "job_revision": job.evidence_revision if job else None,
        "invoice": str(invoice.id) if invoice else None,
        "invoice_revision": str(invoice.current_revision_id) if invoice and invoice.current_revision_id else None,
        "assets": asset_versions,
        "assignment": str(assignment_id) if assignment_id else None,
        "provider": provider,
        "model": model,
        "config": config_version,
    }
    run = AnalysisRun(
        kind=kind,
        job_id=job.id if job else None,
        invoice_id=invoice.id if invoice else None,
        requested_by=requested_by,
        job_revision=job.evidence_revision if job else None,
        asset_versions=asset_versions,
        invoice_revision_id=invoice.current_revision_id if invoice else None,
        assignment_id=assignment_id,
        provider=provider,
        model=model,
        config_version=config_version,
        input_digest=digest(bindings),
        idempotency_key=idempotency_key,
    )
    db.add(run)
    await db.flush()
    return run, True


async def claim(db: AsyncSession, run_id: uuid.UUID) -> uuid.UUID | None:
    """Claim a pending (or lease-expired) run; returns the fencing token. Commits."""
    settings = get_settings()
    now = utcnow()
    token = uuid.uuid4()
    claimed = (
        await db.execute(
            update(AnalysisRun)
            .where(
                AnalysisRun.id == run_id,
                AnalysisRun.attempts < settings.service_processing_max_attempts,
                or_(
                    AnalysisRun.status == "pending",
                    (AnalysisRun.status == "running") & (AnalysisRun.lease_expires_at < now),
                ),
            )
            .values(
                status="running",
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=settings.service_processing_lease_seconds),
                attempts=AnalysisRun.attempts + 1,
            )
            .returning(AnalysisRun.id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    await db.commit()
    return token if claimed else None


async def stale_reason(db: AsyncSession, run: AnalysisRun) -> str | None:
    """Why the run's inputs or authority are no longer current (None when still current)."""
    if run.job_id is not None:
        job = await db.get(ServiceJob, run.job_id, populate_existing=True)
        if job is None or job.deleted_at is not None:
            return "job_deleted"
        if run.job_revision is not None and job.evidence_revision != run.job_revision:
            return "evidence_changed"
        if not await access.still_authorized(db, run.job_id, run.requested_by, run.assignment_id):
            return "access_revoked"
    if run.invoice_id is not None:
        invoice = await db.get(Invoice, run.invoice_id, populate_existing=True)
        if invoice is None or invoice.deleted_at is not None:
            return "invoice_deleted"
        if run.invoice_revision_id is not None and invoice.current_revision_id != run.invoice_revision_id:
            return "invoice_revised"
    for asset_id, version in (run.asset_versions or {}).items():
        asset = await db.get(EvidenceAsset, uuid.UUID(asset_id), populate_existing=True)
        if asset is None or asset.status != "available" or asset.version != version:
            return "asset_changed"
    return None


async def publish(
    db: AsyncSession,
    run_id: uuid.UUID,
    token: uuid.UUID,
    output: dict,
    apply: Callable[[AsyncSession, AnalysisRun], Awaitable[None]] | None = None,
) -> str:
    """Publish a finished run if still owned and current. Returns the resulting status
    (``draft_ready``, ``superseded`` or ``lease_lost``). ``apply`` writes the derived
    records (observations, extraction fields…) in the same transaction. Commits.

    Lock order (D22 extension): the subject first — the job row (or the invoice row) —
    then the run. Holding the subject lock means no other transaction can bump the job's
    evidence revision (or revise the invoice) between the staleness check and the write."""
    subject = (
        await db.execute(select(AnalysisRun.job_id, AnalysisRun.invoice_id).where(AnalysisRun.id == run_id))
    ).first()
    if subject is None:
        await db.rollback()
        return "lease_lost"
    # (stale_reason re-reads both rows with populate_existing once they are locked)
    if subject.job_id is not None:
        await db.execute(select(ServiceJob.id).where(ServiceJob.id == subject.job_id).with_for_update())
    if subject.invoice_id is not None:
        await db.execute(select(Invoice.id).where(Invoice.id == subject.invoice_id).with_for_update())
    run = (
        await db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if run is None or run.lease_token != token:
        await db.rollback()
        return "lease_lost"
    if run.status == "superseded":  # the evidence changed while the provider ran
        run.lease_token = None
        run.lease_expires_at = None
        await db.commit()
        return "superseded"
    if run.status != "running":
        await db.rollback()
        return "lease_lost"
    reason = await stale_reason(db, run)
    if reason is not None:
        run.status = "superseded"
        run.output = {"stale": reason}  # a diagnostic only — never shown as a result
    else:
        run.status = "draft_ready"
        run.output = output
        if apply is not None:
            await apply(db, run)
    run.lease_token = None
    run.lease_expires_at = None
    await db.commit()
    return run.status


async def fail(db: AsyncSession, run_id: uuid.UUID, token: uuid.UUID, error: str) -> None:
    """Record a provider failure (honest "unavailable" state; retried while attempts remain)."""
    settings = get_settings()
    run = (
        await db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if run is None or run.lease_token != token:
        await db.rollback()
        return
    if run.status != "running":  # superseded meanwhile: never resurrect it for a retry
        run.lease_token = None
        run.lease_expires_at = None
        await db.commit()
        return
    run.error = error[:200]
    run.status = "failed" if run.attempts >= settings.service_processing_max_attempts else "pending"
    run.lease_token = None
    run.lease_expires_at = None
    await db.commit()


async def supersede_for_job(db: AsyncSession, job_id: uuid.UUID, kinds: tuple[str, ...] | None = None) -> None:
    """Mark earlier results for a job superseded (call, holding the job lock, when evidence
    changes) — pending, draft and *running* runs: a run whose provider call is in flight
    keeps its lease token, so its publication finds it superseded and publishes nothing."""
    q = update(AnalysisRun).where(
        AnalysisRun.job_id == job_id, AnalysisRun.status.in_(("pending", "running", "draft_ready"))
    )
    if kinds:
        q = q.where(AnalysisRun.kind.in_(kinds))
    await db.execute(
        q.values(
            status="superseded",
            output=case(
                (AnalysisRun.status == "running", literal({"stale": "evidence_changed"}, JSONB)),
                else_=AnalysisRun.output,
            ),
        ).execution_options(synchronize_session=False)
    )
