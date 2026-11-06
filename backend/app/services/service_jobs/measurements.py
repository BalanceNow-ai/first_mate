"""Typed measurements with provenance and revisions (SJ-04, SJ-09; spec §4.2, §6.1).

* Semantics are explicit: hose internal vs external diameter, fitting OD, thread, clamp
  range, route length, bend radius, clearance. The written value, unit and precision are
  kept; :mod:`units` converts centrally without adding precision.
* State follows who recorded it and how — the owner's tape/caliper reading is
  ``owner_measured``; a marking the owner reads or a document they cite is
  ``owner_declared``; an image estimate (only with an explicit reference and uncertainty)
  stays ``unknown`` and can never be confirmed; the assigned contractor's own record or
  confirmation is ``contractor_confirmed`` with who/when/method.
* A marking without a unit ("316" on a clamp) is not a dimension, and a marking that says
  ID cannot be recorded as an OD (or vice versa).
* Records are never edited in place: a revision is a new row (``supersedes_id``); the old
  row becomes ``superseded`` and every preparation item depending on it is superseded by
  an unconfirmed copy that must be reviewed again.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import MEASUREMENT_DIMENSIONS, Measurement, Observation, PreparationItem, ServiceJob
from app.services import audit
from app.services.service_jobs import revisions, units
from app.services.service_jobs.access import JobActor
from app.services.service_jobs.observations import actor_role, get_asset, role_of

LENGTH_DIMENSIONS = (
    "hose_internal_diameter",
    "hose_external_diameter",
    "fitting_outside_diameter",
    "clamp_range",
    "route_length",
    "bend_radius",
    "clearance",
)
OWNER_METHODS = (
    "owner_tape",
    "owner_caliper",
    "owner_other",
    "marking_read",
    "source_document",
    "image_estimate_with_reference",
)
CONTRACTOR_METHODS = ("contractor_site", "marking_read", "source_document", "image_estimate_with_reference")
CONFIRMATION_METHODS = ("contractor_site", "marking_read", "source_document")
INACTIVE = ("superseded", "rejected")
# States a dimension check may rely on (never an estimate or a model suggestion).
USABLE_STATES = ("owner_measured", "owner_declared", "contractor_confirmed", "source_verified")
LIVE_ITEM_STATUSES = ("suggested", "needs_evidence", "contractor_confirmed")

BADGES = {
    "model_suggested": "Suggested",
    "owner_declared": "Owner declared",
    "owner_measured": "Owner measured",
    "contractor_confirmed": "Contractor confirmed",
    "source_verified": "Source verified",
    "rejected": "Rejected",
    "superseded": "Superseded",
    "unknown": "Estimate — unconfirmed",
}
METHOD_LABELS = {
    "marking_read": "read from a marking",
    "owner_tape": "tape measure",
    "owner_caliper": "caliper",
    "owner_other": "owner's own method",
    "image_estimate_with_reference": "estimated from a photo with a reference",
    "contractor_site": "measured on site",
    "source_document": "from a document",
    "unknown": "method not stated",
}


@dataclass
class MeasurementInput:
    dimension: str
    component: str
    value_text: str
    unit: str | None = None
    precision: str | None = None
    method: str = "owner_tape"
    tool: str | None = None
    reference: str | None = None
    source_asset_id: uuid.UUID | None = None
    source_region: dict | None = None
    source_observation_id: uuid.UUID | None = None
    notes: str | None = None


def _invalid(code: str, message: str) -> AppError:
    return AppError(422, code, message)


_ID_RE = re.compile(r"\b(I\.?D\.?|bore|inside|internal)\b", re.IGNORECASE)
_OD_RE = re.compile(r"\b(O\.?D\.?|outside|external)\b", re.IGNORECASE)
_UNIT_IN_TEXT = re.compile(r"\d\s*(mm|cm|m\b|in\b|inch|\"|″|ft\b|'|′)", re.IGNORECASE)


def _check_marking(obs: Observation, data: MeasurementInput, parsed: units.Length | None) -> None:
    """A marking can only become a dimension when its own text says so: the number as
    written, a length unit, and no contrary ID/OD semantics."""
    text = obs.extracted_text or ""
    if not text:
        raise _invalid("marking_has_no_text", "That observation has no readable marking text")
    if data.dimension in LENGTH_DIMENSIONS or parsed is not None:
        if not _UNIT_IN_TEXT.search(text):
            raise _invalid(
                "marking_has_no_unit",
                "The marking has no length unit, so it is not a dimension (for example 316 is usually a "
                "material grade). Measure the part and record the result instead.",
            )
        first_number = re.match(r"\s*(\d+(?:\.\d+)?|\d+[ -]\d+/\d+|\d+/\d+)", data.value_text)
        if first_number and first_number.group(1) not in text:
            raise _invalid("marking_value_mismatch", "The value is not what the marking text reads")
    if data.dimension == "hose_external_diameter" and _ID_RE.search(text) and not _OD_RE.search(text):
        raise _invalid(
            "marking_semantics_mismatch",
            "The marking states an internal diameter (ID); it cannot be recorded as the outside diameter",
        )
    if data.dimension in ("hose_internal_diameter",) and _OD_RE.search(text) and not _ID_RE.search(text):
        raise _invalid(
            "marking_semantics_mismatch",
            "The marking states an outside diameter (OD); it cannot be recorded as the internal diameter",
        )


def _state_for(actor: JobActor, method: str) -> str:
    if method == "image_estimate_with_reference":
        return "unknown"
    if actor.is_owner:
        return "owner_measured" if method in ("owner_tape", "owner_caliper", "owner_other") else "owner_declared"
    return "contractor_confirmed"


async def _validated(db: AsyncSession, actor: JobActor, data: MeasurementInput) -> dict:
    if data.dimension not in MEASUREMENT_DIMENSIONS:
        raise _invalid("invalid_dimension", "Unknown dimension type")
    allowed = OWNER_METHODS if actor.is_owner else CONTRACTOR_METHODS
    if data.method not in allowed:
        raise _invalid("method_not_allowed", f"Method {data.method} is not available to the {actor_role(actor)}")
    if data.method == "image_estimate_with_reference":
        if not data.reference or not data.precision or data.source_asset_id is None:
            raise _invalid(
                "estimate_needs_reference",
                "A photo estimate needs the photo, a visible reference of known size and an explicit uncertainty; "
                "an unscaled photo cannot give a dimension",
            )
    parsed: units.Length | None = None
    if data.dimension == "thread":
        if data.unit:
            raise _invalid("thread_has_no_unit", "Record a thread as written (e.g. M10x1.25, 1/2 NPT) without a unit")
    elif data.dimension in LENGTH_DIMENSIONS or data.unit:
        try:
            parsed = units.parse_length(data.value_text, data.unit)
        except units.UnitError as exc:
            raise _invalid("invalid_length", str(exc)) from None
        if data.dimension == "clamp_range" and not parsed.is_range:
            raise _invalid("clamp_range_needs_range", "A clamp range needs its minimum and maximum, e.g. 20-32 mm")
        if data.dimension not in ("clamp_range", "other", "clearance") and parsed.is_range:
            raise _invalid("single_value_required", "Record a single value for this dimension")
    if data.source_asset_id is not None:
        asset = await get_asset(db, actor.job.id, data.source_asset_id)
        if asset.status != "available":
            raise _invalid("asset_not_available", "That photo or document is not available yet")
    region = None
    if data.source_region is not None:
        from app.services.service_jobs.vision import _region  # shared normalisation

        if data.source_asset_id is None or (region := _region(data.source_region)) is None:
            raise _invalid("invalid_region", "A source region must be a normalised 0–1 box on the source photo")
    if data.source_observation_id is not None:
        obs = (
            await db.execute(
                select(Observation).where(
                    Observation.id == data.source_observation_id, Observation.job_id == actor.job.id
                )
            )
        ).scalar_one_or_none()
        if obs is None:
            raise not_found("Observation")
        if obs.state in INACTIVE:
            raise AppError(409, "observation_inactive", "That observation was rejected or superseded")
        if data.method == "marking_read":
            _check_marking(obs, data, parsed)
    elif data.method == "marking_read" and data.dimension in LENGTH_DIMENSIONS and parsed is None:
        raise _invalid("invalid_length", "A marking reading needs a unit")
    precision = data.precision or (parsed.implied_precision() if parsed else None)
    return {
        "dimension": data.dimension,
        "component": data.component,
        "value_text": data.value_text,
        "value_min": parsed.value_min if parsed else None,
        "value_max": parsed.value_max if parsed else None,
        "unit": parsed.unit if parsed else None,
        "normalized_min_mm": parsed.normalized_min_mm if parsed else None,
        "normalized_max_mm": parsed.normalized_max_mm if parsed else None,
        "precision": precision,
        "method": data.method,
        "tool": data.tool,
        "reference": data.reference,
        "source_asset_id": data.source_asset_id,
        "source_region": region,
        "source_observation_id": data.source_observation_id,
        "notes": data.notes,
    }


def _confirmation_fields(actor: JobActor, state: str, method: str) -> dict:
    if state != "contractor_confirmed":
        return {}
    return {"confirmed_by": actor.user_id, "confirmed_at": utcnow(), "confirmation_method": method}


async def record(db: AsyncSession, actor: JobActor, data: MeasurementInput) -> Measurement:
    """Record a new measurement (job row locked by the caller)."""
    fields = await _validated(db, actor, data)
    state = _state_for(actor, data.method)
    m = Measurement(
        job_id=actor.job.id,
        state=state,
        recorded_by=actor.user_id,
        job_revision=actor.job.evidence_revision + 1,
        **fields,
        **_confirmation_fields(actor, state, data.method),
    )
    db.add(m)
    await db.flush()
    await revisions.bump(db, actor.job, reason="measurement_recorded")
    return m


async def _locked(db: AsyncSession, job_id: uuid.UUID, measurement_id: uuid.UUID) -> Measurement:
    m = (
        await db.execute(
            select(Measurement)
            .where(Measurement.id == measurement_id, Measurement.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Measurement")
    return m


def _require_current(m: Measurement) -> None:
    if m.state in INACTIVE:
        raise AppError(
            409, "measurement_superseded", "This measurement was revised or rejected; use the current revision"
        )


async def revise(db: AsyncSession, actor: JobActor, measurement_id: uuid.UUID, data: MeasurementInput) -> Measurement:
    """A correction is a new revision; the old row and its dependants are superseded (SJ-09)."""
    old = await _locked(db, actor.job.id, measurement_id)
    _require_current(old)
    fields = await _validated(db, actor, data)
    state = _state_for(actor, data.method)
    new = Measurement(
        job_id=actor.job.id,
        state=state,
        recorded_by=actor.user_id,
        supersedes_id=old.id,
        job_revision=actor.job.evidence_revision + 1,
        **fields,
        **_confirmation_fields(actor, state, data.method),
    )
    old.state = "superseded"
    db.add(new)
    await db.flush()
    await invalidate_dependants(db, actor, {old.id: new.id}, reason="measurement_revised")
    await audit.record(
        db,
        actor.user_id,
        "service_measurement.revised",
        "service_measurement",
        old.id,
        {"job_id": str(actor.job.id), "replacement_id": str(new.id), "role": actor_role(actor)},
    )
    await revisions.bump(db, actor.job, reason="measurement_revised")
    return new


async def reject(db: AsyncSession, actor: JobActor, measurement_id: uuid.UUID, note: str | None) -> Measurement:
    m = await _locked(db, actor.job.id, measurement_id)
    _require_current(m)
    previous = m.state
    m.state = "rejected"
    await invalidate_dependants(db, actor, {m.id: None}, reason="measurement_rejected")
    await audit.record(
        db,
        actor.user_id,
        "service_measurement.rejected",
        "service_measurement",
        m.id,
        {"job_id": str(actor.job.id), "previous_state": previous, "role": actor_role(actor), "note": note},
    )
    await revisions.bump(db, actor.job, reason="measurement_rejected")
    return m


async def confirm(
    db: AsyncSession, actor: JobActor, measurement_id: uuid.UUID, *, method: str, note: str | None
) -> Measurement:
    """The assigned contractor confirms exactly this revision's value. Records who, what,
    which revision, how and when."""
    actor.require_contractor()
    if method not in CONFIRMATION_METHODS:
        raise _invalid("invalid_confirmation_method", "Confirm by site measurement, the marking or a document")
    m = await _locked(db, actor.job.id, measurement_id)
    _require_current(m)
    if m.method == "image_estimate_with_reference":
        raise AppError(
            409,
            "estimate_cannot_be_confirmed",
            "A photo estimate cannot be confirmed; measure on site and record the result",
        )
    if m.state == "contractor_confirmed":
        return m
    m.state = "contractor_confirmed"
    m.confirmed_by = actor.user_id
    m.confirmed_at = utcnow()
    m.confirmation_method = method
    await audit.record(
        db,
        actor.user_id,
        "service_measurement.confirmed",
        "service_measurement",
        m.id,
        {
            "job_id": str(actor.job.id),
            "organization_id": str(actor.organization_id),
            "dimension": m.dimension,
            "value_text": m.value_text,
            "unit": m.unit,
            "measurement_revision": str(m.id),
            "job_revision": actor.job.evidence_revision,
            "method": method,
            "note": note,
        },
    )
    await revisions.bump(db, actor.job, reason="measurement_confirmed")
    return m


async def invalidate_dependants(
    db: AsyncSession, actor: JobActor, changed: dict[uuid.UUID, uuid.UUID | None], *, reason: str
) -> list[PreparationItem]:
    """Supersede preparation items that depend on changed measurements (their confirmation
    and catalogue selection no longer hold) with unconfirmed copies to review again."""
    if not changed:
        return []
    keys = {str(k) for k in changed}
    items = list(
        (
            await db.execute(
                select(PreparationItem)
                .where(PreparationItem.job_id == actor.job.id, PreparationItem.status.in_(LIVE_ITEM_STATUSES))
                .order_by(PreparationItem.created_at, PreparationItem.id)
                .with_for_update()
            )
        ).scalars()
    )
    replaced: list[PreparationItem] = []
    for item in items:
        deps = [str(d) for d in item.depends_on_measurement_ids or []]
        if not keys.intersection(deps):
            continue
        new_deps = []
        for d in deps:
            if d in keys:
                successor = changed[uuid.UUID(d)]
                if successor is not None:
                    new_deps.append(str(successor))
            else:
                new_deps.append(d)
        note = "Re-check: a measurement this item depends on was revised or rejected"
        open_reqs = list(item.open_requirements or [])
        if note not in open_reqs:
            open_reqs.append(note)
        spec = dict(item.specification or {})
        spec.pop("evidence_request_ids", None)
        copy = PreparationItem(
            job_id=item.job_id,
            category=item.category,
            name=item.name,
            purpose=item.purpose,
            quantity=item.quantity if item.origin != "assistant" else None,
            unit=item.unit,
            quantity_basis=item.quantity_basis,
            open_requirements=open_reqs,
            specification=spec,
            depends_on_measurement_ids=new_deps,
            supporting_asset_ids=list(item.supporting_asset_ids or []),
            source_note=item.source_note,
            candidate_product_ids=list(item.candidate_product_ids or []),
            catalogue_match="candidates" if item.candidate_product_ids else "none",
            confirmed_product_id=None,
            origin=item.origin,
            status="suggested",
            created_by=item.created_by,
            job_revision=actor.job.evidence_revision + 1,
        )
        db.add(copy)
        await db.flush()
        item.status = "superseded"
        item.replaced_by_id = copy.id
        item.version += 1
        replaced.append(copy)
        await audit.record(
            db,
            actor.user_id,
            "service_preparation_item.superseded",
            "service_preparation_item",
            item.id,
            {"job_id": str(actor.job.id), "reason": reason, "replacement_id": str(copy.id)},
        )
    return replaced


async def list_for_job(db: AsyncSession, job_id: uuid.UUID, *, include_inactive: bool = True) -> list[Measurement]:
    q = select(Measurement).where(Measurement.job_id == job_id)
    if not include_inactive:
        q = q.where(Measurement.state.notin_(INACTIVE))
    return list((await db.execute(q.order_by(Measurement.created_at, Measurement.id))).scalars())


def current_value_mm(rows: list[Measurement], dimension: str) -> Measurement | None:
    """The best current, human-backed measurement of ``dimension`` (contractor first)."""
    candidates = [m for m in rows if m.dimension == dimension and m.state in USABLE_STATES]
    if not candidates:
        return None
    rank = {"contractor_confirmed": 0, "source_verified": 1, "owner_measured": 2, "owner_declared": 3}
    return sorted(candidates, key=lambda m: (rank[m.state], -m.created_at.timestamp()))[0]


def view(m: Measurement, job: ServiceJob, successor: uuid.UUID | None = None) -> dict:
    resolution = None
    if m.unit and m.value_text:
        try:
            resolution = units.fmt(units.parse_length(m.value_text, m.unit).resolution_mm)
        except units.UnitError:
            resolution = None
    method_label = METHOD_LABELS.get(m.method, m.method)
    recorder = role_of(job, m.recorded_by)
    return {
        "id": m.id,
        "job_id": m.job_id,
        "dimension": m.dimension,
        "component": m.component,
        "value_text": m.value_text,
        "value_min": units.fmt(m.value_min),
        "value_max": units.fmt(m.value_max),
        "unit": m.unit,
        "normalized_min_mm": units.fmt(m.normalized_min_mm),
        "normalized_max_mm": units.fmt(m.normalized_max_mm),
        "resolution_mm": resolution,
        "precision": m.precision,
        "method": m.method,
        "tool": m.tool,
        "reference": m.reference,
        "thread": units.parse_thread(m.value_text) if m.dimension == "thread" else None,
        "source_asset_id": m.source_asset_id,
        "source_region": m.source_region,
        "source_observation_id": m.source_observation_id,
        "state": m.state,
        "provenance": {
            "badge": m.state,
            "label": f"{BADGES.get(m.state, m.state)} ({method_label})",
            "recorded_by": m.recorded_by,
            "recorded_by_role": recorder,
            "method": m.method,
        },
        "recorded_by": m.recorded_by,
        "confirmation": (
            {"confirmed_by": m.confirmed_by, "confirmed_at": m.confirmed_at, "method": m.confirmation_method}
            if m.confirmed_by
            else None
        ),
        "supersedes_id": m.supersedes_id,
        "superseded_by_id": successor,
        "is_current": m.state not in INACTIVE,
        "job_revision": m.job_revision,
        "notes": m.notes,
        "created_at": m.created_at,
    }


def views(rows: list[Measurement], job: ServiceJob) -> list[dict]:
    successor = {m.supersedes_id: m.id for m in rows if m.supersedes_id}
    return [view(m, job, successor.get(m.id)) for m in rows]
