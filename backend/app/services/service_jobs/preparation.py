"""Provisional preparation items: likely parts, consumables and tools (SJ-05, SJ-09).

Suggestions are deterministic — built from the job description and the recorded
measurements, never from a model — and every one carries its purpose, source, supporting
evidence and explicit open requirements. Quantities stay unknown (``null``) unless a
person enters them with a basis: the assistant never invents a billable quantity.

Four distinct things are kept apart:

* a *possible item* (``status`` suggested / needs_evidence),
* an owner-confirmed *measurement* it depends on (see :mod:`measurements`),
* a *contractor-confirmed requirement* (``status`` contractor_confirmed),
* a *confirmed catalogue match* (``catalogue_match`` confirmed) — confirming a dimension
  or requirement is not confirming catalogue fit, stock or price.

Catalogue candidates come only from real active catalogue products, annotated with the
central fitment result and a separate, explicitly unverified dimension check. "No
matching product" is a valid outcome. Nothing here touches the cart: the owner adds a
product through the existing cart endpoint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.product import Product
from app.models.service_jobs import EvidenceRequest, Measurement, PreparationItem, ServiceJob
from app.models.vessel import Vessel
from app.services import audit, fitment
from app.services.service_jobs import access, units
from app.services.service_jobs import measurements as msvc
from app.services.service_jobs.access import JobActor, Visibility, check_version
from app.services.service_jobs.observations import actor_role, create_evidence_request, role_of

ACTIVE_STATUSES = ("suggested", "needs_evidence", "contractor_confirmed")
HOSE_WORDS = (
    "hose",
    "pump",
    "plumbing",
    "leak",
    "water",
    "bilge",
    "sink",
    "sanitation",
    "toilet",
    "coolant",
    "intake",
    "outlet",
    "drain",
)
FITTING_WORDS = ("fitting", "adaptor", "adapter", "thread", "barb", "elbow", "valve")
CANDIDATE_LIMIT = 5
COMMERCIAL_NOTE = (
    "Provisional preparation only — not a purchase, quote, work instruction or approval. "
    "The owner adds products to the cart; stock and price are checked then."
)


@dataclass
class ItemInput:
    category: str
    name: str
    purpose: str
    quantity: Decimal | None = None
    unit: str | None = None
    quantity_basis: str | None = None
    open_requirements: list[str] | None = None
    specification: dict | None = None
    depends_on_measurement_ids: list[uuid.UUID] | None = None
    supporting_asset_ids: list[uuid.UUID] | None = None
    source_note: str | None = None


# ---------------------------------------------------------------------- candidates
def _template_clause(template: str):
    name = func.lower(Product.name)
    role = func.coalesce(Product.part_role, "")
    if template == "hose":
        return (or_(name.like("%hose%"), func.lower(func.coalesce(Product.sub_category, "")) == "hose")) & not_(
            name.like("%clamp%")
        )
    if template == "clamps":
        return or_(name.like("%clamp%"), role.like("%clamp%"))
    if template == "fitting":
        return or_(name.like("%fitting%"), name.like("%adaptor%"), name.like("%adapter%"))
    if template == "tools":
        return func.lower(Product.category) == "tools"
    return None


def dimension_check(product: Product, template: str, od: Measurement | None) -> dict:
    """A *dimension-only* comparison, never a verified fit. For clamps the installed hose
    outside diameter must fall inside the product's stated range; the bore (ID) is never
    used in its place."""
    if template != "clamps":
        return {"status": "not_applicable", "reason": None}
    spec = product.specifications or {}
    rng = spec.get("clamp_range_mm")
    if od is None or od.normalized_min_mm is None:
        return {
            "status": "unknown",
            "reason": "Hose outside diameter not recorded — a clamp sized from the bore (ID) is not assumed to fit",
        }
    if not (isinstance(rng, list) and len(rng) == 2):
        return {"status": "unknown", "reason": "The product has no stated clamp range"}
    try:
        lo, hi = Decimal(str(rng[0])), Decimal(str(rng[1]))
    except (ArithmeticError, ValueError):
        return {"status": "unknown", "reason": "The product's clamp range is unreadable"}
    od_mm = od.normalized_min_mm
    shown = f"{units.fmt(lo)}–{units.fmt(hi)} mm"
    if lo <= od_mm <= hi:
        return {
            "status": "range_includes_recorded_od",
            "reason": f"Stated range {shown} includes the recorded {units.fmt(od_mm)} mm hose OD "
            f"({msvc.BADGES.get(od.state, od.state).lower()}); not a verified fit",
        }
    return {
        "status": "range_excludes_recorded_od",
        "reason": f"Stated range {shown} does not include the recorded {units.fmt(od_mm)} mm hose OD",
    }


async def _profile(db: AsyncSession, job: ServiceJob) -> fitment.VesselProfile | None:
    if job.vessel_id is None:
        return None
    vessel = (
        await db.execute(select(Vessel).where(Vessel.id == job.vessel_id, Vessel.user_id == job.owner_id))
    ).scalar_one_or_none()
    return await fitment.load_vessel_profile(db, vessel) if vessel else None


async def find_candidates(
    db: AsyncSession, template: str, profile: fitment.VesselProfile | None, od: Measurement | None
) -> list[uuid.UUID]:
    clause = _template_clause(template)
    if clause is None:
        return []
    products = list(
        (
            await db.execute(
                select(Product)
                .where(Product.is_active.is_(True), clause)
                .order_by(Product.name, Product.id)
                .limit(CANDIDATE_LIMIT * 3)
            )
        ).scalars()
    )
    fit = await fitment.evaluate_products(db, products, profile) if profile else {}
    out: list[uuid.UUID] = []
    for p in products:
        if p.id in fit and fit[p.id].status == "verified_mismatch":
            continue
        if dimension_check(p, template, od)["status"] == "range_excludes_recorded_od":
            continue
        out.append(p.id)
        if len(out) >= CANDIDATE_LIMIT:
            break
    return out


async def candidate_views(db: AsyncSession, job: ServiceJob, items: list[PreparationItem]) -> dict[str, dict]:
    """Live product facts for every candidate/confirmed product (refreshed on each read)."""
    ids: set[uuid.UUID] = set()
    for item in items:
        ids.update(uuid.UUID(str(i)) for i in item.candidate_product_ids or [])
        if item.confirmed_product_id:
            ids.add(item.confirmed_product_id)
    if not ids:
        return {}
    products = list((await db.execute(select(Product).where(Product.id.in_(ids)))).scalars())
    profile = await _profile(db, job)
    fit = await fitment.evaluate_products(db, products, profile) if profile else {}
    rows = await msvc.list_for_job(db, job.id, include_inactive=False)
    od = msvc.current_value_mm(rows, "hose_external_diameter")
    out: dict[str, dict] = {}
    for p in products:
        f = fit.get(p.id)
        out[str(p.id)] = {
            "product": p,
            "fitment": f,
            "od": od,
        }
    return out


def _candidate_json(entry: dict, template: str) -> dict:
    p: Product = entry["product"]
    f = entry["fitment"]
    return {
        "product_id": p.id,
        "sku": p.sku,
        "name": p.name,
        "brand": p.brand,
        "price_cents": p.price_cents,
        "sale_price_cents": p.sale_price_cents,
        "currency": "NZD",
        "is_active": p.is_active,
        "in_stock": p.stock_quantity > 0,
        "fitment_status": f.status if f else "unknown",
        "fitment_message": f.message if f else "No vessel on this job — vessel fitment is unknown",
        "dimension_check": dimension_check(p, template, entry["od"]),
    }


# ---------------------------------------------------------------------- views
def view(
    item: PreparationItem, job: ServiceJob, products: dict[str, dict], measurements: dict[str, Measurement]
) -> dict:
    template = (item.specification or {}).get("template", "")
    candidates = [
        _candidate_json(products[str(pid)], template)
        for pid in item.candidate_product_ids or []
        if str(pid) in products and products[str(pid)]["product"].is_active
    ]
    confirmed = (
        _candidate_json(products[str(item.confirmed_product_id)], template)
        if item.confirmed_product_id and str(item.confirmed_product_id) in products
        else None
    )
    deps = []
    for mid in item.depends_on_measurement_ids or []:
        m = measurements.get(str(mid))
        deps.append(
            {
                "measurement_id": mid,
                "dimension": m.dimension if m else None,
                "value_text": m.value_text if m else None,
                "unit": m.unit if m else None,
                "state": m.state if m else "unknown",
            }
        )
    requirement_state = {"suggested": "possible", "needs_evidence": "needs_evidence"}.get(item.status, item.status)
    return {
        "id": item.id,
        "job_id": item.job_id,
        "category": item.category,
        "name": item.name,
        "purpose": item.purpose,
        "quantity": units.fmt(item.quantity),
        "unit": item.unit,
        "quantity_basis": item.quantity_basis,
        "open_requirements": list(item.open_requirements or []),
        "specification": item.specification or {},
        "depends_on": deps,
        "supporting_asset_ids": list(item.supporting_asset_ids or []),
        "source_note": item.source_note,
        "origin": item.origin,
        "created_by_role": role_of(job, item.created_by) if item.origin != "assistant" else "assistant",
        "status": item.status,
        "requirement_state": requirement_state,
        "catalogue_match": item.catalogue_match,
        "candidates": candidates,
        "confirmed_product": confirmed,
        "confirmed_by": item.confirmed_by,
        "confirmed_by_other_organization": False,
        "confirmed_at": item.confirmed_at,
        "confirmed_job_revision": item.confirmed_job_revision,
        "evidence_changed_since_confirmation": bool(
            item.confirmed_job_revision is not None and item.confirmed_job_revision != job.evidence_revision
        ),
        "replaced_by_id": item.replaced_by_id,
        "evidence_request_ids": list((item.specification or {}).get("evidence_request_ids", [])),
        "job_revision": item.job_revision,
        "version": item.version,
        "commercial_note": COMMERCIAL_NOTE,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


async def list_items(db: AsyncSession, job: ServiceJob, *, include_inactive: bool = True) -> list[PreparationItem]:
    q = select(PreparationItem).where(PreparationItem.job_id == job.id)
    if not include_inactive:
        q = q.where(PreparationItem.status.in_(ACTIVE_STATUSES))
    return list((await db.execute(q.order_by(PreparationItem.created_at, PreparationItem.id))).scalars())


async def views(
    db: AsyncSession, job: ServiceJob, items: list[PreparationItem], vis: Visibility | None = None
) -> list[dict]:
    """Views of ``items``; with ``vis``, only what that reader may see (see :mod:`access`)."""
    if vis is not None:
        items = [i for i in items if vis.item(i)]
    products = await candidate_views(db, job, items)
    ms = {str(m.id): m for m in await msvc.list_for_job(db, job.id)}
    out = []
    for i in items:
        v = view(i, job, products, ms)
        if vis is not None and vis.foreign_people(i.confirmed_by):
            v["confirmed_by"] = None  # another organization's confirmation: identity withheld
            v["confirmed_by_other_organization"] = True
        out.append(v)
    return out


# ---------------------------------------------------------------------- suggestions
def _mtext(m: Measurement | None) -> str:
    if m is None:
        return ""
    return f"{m.value_text}{' ' + m.unit if m.unit and m.unit not in m.value_text else ''}"


async def suggest(db: AsyncSession, actor: JobActor) -> list[PreparationItem]:
    """Create deterministic provisional suggestions that do not exist yet (job row locked)."""
    job = actor.job
    rows = await msvc.list_for_job(db, job.id, include_inactive=False)
    text = " ".join(
        filter(None, [job.title, job.issue_description, job.affected_system, job.affected_equipment])
    ).lower()
    hose_dims = ("hose_internal_diameter", "hose_external_diameter", "route_length", "clamp_range")
    hose_job = any(w in text for w in HOSE_WORDS) or any(m.dimension in hose_dims for m in rows)
    fitting_job = any(w in text for w in FITTING_WORDS) or any(
        m.dimension in ("thread", "fitting_outside_diameter") for m in rows
    )
    existing = {
        (i.specification or {}).get("template")
        for i in await list_items(db, job, include_inactive=False)
        if i.origin == "assistant"
    }
    requests = list((await db.execute(select(EvidenceRequest).where(EvidenceRequest.job_id == job.id))).scalars())
    far_end_gap = any(r.category == "connections" and r.status in ("outstanding", "unavailable") for r in requests)
    access_known = any(r.category == "access_route" and r.status == "answered" for r in requests)
    profile = await _profile(db, job)

    idm = msvc.current_value_mm(rows, "hose_internal_diameter")
    odm = msvc.current_value_mm(rows, "hose_external_diameter")
    route = msvc.current_value_mm(rows, "route_length")
    thread = msvc.current_value_mm(rows, "thread")
    source = "Suggested from the job description and recorded measurements; provisional until the contractor confirms."
    supporting = sorted({str(m.source_asset_id) for m in rows if m.source_asset_id})
    templates: list[tuple[str, ItemInput]] = []
    if hose_job:
        reqs = ["Application not confirmed (e.g. potable water, sanitation, fuel, exhaust) — not inferred from photos"]
        if idm is None:
            reqs.append("Hose internal diameter (bore) not confirmed")
        if route is None:
            reqs.append("Length needed not known")
        else:
            reqs.append(f"Visible route {_mtext(route)} recorded; total length and allowance not confirmed")
        reqs.append("Far-end connection not visible" if far_end_gap else "Both hose ends not yet confirmed")
        templates.append(
            (
                "hose",
                ItemInput(
                    category="part",
                    name="Replacement hose",
                    purpose="Replace the leaking or damaged hose section",
                    unit="m",
                    open_requirements=reqs,
                    specification={
                        "internal_diameter": _mtext(idm) or None,
                        "internal_diameter_state": idm.state if idm else "unknown",
                        "application": None,
                    },
                    depends_on_measurement_ids=[m.id for m in (idm, route) if m],
                ),
            )
        )
        clamp_reqs = []
        if odm is None:
            clamp_reqs.append("Clamp range must cover the installed hose outside diameter — OD not recorded")
            if idm is not None:
                clamp_reqs.append(
                    f"The {_mtext(idm)} bore (ID) is not the clamp size; a clamp sized from the ID is not assumed"
                    " to fit"
                )
        else:
            clamp_reqs.append(f"Clamp range must include the recorded {_mtext(odm)} hose OD")
        clamp_reqs += [
            "Quantity depends on the number of connections — not confirmed",
            "Clamp material/grade not confirmed from photos",
        ]
        templates.append(
            (
                "clamps",
                ItemInput(
                    category="part",
                    name="Hose clamps",
                    purpose="Secure each hose end on its fitting",
                    unit="each",
                    open_requirements=clamp_reqs,
                    specification={
                        "required_od": _mtext(odm) or None,
                        "required_od_state": odm.state if odm else "unknown",
                    },
                    depends_on_measurement_ids=[m.id for m in (odm, idm) if m],
                ),
            )
        )
    if fitting_job or hose_job:
        templates.append(
            (
                "fitting",
                ItemInput(
                    category="part",
                    name="Hose fitting / adaptor (if the existing one is damaged)",
                    purpose="Connect the hose to the equipment if the existing fitting cannot be reused",
                    unit="each",
                    open_requirements=[
                        "Fitting thread not confirmed"
                        if thread is None or thread.state != "contractor_confirmed"
                        else "Thread recorded; fitting condition not confirmed",
                        "Whether the existing fitting can be reused needs site inspection",
                    ],
                    specification={"thread": _mtext(thread) or None},
                    depends_on_measurement_ids=[thread.id] if thread else [],
                ),
            )
        )
    tool_reqs = [] if access_known else ["Access route and working space not confirmed"]
    templates.append(
        (
            "tools",
            ItemInput(
                category="tool",
                name="Access and hand tools",
                purpose="Reach and work on the affected equipment (e.g. nut driver for clamps, hose cutter, torch, "
                "absorbent pads)",
                open_requirements=tool_reqs + ["Tool list to be confirmed by the contractor"],
                specification={},
            ),
        )
    )
    created: list[PreparationItem] = []
    for template, data in templates:
        if template in existing:
            continue
        od_for = odm if template == "clamps" else None
        candidates = await find_candidates(db, template, profile, od_for)
        item = PreparationItem(
            job_id=job.id,
            category=data.category,
            name=data.name,
            purpose=data.purpose,
            quantity=None,  # never invented
            unit=data.unit,
            quantity_basis=None,
            open_requirements=data.open_requirements or [],
            specification={"template": template, **(data.specification or {})},
            depends_on_measurement_ids=[str(i) for i in data.depends_on_measurement_ids or []],
            supporting_asset_ids=supporting,
            source_note=source,
            candidate_product_ids=[str(c) for c in candidates],
            catalogue_match="candidates" if candidates else "none",
            origin="assistant",
            status="suggested",
            created_by=None,
            job_revision=job.evidence_revision,
        )
        db.add(item)
        created.append(item)
    await db.flush()
    return created


# ---------------------------------------------------------------------- person actions
async def _validate_refs(db: AsyncSession, job: ServiceJob, data: ItemInput) -> tuple[list[str], list[str]]:
    mids = [str(i) for i in data.depends_on_measurement_ids or []]
    if mids:
        found = {
            str(r[0])
            for r in await db.execute(
                select(Measurement.id).where(
                    Measurement.job_id == job.id,
                    Measurement.id.in_([uuid.UUID(m) for m in mids]),
                    Measurement.state.notin_(msvc.INACTIVE),
                )
            )
        }
        if found != set(mids):
            raise not_found("Measurement")
    aids = [str(i) for i in data.supporting_asset_ids or []]
    if aids:
        from app.models.service_jobs import EvidenceAsset

        found = {
            str(r[0])
            for r in await db.execute(
                select(EvidenceAsset.id).where(
                    EvidenceAsset.job_id == job.id,
                    EvidenceAsset.id.in_([uuid.UUID(a) for a in aids]),
                    EvidenceAsset.deleted_at.is_(None),
                )
            )
        }
        if found != set(aids):
            raise not_found("Evidence asset")
    return mids, aids


def _quantity(actor: JobActor, data: ItemInput) -> None:
    if data.quantity is not None and not data.quantity_basis:
        raise AppError(
            422,
            "quantity_basis_required",
            "Say where the quantity comes from (e.g. 'two connections, contractor allowance +0.3 m')",
        )
    if data.quantity is not None and not data.unit:
        raise AppError(422, "unit_required", "A quantity needs a unit")


async def create_item(db: AsyncSession, actor: JobActor, data: ItemInput) -> PreparationItem:
    _quantity(actor, data)
    mids, aids = await _validate_refs(db, actor.job, data)
    if not actor.is_owner and (mids or aids):
        from app.models.service_jobs import EvidenceAsset

        vis = await access.visibility(db, actor)
        if mids:
            for m in (
                await db.execute(select(Measurement).where(Measurement.id.in_([uuid.UUID(x) for x in mids])))
            ).scalars():
                vis.require("measurements", m)
        if aids:
            for a in (
                await db.execute(select(EvidenceAsset).where(EvidenceAsset.id.in_([uuid.UUID(x) for x in aids])))
            ).scalars():
                if a.purpose not in ("job_photo", "job_document") or vis.other_contractor(a.uploaded_by):
                    raise not_found("Evidence asset")
                vis.require("assets", a)
    spec = dict(data.specification or {})
    spec.pop("evidence_request_ids", None)
    spec.pop("template", None)
    item = PreparationItem(
        job_id=actor.job.id,
        category=data.category,
        name=data.name,
        purpose=data.purpose,
        quantity=data.quantity,
        unit=data.unit,
        quantity_basis=(f"{actor_role(actor).capitalize()}: {data.quantity_basis}" if data.quantity_basis else None),
        open_requirements=list(data.open_requirements or []),
        specification=spec,
        depends_on_measurement_ids=mids,
        supporting_asset_ids=aids,
        source_note=data.source_note or f"Added by the {actor_role(actor)}",
        candidate_product_ids=[],
        catalogue_match="none",
        origin=actor_role(actor),
        status="suggested",
        created_by=actor.user_id,
        job_revision=actor.job.evidence_revision,
    )
    db.add(item)
    await db.flush()
    return item


async def _locked_item(db: AsyncSession, actor: JobActor, item_id: uuid.UUID) -> PreparationItem:
    """The item, locked (job row already locked by the caller), if the actor may act on it."""
    item = (
        await db.execute(
            select(PreparationItem)
            .where(PreparationItem.id == item_id, PreparationItem.job_id == actor.job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("Preparation item")
    if not actor.is_owner:
        vis = await access.visibility(db, actor)
        if item.origin == "contractor" and vis.other_contractor(item.created_by):
            raise not_found("Preparation item")  # another organization's item
        vis.require("items", item)
    return item


def _require_active(item: PreparationItem) -> None:
    if item.status not in ACTIVE_STATUSES:
        raise AppError(409, "item_inactive", "This item was rejected, replaced or superseded")


async def _deps_current(db: AsyncSession, item: PreparationItem) -> None:
    ids = [uuid.UUID(str(i)) for i in item.depends_on_measurement_ids or []]
    if not ids:
        return
    stale = (
        await db.execute(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.id.in_(ids), Measurement.state.in_(msvc.INACTIVE))
        )
    ).scalar_one()
    if stale:
        raise AppError(409, "dependency_superseded", "A measurement this item depends on has changed; review again")


async def confirm(
    db: AsyncSession,
    actor: JobActor,
    item_id: uuid.UUID,
    *,
    expected_version: int | None,
    quantity: Decimal | None,
    unit: str | None,
    quantity_basis: str | None,
    note: str | None,
) -> PreparationItem:
    """The contractor confirms the requirement (not a catalogue match, stock or price)."""
    actor.require_contractor()
    item = await _locked_item(db, actor, item_id)
    check_version(item.version, expected_version, "preparation item")
    _require_active(item)
    await _deps_current(db, item)
    if quantity is not None:
        _quantity(
            actor,
            ItemInput(
                category=item.category,
                name=item.name,
                purpose="",
                quantity=quantity,
                unit=unit or item.unit,
                quantity_basis=quantity_basis,
            ),
        )
        item.quantity = quantity
        item.unit = unit or item.unit
        item.quantity_basis = f"Contractor: {quantity_basis}"
    item.status = "contractor_confirmed"
    item.confirmed_by = actor.user_id
    item.confirmed_at = utcnow()
    item.confirmed_job_revision = actor.job.evidence_revision
    item.version += 1
    await audit.record(
        db,
        actor.user_id,
        "service_preparation_item.confirmed",
        "service_preparation_item",
        item.id,
        {
            "job_id": str(actor.job.id),
            "organization_id": str(actor.organization_id),
            "version": item.version,
            "job_revision": actor.job.evidence_revision,
            "quantity": units.fmt(item.quantity),
            "unit": item.unit,
            "note": note,
        },
    )
    return item


async def replace(
    db: AsyncSession, actor: JobActor, item_id: uuid.UUID, data: ItemInput, *, expected_version: int | None
) -> PreparationItem:
    """The contractor replaces an item with their own requirement (confirmed by them)."""
    actor.require_contractor()
    old = await _locked_item(db, actor, item_id)
    check_version(old.version, expected_version, "preparation item")
    _require_active(old)
    new = await create_item(db, actor, data)
    new.status = "contractor_confirmed"
    new.confirmed_by = actor.user_id
    new.confirmed_at = utcnow()
    new.confirmed_job_revision = actor.job.evidence_revision
    old.status = "replaced"
    old.replaced_by_id = new.id
    old.version += 1
    await db.flush()
    await audit.record(
        db,
        actor.user_id,
        "service_preparation_item.replaced",
        "service_preparation_item",
        old.id,
        {"job_id": str(actor.job.id), "replacement_id": str(new.id)},
    )
    return new


async def reject(
    db: AsyncSession, actor: JobActor, item_id: uuid.UUID, *, expected_version: int | None, note: str | None
) -> PreparationItem:
    item = await _locked_item(db, actor, item_id)
    check_version(item.version, expected_version, "preparation item")
    _require_active(item)
    if actor.is_owner and item.status == "contractor_confirmed":
        raise AppError(403, "contractor_requirement", "A contractor-confirmed requirement is changed by the contractor")
    item.status = "rejected"
    item.version += 1
    await audit.record(
        db,
        actor.user_id,
        "service_preparation_item.rejected",
        "service_preparation_item",
        item.id,
        {"job_id": str(actor.job.id), "role": actor_role(actor), "note": note},
    )
    return item


async def request_evidence(
    db: AsyncSession,
    actor: JobActor,
    item_id: uuid.UUID,
    *,
    expected_version: int | None,
    category: str,
    prompt: str,
    reason: str,
    measurement_dimension: str | None,
    priority: str,
) -> tuple[PreparationItem, EvidenceRequest]:
    actor.require_contractor()
    item = await _locked_item(db, actor, item_id)
    check_version(item.version, expected_version, "preparation item")
    _require_active(item)
    request = await create_evidence_request(
        db,
        actor,
        category=category,
        prompt=prompt,
        reason=reason,
        component=item.name,
        measurement_dimension=measurement_dimension,
        priority=priority,
    )
    spec = dict(item.specification or {})
    spec["evidence_request_ids"] = [*spec.get("evidence_request_ids", []), str(request.id)]
    item.specification = spec
    item.status = "needs_evidence"
    item.version += 1
    return item, request


async def confirm_catalogue_match(
    db: AsyncSession, actor: JobActor, item_id: uuid.UUID, product_id: uuid.UUID, *, expected_version: int | None
) -> PreparationItem:
    """The contractor states that this real catalogue product meets the confirmed
    requirement. Refused for a fitment or dimension contradiction. Not stock or price."""
    actor.require_contractor()
    item = await _locked_item(db, actor, item_id)
    check_version(item.version, expected_version, "preparation item")
    if item.status != "contractor_confirmed":
        raise AppError(409, "requirement_not_confirmed", "Confirm the requirement before choosing a catalogue product")
    await _deps_current(db, item)
    product = (
        await db.execute(select(Product).where(Product.id == product_id, Product.is_active.is_(True)))
    ).scalar_one_or_none()
    if product is None:
        raise not_found("Product")
    profile = await _profile(db, actor.job)
    if profile is not None:
        result = (await fitment.evaluate_products(db, [product], profile))[product.id]
        if result.status == "verified_mismatch":
            raise AppError(409, "fitment_mismatch", "Central fitment says this product does not fit the vessel")
    template = (item.specification or {}).get("template", "")
    od = msvc.current_value_mm(
        await msvc.list_for_job(db, actor.job.id, include_inactive=False), "hose_external_diameter"
    )
    if dimension_check(product, template, od)["status"] == "range_excludes_recorded_od":
        raise AppError(409, "dimension_mismatch", "The product's stated range excludes the recorded dimension")
    if str(product.id) not in [str(c) for c in item.candidate_product_ids or []]:
        item.candidate_product_ids = [*item.candidate_product_ids, str(product.id)]
    item.confirmed_product_id = product.id
    item.catalogue_match = "confirmed"
    item.version += 1
    await audit.record(
        db,
        actor.user_id,
        "service_preparation_item.catalogue_confirmed",
        "service_preparation_item",
        item.id,
        {"job_id": str(actor.job.id), "product_id": str(product.id), "sku": product.sku},
    )
    return item
