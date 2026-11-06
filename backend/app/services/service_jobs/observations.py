"""Observations of evidence and the evidence-analysis runs that propose them (SJ-02, SJ-20).

An observation is what a photo or document *appears to show* — "image text appears to read
25 mm ID" — with its source region, origin and uncertainty. It is never a measured
dimension (see :mod:`measurements`), a decision or a permission. Model/OCR output is always
``model_suggested``; people can reject it, supersede it with a correction, or add notes.

Analysis: ``request_analysis`` creates a run bound to the job evidence revision and the
exact asset versions (``runs.create``); ``execute`` claims it, reads the authorised
derivatives and calls the provider **outside any transaction**, then publishes through
``runs.publish``, which re-checks access and versions. Stale output is never published.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    AnalysisRun,
    EvidenceAsset,
    EvidenceRequest,
    JobAccessDetails,
    JobAssignmentMember,
    Observation,
    ServiceJob,
)
from app.models.vessel import Vessel
from app.services import audit
from app.services.service_jobs import access, revisions, runs, storage, vision
from app.services.service_jobs.access import JobActor
from app.services.service_jobs.notify import notify

logger = logging.getLogger(__name__)

ANALYSIS_KIND = "evidence_observations"
ANALYSABLE_PURPOSES = ("job_photo", "job_document")
INACTIVE_STATES = ("rejected", "superseded")
ANALYSIS_TASK = "app.tasks.service_analysis.analyse_evidence"


# ---------------------------------------------------------------------- shared helpers
def actor_role(actor: JobActor) -> str:
    return "owner" if actor.is_owner else "contractor"


def human_state(actor: JobActor) -> str:
    """The state of a person's own statement: the owner declares; the assigned contractor
    confirms (with who/when recorded)."""
    return "owner_declared" if actor.is_owner else "contractor_confirmed"


def role_of(job: ServiceJob, user_id: uuid.UUID | None) -> str:
    if user_id is None:
        return "assistant"
    return "owner" if user_id == job.owner_id else "contractor"


async def assigned_member_ids(db: AsyncSession, actor_or_job) -> list[uuid.UUID]:
    """Users currently assigned on the job's live accepted assignment."""
    job = actor_or_job.job if isinstance(actor_or_job, JobActor) else actor_or_job
    assignment = await access.live_assignment(db, job.id)
    if assignment is None or assignment.status != "accepted":
        return []
    rows = await db.execute(
        select(JobAssignmentMember.user_id).where(
            JobAssignmentMember.assignment_id == assignment.id, JobAssignmentMember.removed_at.is_(None)
        )
    )
    return [r[0] for r in rows]


async def notify_counterparty(db: AsyncSession, actor: JobActor, kind: str, key: str) -> None:
    """Content-free "an update is available" for the other side of the job."""
    if actor.is_owner:
        recipients = await assigned_member_ids(db, actor)
    else:
        recipients = [actor.job.owner_id]
    for user_id in recipients:
        await notify(db, user_id, kind, job_id=actor.job.id, key=f"{key}:{user_id}")


async def get_asset(db: AsyncSession, job_id: uuid.UUID, asset_id: uuid.UUID) -> EvidenceAsset:
    asset = (
        await db.execute(
            select(EvidenceAsset).where(
                EvidenceAsset.id == asset_id, EvidenceAsset.job_id == job_id, EvidenceAsset.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise not_found("Evidence asset")
    return asset


async def create_evidence_request(
    db: AsyncSession,
    actor: JobActor,
    *,
    category: str,
    prompt: str,
    reason: str,
    component: str | None = None,
    measurement_dimension: str | None = None,
    priority: str = "normal",
) -> EvidenceRequest:
    """A contractor's (or owner's) request for a specific view/measurement. Notifies the owner."""
    request = EvidenceRequest(
        job_id=actor.job.id,
        requested_by=actor.user_id,
        requester_role=actor_role(actor),
        organization_id=actor.organization_id,
        category=category,
        component=component,
        prompt=prompt,
        reason=reason,
        measurement_dimension=measurement_dimension,
        priority=priority,
    )
    db.add(request)
    await db.flush()
    if not actor.is_owner:
        await notify(db, actor.job.owner_id, "evidence_requested", job_id=actor.job.id, key=str(request.id))
    return request


# ---------------------------------------------------------------------- views
async def _uncertainties(db: AsyncSession, observations: Iterable[Observation]) -> dict[str, str | None]:
    run_ids = {o.analysis_run_id for o in observations if o.analysis_run_id}
    if not run_ids:
        return {}
    out: dict[str, str | None] = {}
    for run in (await db.execute(select(AnalysisRun).where(AnalysisRun.id.in_(run_ids)))).scalars():
        for item in (run.output or {}).get("observations", []) or []:
            if isinstance(item, dict) and item.get("observation_id"):
                out[item["observation_id"]] = item.get("uncertainty")
    return out


def _view(o: Observation, job: ServiceJob, uncertainty: str | None, superseded_by: uuid.UUID | None) -> dict:
    origin = "model" if o.analysis_run_id is not None or o.recorded_by is None else role_of(job, o.recorded_by)
    return {
        "id": o.id,
        "job_id": o.job_id,
        "asset_id": o.asset_id,
        "page": o.page,
        "region": o.region,
        "kind": o.kind,
        "assertion": o.assertion,
        "extracted_text": o.extracted_text,
        "state": o.state,
        "confidence": float(o.confidence) if o.confidence is not None else None,
        "uncertainty": uncertainty,
        "origin": origin,
        "analysis_run_id": o.analysis_run_id,
        "model_version": o.model_version,
        "recorded_by": o.recorded_by,
        "supersedes_id": o.supersedes_id,
        "superseded_by_id": superseded_by,
        "job_revision": o.job_revision,
        "is_measurement": False,
        "created_at": o.created_at,
    }


async def views(db: AsyncSession, job: ServiceJob, observations: list[Observation]) -> list[dict]:
    unc = await _uncertainties(db, observations)
    successor = {o.supersedes_id: o.id for o in observations if o.supersedes_id}
    return [_view(o, job, unc.get(str(o.id)), successor.get(o.id)) for o in observations]


async def list_for_job(db: AsyncSession, actor: JobActor, *, include_inactive: bool = True) -> list[dict]:
    q = select(Observation).where(Observation.job_id == actor.job.id)
    if not include_inactive:
        q = q.where(Observation.state.notin_(INACTIVE_STATES))
    rows = list((await db.execute(q.order_by(Observation.created_at, Observation.id))).scalars())
    return await views(db, actor.job, rows)


async def _locked_observation(db: AsyncSession, job_id: uuid.UUID, obs_id: uuid.UUID) -> Observation:
    obs = (
        await db.execute(
            select(Observation)
            .where(Observation.id == obs_id, Observation.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if obs is None:
        raise not_found("Observation")
    return obs


def _check_region(asset_id, page, region) -> dict | None:
    if region is None:
        return None
    if asset_id is None:
        raise AppError(422, "region_needs_asset", "A region must refer to a photo or document")
    normalised = vision._region(region)  # noqa: SLF001 - shared validation
    if normalised is None:
        raise AppError(422, "invalid_region", "Regions are normalised 0–1 boxes inside the image")
    return normalised


async def add_note(
    db: AsyncSession,
    actor: JobActor,
    *,
    text: str,
    asset_id: uuid.UUID | None = None,
    page: int | None = None,
    region: dict | None = None,
) -> Observation:
    """A person's note or annotation on the evidence (job row locked by the caller)."""
    if asset_id is not None:
        await get_asset(db, actor.job.id, asset_id)
    obs = Observation(
        job_id=actor.job.id,
        asset_id=asset_id,
        page=page,
        region=_check_region(asset_id, page, region),
        kind="owner_note" if actor.is_owner else "contractor_note",
        assertion=text,
        state=human_state(actor),
        recorded_by=actor.user_id,
        job_revision=actor.job.evidence_revision + 1,
    )
    db.add(obs)
    await revisions.bump(db, actor.job, reason="observation_added")
    await db.flush()
    return obs


def _may_change(actor: JobActor, obs: Observation) -> None:
    if obs.state in INACTIVE_STATES:
        raise AppError(409, "observation_inactive", "This observation was already rejected or superseded")
    if obs.recorded_by is not None and obs.analysis_run_id is None:
        # A person's note: its author, or the job owner.
        if not actor.is_owner and obs.recorded_by != actor.user_id:
            raise AppError(403, "not_author", "Only the author or the job owner can change this note")


async def reject(db: AsyncSession, actor: JobActor, obs_id: uuid.UUID, note: str | None) -> Observation:
    obs = await _locked_observation(db, actor.job.id, obs_id)
    _may_change(actor, obs)
    previous = obs.state
    obs.state = "rejected"
    await audit.record(
        db,
        actor.user_id,
        "service_observation.rejected",
        "service_observation",
        obs.id,
        {"job_id": str(actor.job.id), "previous_state": previous, "role": actor_role(actor), "note": note},
    )
    await revisions.bump(db, actor.job, reason="observation_rejected")
    return obs


async def supersede(
    db: AsyncSession,
    actor: JobActor,
    obs_id: uuid.UUID,
    *,
    assertion: str,
    extracted_text: str | None,
    region: dict | None,
    page: int | None,
) -> Observation:
    """Replace an observation with a person's correction; the original is kept as superseded."""
    old = await _locked_observation(db, actor.job.id, obs_id)
    _may_change(actor, old)
    kind = old.kind if old.kind in vision.PROVIDER_KINDS else ("owner_note" if actor.is_owner else "contractor_note")
    new = Observation(
        job_id=actor.job.id,
        asset_id=old.asset_id,
        page=page if page is not None else old.page,
        region=_check_region(old.asset_id, page, region) if region is not None else old.region,
        kind=kind,
        assertion=assertion,
        extracted_text=extracted_text,
        state=human_state(actor),
        recorded_by=actor.user_id,
        supersedes_id=old.id,
        job_revision=actor.job.evidence_revision + 1,
    )
    old.state = "superseded"
    db.add(new)
    await db.flush()
    await audit.record(
        db,
        actor.user_id,
        "service_observation.superseded",
        "service_observation",
        old.id,
        {"job_id": str(actor.job.id), "replacement_id": str(new.id), "role": actor_role(actor)},
    )
    await revisions.bump(db, actor.job, reason="observation_superseded")
    return new


# ---------------------------------------------------------------------- analysis runs
def run_view(run: AnalysisRun) -> dict:
    output = run.output or {}
    return {
        "id": run.id,
        "job_id": run.job_id,
        "kind": run.kind,
        "status": run.status,
        "provider": run.provider,
        "model": run.model,
        "job_revision": run.job_revision,
        "asset_ids": sorted(run.asset_versions or {}),
        "observation_count": len(output.get("observations", []) or []) if run.status == "draft_ready" else 0,
        "superseded_reason": output.get("stale") if run.status == "superseded" else None,
        "error": run.error,
        "attempts": run.attempts,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


async def list_runs(db: AsyncSession, actor: JobActor) -> list[AnalysisRun]:
    q = (
        select(AnalysisRun)
        .where(AnalysisRun.job_id == actor.job.id, AnalysisRun.kind == ANALYSIS_KIND)
        .order_by(AnalysisRun.created_at.desc())
        .limit(50)
    )
    return list((await db.execute(q)).scalars())


async def get_run(db: AsyncSession, actor: JobActor, run_id: uuid.UUID) -> AnalysisRun:
    run = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id, AnalysisRun.job_id == actor.job.id, AnalysisRun.kind == ANALYSIS_KIND
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise not_found("Analysis run")
    return run


async def request_analysis(
    db: AsyncSession, actor: JobActor, asset_ids: list[uuid.UUID] | None, idempotency_key: str
) -> tuple[AnalysisRun, bool]:
    """Create (idempotently) an observation run bound to the current evidence. Job row locked."""
    settings = get_settings()
    provider = vision.get_provider(settings)
    if not provider.available():
        raise AppError(
            503,
            "analysis_unavailable",
            "Photo analysis is unavailable right now. You can still add photos, record measurements "
            "and prepare the job manually.",
            extra={"provider": provider.name},
        )
    existing = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.requested_by == actor.user_id, AnalysisRun.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.job_id != actor.job.id:
            raise AppError(409, "idempotency_key_reused", "This Idempotency-Key was used for another request")
        return existing, False
    since = utcnow() - timedelta(days=1)
    used = (
        await db.execute(
            select(func.count())
            .select_from(AnalysisRun)
            .where(AnalysisRun.requested_by == actor.user_id, AnalysisRun.created_at >= since)
        )
    ).scalar_one()
    if used >= settings.service_analysis_runs_per_day:
        raise AppError(429, "analysis_quota_exceeded", "The daily photo-analysis limit has been reached")
    q = select(EvidenceAsset).where(
        EvidenceAsset.job_id == actor.job.id,
        EvidenceAsset.deleted_at.is_(None),
        EvidenceAsset.purpose.in_(ANALYSABLE_PURPOSES),
    )
    if asset_ids:
        q = q.where(EvidenceAsset.id.in_(asset_ids))
    assets = list((await db.execute(q.order_by(EvidenceAsset.created_at, EvidenceAsset.id))).scalars())
    if asset_ids and len({a.id for a in assets}) != len(set(asset_ids)):
        raise not_found("Evidence asset")
    if any(a.status != "available" or not a.derivative_key for a in assets) and asset_ids:
        raise AppError(422, "asset_not_available", "Only processed, available photos and documents can be analysed")
    assets = [a for a in assets if a.status == "available" and a.derivative_key]
    if not assets:
        raise AppError(422, "no_assets", "There are no available photos or documents to analyse")
    run, created = await runs.create(
        db,
        kind=ANALYSIS_KIND,
        requested_by=actor.user_id,
        job=actor.job,
        assets=assets,
        assignment_id=actor.assignment.id if actor.assignment else None,
        provider=provider.name,
        model=provider.model,
        config_version=vision.CONFIG_VERSION,
        idempotency_key=idempotency_key,
    )
    return run, created


def _send_task(run_id: uuid.UUID) -> None:
    if get_settings().app_env == "test":
        return  # tests drive ``execute`` directly
    try:
        from app.celery_app import celery

        celery.send_task(ANALYSIS_TASK, args=[str(run_id)], retry=False, ignore_result=True)
    except Exception as exc:  # broker outage: the run stays pending for the sweeper
        logger.error("Could not queue evidence analysis: %s", type(exc).__name__)


# Indirection so tests (and the local stack) can replace task dispatch.
dispatch = _send_task


@dataclass
class _Prepared:
    asset_id: str
    derivative_key: str
    media_type: str
    quality: dict
    pages: int | None


async def execute(db: AsyncSession, run_id: uuid.UUID) -> str:
    """Claim → read derivatives and call the provider with no transaction open → publish.

    Returns the final status (``draft_ready``, ``superseded``, ``pending``/``failed`` after a
    provider failure, ``not_claimed`` or ``lease_lost``)."""
    token = await runs.claim(db, run_id)
    if token is None:
        return "not_claimed"
    run = await db.get(AnalysisRun, run_id, populate_existing=True)
    job = await db.get(ServiceJob, run.job_id) if run and run.job_id else None
    if run is None or job is None:
        await db.rollback()
        return "lease_lost"
    prepared: list[_Prepared] = []
    for asset_id in sorted(run.asset_versions or {}):
        asset = await db.get(EvidenceAsset, uuid.UUID(asset_id))
        if asset is None or asset.status != "available" or not asset.derivative_key:
            continue  # publication will mark the run superseded (asset_changed)
        prepared.append(
            _Prepared(
                asset_id, asset.derivative_key, asset.detected_type or "image/jpeg", asset.quality or {}, asset.pages
            )
        )
    vessel_label = None
    if job.vessel_id:
        vessel = await db.get(Vessel, job.vessel_id)
        if vessel is not None:
            vessel_label = f"{vessel.year} {vessel.make} {vessel.model}"
    details = await db.get(JobAccessDetails, job.id)
    context = vision.masked_context(job, vessel_label, details.restricted if details else None)
    await db.rollback()  # no transaction or lock is held across storage/provider calls

    provider = vision.get_provider()
    results: list[tuple[str, list[vision.VisionObservation]]] = []
    try:
        store = storage.get_store()
        for item in prepared:
            data = store.get(item.derivative_key)
            observed = await provider.analyse(
                vision.VisionInput(
                    asset_id=item.asset_id,
                    sha256=vision.fixture_sha(data),
                    media_type=item.media_type,
                    data=data,
                    quality_hints=item.quality,
                    context=context,
                )
            )
            for o in observed:
                if item.pages is not None and o.page is not None and o.page > item.pages:
                    o.page = None
            results.append((item.asset_id, observed))
    except storage.ObjectStoreError:
        await runs.fail(db, run_id, token, "storage_unavailable")
        return (await db.get(AnalysisRun, run_id, populate_existing=True)).status
    except vision.VisionUnavailableError:
        await runs.fail(db, run_id, token, "analysis_unavailable")
        return (await db.get(AnalysisRun, run_id, populate_existing=True)).status

    output = {
        "provider": provider.name,
        "model": provider.model,
        "observations": [{"asset_id": aid, **o.as_json()} for aid, obs in results for o in obs],
    }

    async def apply(session: AsyncSession, published: AnalysisRun) -> None:
        await _publish_observations(session, published, results, f"{provider.name}:{provider.model or '-'}")

    return await runs.publish(db, run_id, token, output, apply)


async def _publish_observations(
    db: AsyncSession, run: AnalysisRun, results: list[tuple[str, list[vision.VisionObservation]]], model_version: str
) -> None:
    """Write the run's observations (all ``model_suggested``) and retire earlier suggestions
    for the same assets. Nothing else changes: no measurement, item, decision or grant."""
    asset_ids = [uuid.UUID(aid) for aid, _ in results]
    if asset_ids:
        await db.execute(
            update(Observation)
            .where(
                Observation.job_id == run.job_id,
                Observation.asset_id.in_(asset_ids),
                Observation.state == "model_suggested",
                Observation.analysis_run_id.isnot(None),
            )
            .values(state="superseded")
            .execution_options(synchronize_session=False)
        )
    stored: list[dict] = []
    for aid, observed in results:
        for o in observed:
            row = Observation(
                job_id=run.job_id,
                asset_id=uuid.UUID(aid),
                page=o.page,
                region=o.region,
                kind=o.kind,
                assertion=o.assertion,
                extracted_text=o.extracted_text,
                state="model_suggested",
                confidence=o.confidence,
                analysis_run_id=run.id,
                model_version=model_version,
                recorded_by=None,
                job_revision=run.job_revision or 0,
            )
            db.add(row)
            await db.flush()
            stored.append({"observation_id": str(row.id), "asset_id": aid, **o.as_json()})
    run.output = {**(run.output or {}), "observations": stored}
