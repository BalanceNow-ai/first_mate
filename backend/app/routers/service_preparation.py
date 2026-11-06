"""Observations, measurements, preparation items, briefs, scope revisions/decisions (workstream B).

Every endpoint resolves access with :func:`access.job_for` for its section (evidence,
measurements, preparation or scope): owner, or an assigned member of the live accepted
assignment holding that section. Anyone else gets 404; an unshared section is 403.
Mutations lock the job row first (then child rows). Model/OCR output never reaches the
measurement, preparation-confirmation or scope-decision paths.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.schemas.service_preparation import (
    AnalysisRequest,
    AnalysisRunResponse,
    AnalysisStatusResponse,
    BriefAcknowledge,
    BriefAcknowledgeResponse,
    BriefPublish,
    BriefResponse,
    CatalogueMatch,
    ItemConfirm,
    ItemEvidenceRequest,
    ItemEvidenceResponse,
    ItemReject,
    ItemReplace,
    MeasurementConfirm,
    MeasurementCreate,
    MeasurementResponse,
    NoteBody,
    ObservationCorrection,
    ObservationNote,
    ObservationResponse,
    PreparationItemCreate,
    PreparationItemResponse,
    ScopeCreate,
    ScopeDecisionCreate,
    ScopeDecisionResponse,
    ScopeResponse,
)
from app.services.service_jobs import access, vision
from app.services.service_jobs import briefs as bsvc
from app.services.service_jobs import measurements as msvc
from app.services.service_jobs import observations as osvc
from app.services.service_jobs import preparation as psvc
from app.services.service_jobs import scope as ssvc

router = APIRouter(prefix="/service-jobs", tags=["Service preparation"])
Mutation = [Depends(mutation_limit())]
IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,100}$")


def _idempotency(key: str | None) -> str:
    if key is None or not IDEMPOTENCY_KEY.match(key):
        raise AppError(
            400,
            "idempotency_key_required",
            "An Idempotency-Key header of 8-100 characters (letters, digits, _ - : .) is required",
        )
    return key


def _region(r) -> dict | None:
    return r.model_dump() if r is not None else None


# ====================================================================== analysis
@router.get("/{job_id}/analysis", response_model=AnalysisStatusResponse)
async def analysis_status(
    job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    """Whether photo analysis is available (honest status) and this job's recent runs."""
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    return {**vision.availability(), "runs": [osvc.run_view(r) for r in await osvc.list_runs(db, actor)]}


@router.post(
    "/{job_id}/analysis",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=Mutation,
)
async def request_analysis(
    job_id: uuid.UUID,
    response: Response,
    user_id: CurrentUserId,
    body: AnalysisRequest | None = None,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Queue observation analysis of the available photos/documents (all, or ``asset_ids``).
    Results are suggestions only. 503 ``analysis_unavailable`` when the provider is off."""
    key = _idempotency(idempotency_key)
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    run, created = await osvc.request_analysis(db, actor, body.asset_ids if body else None, key)
    await db.commit()
    if created:
        osvc.dispatch(run.id)
    else:
        response.status_code = status.HTTP_200_OK
    return osvc.run_view(run)


@router.get("/{job_id}/analysis/{run_id}", response_model=AnalysisRunResponse)
async def get_analysis(
    job_id: uuid.UUID, run_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    return osvc.run_view(await osvc.get_run(db, actor, run_id))


# ====================================================================== observations
@router.get("/{job_id}/observations", response_model=list[ObservationResponse])
async def list_observations(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    include_inactive: bool = Query(True),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """What the evidence appears to show (suggestions, notes, corrections) — not measurements."""
    actor = await access.job_for(db, user_id, job_id, section="evidence")
    return await osvc.list_for_job(db, actor, include_inactive=include_inactive)


async def _observation(db, actor, obs) -> dict:
    return (await osvc.views(db, actor.job, [obs]))[0]


@router.post(
    "/{job_id}/observations",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def add_observation_note(
    job_id: uuid.UUID,
    body: ObservationNote,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Add a note or annotation (optionally on a photo region)."""
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    obs = await osvc.add_note(
        db, actor, text=body.text, asset_id=body.asset_id, page=body.page, region=_region(body.region)
    )
    return await _observation(db, actor, obs)


@router.post("/{job_id}/observations/{obs_id}/reject", response_model=ObservationResponse, dependencies=Mutation)
async def reject_observation(
    job_id: uuid.UUID,
    obs_id: uuid.UUID,
    user_id: CurrentUserId,
    body: NoteBody | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    obs = await osvc.reject(db, actor, obs_id, body.note if body else None)
    return await _observation(db, actor, obs)


@router.post(
    "/{job_id}/observations/{obs_id}/supersede",
    response_model=ObservationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def supersede_observation(
    job_id: uuid.UUID,
    obs_id: uuid.UUID,
    body: ObservationCorrection,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Correct an observation; the original is kept, marked superseded."""
    actor = await access.job_for(db, user_id, job_id, section="evidence", lock=True)
    obs = await osvc.supersede(
        db,
        actor,
        obs_id,
        assertion=body.assertion,
        extracted_text=body.extracted_text,
        region=_region(body.region),
        page=body.page,
    )
    return await _observation(db, actor, obs)


# ====================================================================== measurements
def _minput(body: MeasurementCreate) -> msvc.MeasurementInput:
    data = body.model_dump()
    data["source_region"] = _region(body.source_region)
    return msvc.MeasurementInput(**data)


async def _measurement(db, actor, m) -> dict:
    rows = await msvc.list_for_job(db, actor.job.id)
    return next(v for v in msvc.views(rows, actor.job) if v["id"] == m.id)


@router.get("/{job_id}/measurements", response_model=list[MeasurementResponse])
async def list_measurements(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    include_inactive: bool = Query(True),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    actor = await access.job_for(db, user_id, job_id, section="measurements")
    rows = await msvc.list_for_job(db, job_id)
    out = msvc.views(rows, actor.job)
    return out if include_inactive else [v for v in out if v["is_current"]]


@router.post(
    "/{job_id}/measurements",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def record_measurement(
    job_id: uuid.UUID,
    body: MeasurementCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Record a typed dimension with its method; the state follows who measured and how."""
    actor = await access.job_for(db, user_id, job_id, section="measurements", lock=True)
    m = await msvc.record(db, actor, _minput(body))
    return await _measurement(db, actor, m)


@router.post(
    "/{job_id}/measurements/{measurement_id}/revise",
    response_model=MeasurementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def revise_measurement(
    job_id: uuid.UUID,
    measurement_id: uuid.UUID,
    body: MeasurementCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """A correction creates a new revision; dependent confirmations and items are superseded."""
    actor = await access.job_for(db, user_id, job_id, section="measurements", lock=True)
    m = await msvc.revise(db, actor, measurement_id, _minput(body))
    return await _measurement(db, actor, m)


@router.post(
    "/{job_id}/measurements/{measurement_id}/confirm", response_model=MeasurementResponse, dependencies=Mutation
)
async def confirm_measurement(
    job_id: uuid.UUID,
    measurement_id: uuid.UUID,
    body: MeasurementConfirm,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Assigned contractor confirms this exact revision's value (who/what/how/when recorded)."""
    actor = await access.job_for(db, user_id, job_id, section="measurements", lock=True)
    m = await msvc.confirm(db, actor, measurement_id, method=body.method, note=body.note)
    return await _measurement(db, actor, m)


@router.post(
    "/{job_id}/measurements/{measurement_id}/reject", response_model=MeasurementResponse, dependencies=Mutation
)
async def reject_measurement(
    job_id: uuid.UUID,
    measurement_id: uuid.UUID,
    user_id: CurrentUserId,
    body: NoteBody | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    actor = await access.job_for(db, user_id, job_id, section="measurements", lock=True)
    m = await msvc.reject(db, actor, measurement_id, body.note if body else None)
    return await _measurement(db, actor, m)


# ====================================================================== preparation
def _iinput(body: PreparationItemCreate) -> psvc.ItemInput:
    data = body.model_dump(exclude={"expected_version"})
    return psvc.ItemInput(**data)


async def _item(db, actor, item) -> dict:
    return (await psvc.views(db, actor.job, [item]))[0]


@router.get("/{job_id}/preparation-items", response_model=list[PreparationItemResponse])
async def list_preparation_items(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    include_inactive: bool = Query(True),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Provisional/confirmed items with provenance, open requirements and live catalogue facts."""
    actor = await access.job_for(db, user_id, job_id, section="preparation")
    items = await psvc.list_items(db, actor.job, include_inactive=include_inactive)
    return await psvc.views(db, actor.job, items)


@router.post("/{job_id}/preparation-items/suggest", response_model=list[PreparationItemResponse], dependencies=Mutation)
async def suggest_preparation_items(
    job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    """Add deterministic provisional suggestions (no quantities invented); returns active items."""
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    await psvc.suggest(db, actor)
    items = await psvc.list_items(db, actor.job, include_inactive=False)
    return await psvc.views(db, actor.job, items)


@router.post(
    "/{job_id}/preparation-items",
    response_model=PreparationItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def create_preparation_item(
    job_id: uuid.UUID,
    body: PreparationItemCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    item = await psvc.create_item(db, actor, _iinput(body))
    return await _item(db, actor, item)


@router.post(
    "/{job_id}/preparation-items/{item_id}/confirm", response_model=PreparationItemResponse, dependencies=Mutation
)
async def confirm_preparation_item(
    job_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemConfirm,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Contractor confirms the requirement (not a catalogue match, stock or price)."""
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    item = await psvc.confirm(
        db,
        actor,
        item_id,
        expected_version=body.expected_version,
        quantity=body.quantity,
        unit=body.unit,
        quantity_basis=body.quantity_basis,
        note=body.note,
    )
    return await _item(db, actor, item)


@router.post(
    "/{job_id}/preparation-items/{item_id}/replace",
    response_model=PreparationItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def replace_preparation_item(
    job_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemReplace,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Contractor replaces an item with their own requirement; the original points to it."""
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    item = await psvc.replace(db, actor, item_id, _iinput(body), expected_version=body.expected_version)
    return await _item(db, actor, item)


@router.post(
    "/{job_id}/preparation-items/{item_id}/reject", response_model=PreparationItemResponse, dependencies=Mutation
)
async def reject_preparation_item(
    job_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    body: ItemReject | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    item = await psvc.reject(
        db, actor, item_id, expected_version=body.expected_version if body else None, note=body.note if body else None
    )
    return await _item(db, actor, item)


@router.post(
    "/{job_id}/preparation-items/{item_id}/request-evidence",
    response_model=ItemEvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def request_item_evidence(
    job_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemEvidenceRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Contractor asks the owner for a specific view/measurement for this item."""
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    item, request = await psvc.request_evidence(
        db,
        actor,
        item_id,
        expected_version=body.expected_version,
        category=body.category,
        prompt=body.prompt,
        reason=body.reason,
        measurement_dimension=body.measurement_dimension,
        priority=body.priority,
    )
    return {"item": await _item(db, actor, item), "evidence_request": request}


@router.post(
    "/{job_id}/preparation-items/{item_id}/catalogue-match",
    response_model=PreparationItemResponse,
    dependencies=Mutation,
)
async def confirm_catalogue_match(
    job_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CatalogueMatch,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Contractor confirms a real catalogue product meets the confirmed requirement."""
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    item = await psvc.confirm_catalogue_match(
        db, actor, item_id, body.product_id, expected_version=body.expected_version
    )
    return await _item(db, actor, item)


# ====================================================================== briefs
@router.post(
    "/{job_id}/briefs/preview", response_model=BriefResponse, status_code=status.HTTP_201_CREATED, dependencies=Mutation
)
async def preview_brief(
    job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    """Owner: snapshot exactly what the assigned contractor would receive, with recipients."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    brief = await bsvc.preview(db, actor)
    return await bsvc.view(db, actor, brief)


@router.get("/{job_id}/briefs", response_model=list[BriefResponse])
async def list_briefs(job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")):
    """Owner: every revision. Contractor: published revisions for their assignment (no content)."""
    actor = await access.job_for(db, user_id, job_id, section="preparation")
    return [await bsvc.view(db, actor, b, with_content=False) for b in await bsvc.list_briefs(db, actor)]


@router.get("/{job_id}/briefs/{brief_id}", response_model=BriefResponse)
async def get_brief(
    job_id: uuid.UUID, brief_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    actor = await access.job_for(db, user_id, job_id, section="preparation")
    return await bsvc.view(db, actor, await bsvc.get_brief(db, actor, brief_id))


@router.post("/{job_id}/briefs/{brief_id}/publish", response_model=BriefResponse, dependencies=Mutation)
async def publish_brief(
    job_id: uuid.UUID,
    brief_id: uuid.UUID,
    user_id: CurrentUserId,
    body: BriefPublish | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Owner publishes the exact preview (optionally quoting its digest)."""
    actor = await access.job_for(db, user_id, job_id, owner_only=True, lock=True)
    brief = await bsvc.publish(db, actor, brief_id, body.content_digest if body else None)
    return await bsvc.view(db, actor, brief)


@router.post(
    "/{job_id}/briefs/{brief_id}/acknowledgements",
    response_model=BriefAcknowledgeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def acknowledge_brief(
    job_id: uuid.UUID,
    brief_id: uuid.UUID,
    body: BriefAcknowledge,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Contractor: reviewed / incomplete (+ requested view) / limitations acknowledged / confirmed."""
    actor = await access.job_for(db, user_id, job_id, section="preparation", lock=True)
    ack, request = await bsvc.acknowledge(
        db,
        actor,
        brief_id,
        kind=body.kind,
        note=body.note,
        requested_view=body.requested_view.model_dump() if body.requested_view else None,
    )
    return {"acknowledgement": ack, "evidence_request": request}


@router.get("/{job_id}/briefs/{brief_id}/export", response_class=HTMLResponse)
async def export_brief(
    job_id: uuid.UUID, brief_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> HTMLResponse:
    """Printable, inert HTML of the brief (escaped; authorized like the job; not cached)."""
    actor = await access.job_for(db, user_id, job_id, section="preparation")
    data = await bsvc.view(db, actor, await bsvc.get_brief(db, actor, brief_id))
    return HTMLResponse(
        bsvc.export_html(data),
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Content-Disposition": f'attachment; filename="service-brief-r{int(data["revision_number"])}.html"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'",
            "Referrer-Policy": "no-referrer",
        },
    )


# ====================================================================== scope
@router.get("/{job_id}/scopes", response_model=list[ScopeResponse])
async def list_scopes(job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")):
    """Every scope revision with its decision (oldest first; ``is_current`` marks the latest)."""
    await access.job_for(db, user_id, job_id, section="scope")
    return await ssvc.views(db, job_id)


@router.get("/{job_id}/scopes/{scope_id}", response_model=ScopeResponse)
async def get_scope(
    job_id: uuid.UUID, scope_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    await access.job_for(db, user_id, job_id, section="scope")
    await ssvc.get_revision(db, job_id, scope_id)
    return next(v for v in await ssvc.views(db, job_id) if v["id"] == scope_id)


@router.post(
    "/{job_id}/scopes", response_model=ScopeResponse, status_code=status.HTTP_201_CREATED, dependencies=Mutation
)
async def propose_scope(
    job_id: uuid.UUID, body: ScopeCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
):
    """Assigned contractor proposes a scope revision (a later one is a change superseding it)."""
    actor = await access.job_for(db, user_id, job_id, section="scope", lock=True)
    rev = await ssvc.propose(
        db,
        actor,
        ssvc.ScopeInput(
            summary=body.summary,
            tasks=[t.model_dump() for t in body.tasks],
            estimate_lines=[line.model_dump() for line in body.estimate_lines],
            currency=body.currency,
            exclusions=body.exclusions,
            assumptions=body.assumptions,
            supersedes_id=body.supersedes_id,
        ),
    )
    return next(v for v in await ssvc.views(db, job_id) if v["id"] == rev.id)


@router.post(
    "/{job_id}/scopes/{scope_id}/decision",
    response_model=ScopeDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def decide_scope(
    job_id: uuid.UUID,
    scope_id: uuid.UUID,
    body: ScopeDecisionCreate,
    response: Response,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """The job owner accepts / rejects / requests changes to ONE exact revision (quote its
    ``content_digest``). Requires an ``Idempotency-Key``; a repeat returns the decision (200)."""
    key = _idempotency(idempotency_key)
    actor = await access.job_for(db, user_id, job_id, section="scope", lock=True)
    decision, created = await ssvc.decide(
        db,
        actor,
        scope_id,
        decision=body.decision,
        revision_digest=body.revision_digest,
        note=body.note,
        idempotency_key=key,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return ssvc.decision_view(decision)
