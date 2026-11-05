"""Vessel equipment & service history (owner-scoped) and the Boat OEM database.

Two route families live here (``main.py`` includes this module's ``router``):

* ``/vessels/{vessel_id}/equipment…``, ``/service-records…``, ``/service-reminders…`` —
  owner-scoped through :func:`app.routers.vessels.get_owned_vessel` (other owners: 404).
* ``/boat-db/…`` — public read of manufacturers → models → years → OEM equipment,
  HIN decoding, admin curation and the profile-verification review queue.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit, rate_limit
from app.database import get_db, utcnow
from app.middleware.auth import AdminUser, CurrentUserId
from app.models.boat_db import BoatModel, EquipmentCategory, Manufacturer, ModelYear, OEMEquipment
from app.models.vessel import (
    EquipmentVerificationRequest,
    ServiceRecord,
    ServiceReminder,
    Vessel,
    VesselEquipment,
)
from app.routers.vessels import get_owned_vessel
from app.schemas.boat_db import (
    AdminVerificationItem,
    BoatModelCreate,
    BoatModelResponse,
    BoatModelUpdate,
    EquipmentCategoryCreate,
    EquipmentCategoryResponse,
    HinDecodeRequest,
    HinDecodeResponse,
    ManufacturerCreate,
    ManufacturerDetail,
    ManufacturerResponse,
    ManufacturerUpdate,
    ModelYearCreate,
    ModelYearDetail,
    ModelYearResponse,
    ModelYearUpdate,
    OEMEquipmentCreate,
    OEMEquipmentResponse,
    OEMEquipmentUpdate,
    VerificationReview,
)
from app.schemas.equipment import (
    ApplyOEMRequest,
    ApplyOEMResponse,
    EquipmentCreate,
    EquipmentItem,
    EquipmentListResponse,
    EquipmentUpdate,
    ReminderComplete,
    ReminderCompleteResponse,
    ReminderCreate,
    ReminderResponse,
    ReminderUpdate,
    ServiceRecordCreate,
    ServiceRecordResponse,
    ServiceRecordUpdate,
    VerificationRequestCreate,
    VerificationRequestResponse,
)
from app.services import audit, boat_db, hin, loyalty

router = APIRouter(tags=["Vessel Equipment & Service"])
boat_router = APIRouter(prefix="/boat-db", tags=["Boat OEM Database"])

VERIFIED_CROWDSOURCE_CONFIDENCE = Decimal("0.80")  # Boat DB spec §5


def _threshold() -> Decimal:
    return Decimal(str(get_settings().fitment_min_confidence))


def _cat(c: EquipmentCategory) -> EquipmentCategoryResponse:
    return EquipmentCategoryResponse.model_validate(c)


async def _category_or_422(db: AsyncSession, slug: str) -> EquipmentCategory:
    cat = await boat_db.category_by_slug(db, slug)
    if cat is None:
        raise AppError(422, "unknown_equipment_category", f"Unknown equipment category '{slug}'")
    return cat


# =========================================================================== equipment
def _installed_item(eq: VesselEquipment, oem: OEMEquipment | None = None) -> EquipmentItem:
    conf = Decimal(str(eq.confidence_score))
    if eq.verification_status == "verified" or eq.provenance == "staff_verified":
        reliability, note = "verified", None
    elif eq.provenance == "owner_declared":
        reliability, note = "owner_declared", None
    elif conf >= _threshold() and eq.verification_status != "rejected":
        reliability, note = "high_confidence", None
    else:
        reliability = "unconfirmed"
        note = (
            f"Factory record with low confidence ({conf:.2f}); confirm it is fitted before relying on it"
        )
    return EquipmentItem(
        id=eq.id,
        source="installed",
        vessel_id=eq.vessel_id,
        category=_cat(eq.category),
        make=eq.make,
        model=eq.model,
        serial_number=eq.serial_number,
        year=eq.year,
        origin=eq.origin,
        provenance=eq.provenance,
        data_source=oem.data_source if oem else None,
        confidence_score=float(conf),
        verification_status=eq.verification_status,
        reliability=reliability,
        is_synthetic=bool(oem and oem.data_source == "synthetic_fixture"),
        oem_equipment_id=eq.oem_equipment_id,
        installed_on=eq.installed_on,
        removed_at=eq.removed_at,
        notes=eq.notes,
        display_note=note,
        created_at=eq.created_at,
        updated_at=eq.updated_at,
    )


def _oem_reliability(o: OEMEquipment) -> str:
    reliable = boat_db.is_reliable(o.confidence_score, o.verification_status)
    if reliable and o.verification_status == "verified":
        return "verified"
    return "high_confidence" if reliable else "unconfirmed"


def _factory_item(vessel_id: uuid.UUID, o: OEMEquipment) -> EquipmentItem:
    reliability = _oem_reliability(o)
    note = "Listed as factory equipment for this model year"
    if reliability == "unconfirmed":
        note = (
            f"Factory record with low confidence ({Decimal(str(o.confidence_score)):.2f}, "
            f"{o.data_source}); not confirmed for your boat"
        )
    return EquipmentItem(
        id=o.id,
        source="factory_oem",
        vessel_id=vessel_id,
        category=_cat(o.category),
        make=o.equipment_make,
        model=o.equipment_model,
        origin="oem",
        provenance="oem_database",
        data_source=o.data_source,
        confidence_score=float(o.confidence_score),
        verification_status=o.verification_status,
        reliability=reliability,
        is_standard=o.is_standard,
        is_synthetic=o.data_source == "synthetic_fixture",
        oem_equipment_id=o.id,
        display_note=note,
        created_at=o.created_at,
    )


async def _owned_equipment(db: AsyncSession, vessel: Vessel, equipment_id: uuid.UUID) -> VesselEquipment:
    eq = (
        await db.execute(
            select(VesselEquipment)
            .where(VesselEquipment.id == equipment_id, VesselEquipment.vessel_id == vessel.id)
            .options(selectinload(VesselEquipment.category))
        )
    ).scalar_one_or_none()
    if eq is None:
        raise not_found("Equipment")
    return eq


async def _oem_map(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, OEMEquipment]:
    if not ids:
        return {}
    return {o.id: o for o in (await db.execute(select(OEMEquipment).where(OEMEquipment.id.in_(ids)))).scalars()}


@router.get("/vessels/{vessel_id}/equipment", response_model=EquipmentListResponse)
async def list_equipment(
    vessel_id: uuid.UUID,
    user_id: CurrentUserId,
    include_removed: bool = False,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> EquipmentListResponse:
    """Installed equipment (owner-added + applied OEM) plus un-applied factory OEM records."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    q = (
        select(VesselEquipment)
        .where(VesselEquipment.vessel_id == vessel.id)
        .options(selectinload(VesselEquipment.category))
        .order_by(VesselEquipment.created_at, VesselEquipment.id)
    )
    if not include_removed:
        q = q.where(VesselEquipment.removed_at.is_(None))
    rows = list((await db.execute(q)).scalars())
    oems = await _oem_map(db, {r.oem_equipment_id for r in rows if r.oem_equipment_id})
    items = [_installed_item(r, oems.get(r.oem_equipment_id)) for r in rows]
    applied = {r.oem_equipment_id for r in rows if r.oem_equipment_id and r.removed_at is None}
    if vessel.model_year_id:
        factory = (
            await db.execute(
                select(OEMEquipment)
                .where(OEMEquipment.model_year_id == vessel.model_year_id, OEMEquipment.verification_status != "rejected")
                .options(selectinload(OEMEquipment.category))
                .order_by(OEMEquipment.created_at, OEMEquipment.id)
            )
        ).scalars()
        items += [_factory_item(vessel.id, o) for o in factory if o.id not in applied]
    return EquipmentListResponse(vessel_id=vessel.id, model_year_id=vessel.model_year_id, items=items)


@router.post(
    "/vessels/{vessel_id}/equipment", response_model=EquipmentItem, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def add_equipment(
    vessel_id: uuid.UUID, body: EquipmentCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> EquipmentItem:
    """Owner-declared equipment (origin user_added, confidence 1.0, unverified)."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    cat = await _category_or_422(db, body.category)
    data = body.model_dump(exclude={"category"})
    eq = VesselEquipment(
        vessel_id=vessel.id, category_id=cat.id, origin="user_added", provenance="owner_declared",
        confidence_score=Decimal("1.0"), verification_status="unverified", **data,
    )
    db.add(eq)
    await db.flush()
    await db.refresh(eq, ["category"])
    return _installed_item(eq)


@router.patch(
    "/vessels/{vessel_id}/equipment/{equipment_id}", response_model=EquipmentItem,
    dependencies=[Depends(mutation_limit())],
)
async def update_equipment(
    vessel_id: uuid.UUID, equipment_id: uuid.UUID, body: EquipmentUpdate, user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> EquipmentItem:
    """Edit installed equipment. Any owner edit makes the row an owner declaration again."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    eq = await _owned_equipment(db, vessel, equipment_id)
    if eq.removed_at is not None:
        raise AppError(409, "equipment_removed", "This equipment has been removed")
    data = body.model_dump(exclude_unset=True)
    if "make" in data and data["make"] is None:
        data.pop("make")
    if "category" in data:
        slug = data.pop("category")
        if slug:
            eq.category_id = (await _category_or_422(db, slug)).id
    for k, v in data.items():
        setattr(eq, k, v)
    eq.provenance = "owner_declared"
    eq.confidence_score = Decimal("1.0")
    eq.verification_status = "unverified"
    await db.flush()
    await db.refresh(eq, ["category"])
    oems = await _oem_map(db, {eq.oem_equipment_id} if eq.oem_equipment_id else set())
    return _installed_item(eq, oems.get(eq.oem_equipment_id))


@router.delete(
    "/vessels/{vessel_id}/equipment/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def remove_equipment(
    vessel_id: uuid.UUID, equipment_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    """Soft remove (kept for service history; ignored by fitment and checklists)."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    eq = await _owned_equipment(db, vessel, equipment_id)
    if eq.removed_at is None:
        eq.removed_at = utcnow()
        await db.flush()


@router.post(
    "/vessels/{vessel_id}/equipment/apply-oem", response_model=ApplyOEMResponse,
    dependencies=[Depends(mutation_limit())],
)
async def apply_oem_equipment(
    vessel_id: uuid.UUID, user_id: CurrentUserId, body: ApplyOEMRequest | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ApplyOEMResponse:
    """Copy factory OEM records into installed equipment, carrying the source confidence."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    if vessel.model_year_id is None:
        raise AppError(409, "no_model_year", "This vessel is not linked to a boat-database model year")
    q = (
        select(OEMEquipment)
        .where(OEMEquipment.model_year_id == vessel.model_year_id, OEMEquipment.verification_status != "rejected")
        .options(selectinload(OEMEquipment.category))
        .order_by(OEMEquipment.created_at, OEMEquipment.id)
    )
    wanted = set(body.oem_equipment_ids) if body and body.oem_equipment_ids else None
    if wanted is not None:
        q = q.where(OEMEquipment.id.in_(wanted))
    records = list((await db.execute(q)).scalars())
    if wanted is not None and len(records) != len(wanted):
        raise AppError(422, "unknown_oem_equipment", "Some OEM records do not belong to this vessel's model year")
    applied = set(
        (
            await db.execute(
                select(VesselEquipment.oem_equipment_id).where(
                    VesselEquipment.vessel_id == vessel.id,
                    VesselEquipment.removed_at.is_(None),
                    VesselEquipment.oem_equipment_id.isnot(None),
                )
            )
        ).scalars()
    )
    created, skipped = [], []
    for o in records:
        if o.id in applied:
            skipped.append(o.id)
            continue
        eq = VesselEquipment(
            vessel_id=vessel.id, category_id=o.category_id, make=o.equipment_make, model=o.equipment_model,
            origin="oem", oem_equipment_id=o.id, provenance="oem_database",
            confidence_score=o.confidence_score,
            verification_status="verified" if o.verification_status == "verified" and boat_db.is_reliable(
                o.confidence_score, o.verification_status) else "unverified",
        )
        db.add(eq)
        await db.flush()
        await db.refresh(eq, ["category"])
        created.append(_installed_item(eq, o))
    return ApplyOEMResponse(created=created, skipped_already_applied=skipped)


# ------------------------------------------------------------------ verification requests
async def _pending_rows(db: AsyncSession, vessel_id: uuid.UUID) -> list[VesselEquipment]:
    return list(
        (
            await db.execute(
                select(VesselEquipment)
                .where(
                    VesselEquipment.vessel_id == vessel_id,
                    VesselEquipment.removed_at.is_(None),
                    VesselEquipment.verification_status == "pending_review",
                )
                .options(selectinload(VesselEquipment.category))
                .order_by(VesselEquipment.created_at, VesselEquipment.id)
            )
        ).scalars()
    )


def _request_response(r: EquipmentVerificationRequest, rows: list[VesselEquipment]) -> VerificationRequestResponse:
    return VerificationRequestResponse(
        id=r.id, vessel_id=r.vessel_id, user_id=r.user_id, status=r.status, submitted_note=r.submitted_note,
        evidence_url=r.evidence_url, reviewed_at=r.reviewed_at, review_note=r.review_note,
        created_at=r.created_at, equipment_ids=[e.id for e in rows],
    )


@router.post(
    "/vessels/{vessel_id}/equipment/verification-requests", response_model=VerificationRequestResponse,
    status_code=status.HTTP_201_CREATED, dependencies=[Depends(mutation_limit())],
)
async def submit_verification_request(
    vessel_id: uuid.UUID, body: VerificationRequestCreate, user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> VerificationRequestResponse:
    """Submit the vessel's equipment profile for staff verification (Boat DB spec §4.2)."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    pending = (
        await db.execute(
            select(EquipmentVerificationRequest.id).where(
                EquipmentVerificationRequest.vessel_id == vessel.id, EquipmentVerificationRequest.status == "pending"
            )
        )
    ).first()
    if pending:
        raise AppError(409, "verification_pending", "A verification request for this vessel is already pending")
    q = select(VesselEquipment).where(
        VesselEquipment.vessel_id == vessel.id,
        VesselEquipment.removed_at.is_(None),
        VesselEquipment.verification_status == "unverified",
    )
    if body.equipment_ids:
        q = q.where(VesselEquipment.id.in_(body.equipment_ids))
    rows = list((await db.execute(q)).scalars())
    if body.equipment_ids and len(rows) != len(set(body.equipment_ids)):
        raise AppError(422, "invalid_equipment", "Only this vessel's unverified installed equipment can be submitted")
    if not rows:
        raise AppError(422, "nothing_to_verify", "Add equipment to your vessel before requesting verification")
    for row in rows:
        row.verification_status = "pending_review"
    req = EquipmentVerificationRequest(
        vessel_id=vessel.id, user_id=user_id, status="pending", submitted_note=body.note,
        evidence_url=body.evidence_url,
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)
    return _request_response(req, rows)


@router.get(
    "/vessels/{vessel_id}/equipment/verification-requests", response_model=list[VerificationRequestResponse]
)
async def list_verification_requests(
    vessel_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> list[VerificationRequestResponse]:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    reqs = (
        await db.execute(
            select(EquipmentVerificationRequest)
            .where(EquipmentVerificationRequest.vessel_id == vessel.id)
            .order_by(EquipmentVerificationRequest.created_at.desc())
        )
    ).scalars()
    rows = await _pending_rows(db, vessel.id)
    return [_request_response(r, rows if r.status == "pending" else []) for r in reqs]


@boat_router.get("/verification-requests", response_model=list[AdminVerificationItem])
async def admin_verification_queue(
    admin: AdminUser,
    status_filter: str = Query("pending", alias="status", pattern="^(pending|approved|rejected|all)$"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[AdminVerificationItem]:
    """Admin review queue of crowdsourced profile verification requests."""
    q = select(EquipmentVerificationRequest).order_by(EquipmentVerificationRequest.created_at)
    if status_filter != "all":
        q = q.where(EquipmentVerificationRequest.status == status_filter)
    out = []
    for r in (await db.execute(q)).scalars():
        vessel = await db.get(Vessel, r.vessel_id)
        rows = await _pending_rows(db, r.vessel_id) if r.status == "pending" else []
        out.append(
            AdminVerificationItem(
                **{k: getattr(r, k) for k in (
                    "id", "vessel_id", "user_id", "status", "submitted_note", "evidence_url", "reviewed_by",
                    "reviewed_at", "review_note", "created_at")},
                vessel_label=f"{vessel.nickname} ({vessel.year} {vessel.make} {vessel.model})",
                equipment=[_installed_item(e).model_dump(mode="json") for e in rows],
            )
        )
    return out


async def _pending_request(db: AsyncSession, request_id: uuid.UUID) -> EquipmentVerificationRequest:
    req = (
        await db.execute(
            select(EquipmentVerificationRequest).where(EquipmentVerificationRequest.id == request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if req is None:
        raise not_found("Verification request")
    if req.status != "pending":
        raise AppError(409, "already_reviewed", f"This request was already {req.status}")
    return req


@boat_router.post("/verification-requests/{request_id}/approve", response_model=VerificationRequestResponse)
async def approve_verification(
    request_id: uuid.UUID, admin: AdminUser, body: VerificationReview | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> VerificationRequestResponse:
    """Approve: reviewed rows become staff-verified; the owner's bonus is awarded once."""
    req = await _pending_request(db, request_id)
    rows = await _pending_rows(db, req.vessel_id)
    for row in rows:
        row.verification_status = "verified"
        row.provenance = "staff_verified"
        row.confidence_score = max(Decimal(str(row.confidence_score)), VERIFIED_CROWDSOURCE_CONFIDENCE)
    req.status = "approved"
    req.reviewed_by = admin.id
    req.reviewed_at = utcnow()
    req.review_note = body.review_note if body else None
    await audit.record(db, admin.id, "equipment_verification.approve", "equipment_verification_request", req.id,
                       {"vessel_id": str(req.vessel_id), "equipment_ids": [str(r.id) for r in rows]})
    await db.flush()
    await loyalty.award_profile_verification_bonus(db, req.user_id, req.id)
    return _request_response(req, rows)


@boat_router.post("/verification-requests/{request_id}/reject", response_model=VerificationRequestResponse)
async def reject_verification(
    request_id: uuid.UUID, admin: AdminUser, body: VerificationReview | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> VerificationRequestResponse:
    """Reject: rows return to unverified owner declarations (still the owner's facts)."""
    req = await _pending_request(db, request_id)
    rows = await _pending_rows(db, req.vessel_id)
    for row in rows:
        row.verification_status = "unverified"
    req.status = "rejected"
    req.reviewed_by = admin.id
    req.reviewed_at = utcnow()
    req.review_note = body.review_note if body else None
    await audit.record(db, admin.id, "equipment_verification.reject", "equipment_verification_request", req.id,
                       {"vessel_id": str(req.vessel_id), "equipment_ids": [str(r.id) for r in rows]})
    await db.flush()
    return _request_response(req, rows)


# =========================================================================== service records
async def _check_equipment_ref(db: AsyncSession, vessel: Vessel, equipment_id: uuid.UUID | None) -> None:
    if equipment_id is None:
        return
    found = (
        await db.execute(
            select(VesselEquipment.id).where(VesselEquipment.id == equipment_id, VesselEquipment.vessel_id == vessel.id)
        )
    ).first()
    if not found:
        raise AppError(422, "invalid_equipment", "Equipment does not belong to this vessel")


async def _owned_record(db: AsyncSession, vessel: Vessel, record_id: uuid.UUID) -> ServiceRecord:
    rec = (
        await db.execute(select(ServiceRecord).where(ServiceRecord.id == record_id, ServiceRecord.vessel_id == vessel.id))
    ).scalar_one_or_none()
    if rec is None:
        raise not_found("Service record")
    return rec


@router.get("/vessels/{vessel_id}/service-records", response_model=list[ServiceRecordResponse])
async def list_service_records(
    vessel_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> list[ServiceRecord]:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    return list(
        (
            await db.execute(
                select(ServiceRecord)
                .where(ServiceRecord.vessel_id == vessel.id)
                .order_by(ServiceRecord.performed_on.desc(), ServiceRecord.created_at.desc())
            )
        ).scalars()
    )


@router.post(
    "/vessels/{vessel_id}/service-records", response_model=ServiceRecordResponse,
    status_code=status.HTTP_201_CREATED, dependencies=[Depends(mutation_limit())],
)
async def create_service_record(
    vessel_id: uuid.UUID, body: ServiceRecordCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> ServiceRecord:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await _check_equipment_ref(db, vessel, body.equipment_id)
    rec = ServiceRecord(vessel_id=vessel.id, **body.model_dump())
    db.add(rec)
    await db.flush()
    await db.refresh(rec)
    return rec


@router.patch(
    "/vessels/{vessel_id}/service-records/{record_id}", response_model=ServiceRecordResponse,
    dependencies=[Depends(mutation_limit())],
)
async def update_service_record(
    vessel_id: uuid.UUID, record_id: uuid.UUID, body: ServiceRecordUpdate, user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ServiceRecord:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    rec = await _owned_record(db, vessel, record_id)
    data = body.model_dump(exclude_unset=True)
    for required in ("service_type", "performed_on"):
        if required in data and data[required] is None:
            data.pop(required)
    if "equipment_id" in data:
        await _check_equipment_ref(db, vessel, data["equipment_id"])
    for k, v in data.items():
        setattr(rec, k, v)
    await db.flush()
    await db.refresh(rec)
    return rec


@router.delete(
    "/vessels/{vessel_id}/service-records/{record_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def delete_service_record(
    vessel_id: uuid.UUID, record_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await db.delete(await _owned_record(db, vessel, record_id))
    await db.flush()


# =========================================================================== reminders
def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _reminder_response(r: ServiceReminder, vessel: Vessel) -> ReminderResponse:
    is_due = r.status == "active" and (
        (r.due_on is not None and r.due_on <= date.today())
        or (r.due_engine_hours is not None and vessel.engine_hours is not None
            and vessel.engine_hours >= r.due_engine_hours)
    )
    return ReminderResponse(
        **{k: getattr(r, k) for k in (
            "id", "vessel_id", "equipment_id", "title", "due_on", "due_engine_hours", "interval_months",
            "interval_hours", "status", "source", "created_at", "updated_at")},
        is_due=is_due,
    )


async def _owned_reminder(db: AsyncSession, vessel: Vessel, reminder_id: uuid.UUID) -> ServiceReminder:
    rem = (
        await db.execute(
            select(ServiceReminder).where(ServiceReminder.id == reminder_id, ServiceReminder.vessel_id == vessel.id)
        )
    ).scalar_one_or_none()
    if rem is None:
        raise not_found("Reminder")
    return rem


@router.get("/vessels/{vessel_id}/service-reminders", response_model=list[ReminderResponse])
async def list_reminders(
    vessel_id: uuid.UUID, user_id: CurrentUserId,
    status_filter: str = Query("active", alias="status", pattern="^(active|completed|dismissed|all)$"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[ReminderResponse]:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    q = select(ServiceReminder).where(ServiceReminder.vessel_id == vessel.id)
    if status_filter != "all":
        q = q.where(ServiceReminder.status == status_filter)
    q = q.order_by(ServiceReminder.due_on.asc().nulls_last(), ServiceReminder.due_engine_hours.asc().nulls_last(),
                   ServiceReminder.created_at)
    return [_reminder_response(r, vessel) for r in (await db.execute(q)).scalars()]


@router.post(
    "/vessels/{vessel_id}/service-reminders", response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED, dependencies=[Depends(mutation_limit())],
)
async def create_reminder(
    vessel_id: uuid.UUID, body: ReminderCreate, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> ReminderResponse:
    """Owner-defined reminder. Intervals are the owner's; none are invented from manufacturer data."""
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await _check_equipment_ref(db, vessel, body.equipment_id)
    rem = ServiceReminder(vessel_id=vessel.id, source="owner", status="active", **body.model_dump())
    db.add(rem)
    await db.flush()
    await db.refresh(rem)
    return _reminder_response(rem, vessel)


@router.patch(
    "/vessels/{vessel_id}/service-reminders/{reminder_id}", response_model=ReminderResponse,
    dependencies=[Depends(mutation_limit())],
)
async def update_reminder(
    vessel_id: uuid.UUID, reminder_id: uuid.UUID, body: ReminderUpdate, user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ReminderResponse:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    rem = await _owned_reminder(db, vessel, reminder_id)
    if rem.status == "completed":
        raise AppError(409, "reminder_completed", "Completed reminders cannot be edited")
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is None:
        data.pop("title")
    if "status" in data and data["status"] is None:
        data.pop("status")
    if "equipment_id" in data:
        await _check_equipment_ref(db, vessel, data["equipment_id"])
    for k, v in data.items():
        setattr(rem, k, v)
    if rem.due_on is None and rem.due_engine_hours is None:
        raise AppError(422, "reminder_needs_due", "A reminder needs a due date and/or due engine hours")
    await db.flush()
    await db.refresh(rem)
    return _reminder_response(rem, vessel)


@router.delete(
    "/vessels/{vessel_id}/service-reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def delete_reminder(
    vessel_id: uuid.UUID, reminder_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> None:
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    await db.delete(await _owned_reminder(db, vessel, reminder_id))
    await db.flush()


@router.post(
    "/vessels/{vessel_id}/service-reminders/{reminder_id}/complete", response_model=ReminderCompleteResponse,
    dependencies=[Depends(mutation_limit())],
)
async def complete_reminder(
    vessel_id: uuid.UUID, reminder_id: uuid.UUID, user_id: CurrentUserId, body: ReminderComplete | None = None,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ReminderCompleteResponse:
    """Complete a reminder; when it has an interval the next reminder is created from it."""
    body = body or ReminderComplete()
    vessel = await get_owned_vessel(db, vessel_id, user_id)
    rem = (
        await db.execute(
            select(ServiceReminder)
            .where(ServiceReminder.id == reminder_id, ServiceReminder.vessel_id == vessel.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if rem is None:
        raise not_found("Reminder")
    if rem.status != "active":
        raise AppError(409, "reminder_not_active", f"This reminder is {rem.status}")
    done_on = body.completed_on or date.today()
    hours = body.engine_hours if body.engine_hours is not None else vessel.engine_hours
    rem.status = "completed"
    record = None
    if body.record_service:
        record = ServiceRecord(
            vessel_id=vessel.id, equipment_id=rem.equipment_id, service_type=rem.title, performed_on=done_on,
            engine_hours=hours, notes=body.notes,
        )
        db.add(record)
    nxt = None
    if rem.interval_months or rem.interval_hours:
        next_hours = None
        if rem.interval_hours:
            base = hours if hours is not None else rem.due_engine_hours
            next_hours = base + rem.interval_hours if base is not None else None
        nxt = ServiceReminder(
            vessel_id=vessel.id, equipment_id=rem.equipment_id, title=rem.title,
            due_on=_add_months(done_on, rem.interval_months) if rem.interval_months else None,
            due_engine_hours=next_hours, interval_months=rem.interval_months, interval_hours=rem.interval_hours,
            status="active", source=rem.source, knowledge_source_id=rem.knowledge_source_id,
        )
        if nxt.due_on is None and nxt.due_engine_hours is None:
            nxt = None  # interval hours with no known engine hours: owner must set the next due point
        else:
            db.add(nxt)
    if hours is not None and (vessel.engine_hours is None or hours > vessel.engine_hours):
        vessel.engine_hours = hours
    await db.flush()
    for obj in (rem, nxt, record):
        if obj is not None:
            await db.refresh(obj)
    return ReminderCompleteResponse(
        completed=_reminder_response(rem, vessel),
        next=_reminder_response(nxt, vessel) if nxt else None,
        service_record=ServiceRecordResponse.model_validate(record) if record else None,
    )


# =========================================================================== boat DB (public)
def _oem_response(o: OEMEquipment, synthetic_parent: bool = False) -> OEMEquipmentResponse:
    return OEMEquipmentResponse(
        id=o.id, model_year_id=o.model_year_id, category=_cat(o.category), equipment_make=o.equipment_make,
        equipment_model=o.equipment_model, part_sku=o.part_sku, is_standard=o.is_standard,
        data_source=o.data_source, source_url=o.source_url, confidence_score=float(o.confidence_score),
        verification_status=o.verification_status,
        is_synthetic=synthetic_parent or o.data_source == "synthetic_fixture",
        reliable=boat_db.is_reliable(o.confidence_score, o.verification_status),
    )


def _model_response(m: BoatModel, years: list[int] | None = None) -> BoatModelResponse:
    return BoatModelResponse(
        id=m.id, manufacturer_id=m.manufacturer_id, name=m.name, hull_type=m.hull_type,
        propulsion_type=m.propulsion_type, length_ft=float(m.length_ft) if m.length_ft is not None else None,
        beam_in=m.beam_in, is_synthetic=m.is_synthetic, source_url=m.source_url, years=sorted(years or []),
    )


def _maker_response(m: Manufacturer, model_count: int = 0) -> ManufacturerResponse:
    return ManufacturerResponse(
        id=m.id, name=m.name, country=m.country, website=m.website, mic_codes=list(m.mic_codes or []),
        is_synthetic=m.is_synthetic, source=m.source, model_count=model_count,
    )


@boat_router.get("/equipment-categories", response_model=list[EquipmentCategoryResponse])
async def list_equipment_categories(db: AsyncSession = Depends(get_db, scope="function")) -> list[EquipmentCategory]:
    await boat_db.ensure_equipment_categories(db)  # reference data; no-op once present
    return list((await db.execute(select(EquipmentCategory).order_by(EquipmentCategory.name))).scalars())


@boat_router.post(
    "/equipment-categories", response_model=EquipmentCategoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_equipment_category(
    body: EquipmentCategoryCreate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> EquipmentCategory:
    if await boat_db.category_by_slug(db, body.slug):
        raise AppError(409, "duplicate", "An equipment category with this slug exists")
    parent = await _category_or_422(db, body.parent_slug) if body.parent_slug else None
    cat = EquipmentCategory(slug=body.slug, name=body.name, parent_id=parent.id if parent else None)
    db.add(cat)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.category_create", "equipment_category", cat.id, {"slug": cat.slug})
    return cat


@boat_router.post("/hin/decode", response_model=HinDecodeResponse,
                  dependencies=[Depends(rate_limit("hin_decode", lambda: get_settings().rate_limit_hin_per_minute))])
async def decode_hin(body: HinDecodeRequest, db: AsyncSession = Depends(get_db, scope="function")) -> HinDecodeResponse:
    """Decode a HIN/CIN. Manufacturer only when its MIC is recorded; nothing is guessed."""
    return HinDecodeResponse.model_validate((await hin.decode(db, body.hin)).as_dict())


@boat_router.get("/manufacturers", response_model=list[ManufacturerResponse])
async def list_manufacturers(
    q: str | None = Query(None, max_length=100), include_synthetic: bool = True, db: AsyncSession = Depends(get_db, scope="function")
) -> list[ManufacturerResponse]:
    counts = dict(
        (await db.execute(select(BoatModel.manufacturer_id, func.count()).group_by(BoatModel.manufacturer_id))).all()
    )
    query = select(Manufacturer).order_by(Manufacturer.name)
    if q:
        query = query.where(Manufacturer.name.ilike(f"%{q.strip()}%"))
    if not include_synthetic:
        query = query.where(Manufacturer.is_synthetic.is_(False))
    return [_maker_response(m, counts.get(m.id, 0)) for m in (await db.execute(query)).scalars()]


async def _maker_or_404(db: AsyncSession, manufacturer_id: uuid.UUID) -> Manufacturer:
    m = await db.get(Manufacturer, manufacturer_id)
    if m is None:
        raise not_found("Manufacturer")
    return m


async def _model_or_404(db: AsyncSession, model_id: uuid.UUID) -> BoatModel:
    m = (
        await db.execute(select(BoatModel).where(BoatModel.id == model_id).options(selectinload(BoatModel.years)))
    ).scalar_one_or_none()
    if m is None:
        raise not_found("Boat model")
    return m


async def _models_for(db: AsyncSession, manufacturer_id: uuid.UUID) -> list[BoatModelResponse]:
    models = (
        await db.execute(
            select(BoatModel).where(BoatModel.manufacturer_id == manufacturer_id)
            .options(selectinload(BoatModel.years)).order_by(BoatModel.name)
        )
    ).scalars()
    return [_model_response(m, [y.year for y in m.years]) for m in models]


@boat_router.get("/manufacturers/{manufacturer_id}", response_model=ManufacturerDetail)
async def get_manufacturer(manufacturer_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")) -> ManufacturerDetail:
    m = await _maker_or_404(db, manufacturer_id)
    models = await _models_for(db, m.id)
    return ManufacturerDetail(**_maker_response(m, len(models)).model_dump(), models=models)


@boat_router.get("/manufacturers/{manufacturer_id}/models", response_model=list[BoatModelResponse])
async def list_models(manufacturer_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")) -> list[BoatModelResponse]:
    await _maker_or_404(db, manufacturer_id)
    return await _models_for(db, manufacturer_id)


@boat_router.get("/models/{model_id}", response_model=BoatModelResponse)
async def get_model(model_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")) -> BoatModelResponse:
    m = await _model_or_404(db, model_id)
    return _model_response(m, [y.year for y in m.years])


async def _year_counts(db: AsyncSession, year_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not year_ids:
        return {}
    return dict(
        (
            await db.execute(
                select(OEMEquipment.model_year_id, func.count())
                .where(OEMEquipment.model_year_id.in_(year_ids)).group_by(OEMEquipment.model_year_id)
            )
        ).all()
    )


def _year_response(y: ModelYear, count: int = 0) -> ModelYearResponse:
    return ModelYearResponse(
        id=y.id, boat_model_id=y.boat_model_id, year=y.year, brochure_url=y.brochure_url,
        hin_prefix=y.hin_prefix, equipment_count=count,
    )


@boat_router.get("/models/{model_id}/years", response_model=list[ModelYearResponse])
async def list_model_years(model_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")) -> list[ModelYearResponse]:
    m = await _model_or_404(db, model_id)
    years = sorted(m.years, key=lambda y: y.year)
    counts = await _year_counts(db, [y.id for y in years])
    return [_year_response(y, counts.get(y.id, 0)) for y in years]


async def _year_detail(db: AsyncSession, model_year_id: uuid.UUID) -> ModelYearDetail:
    y = await boat_db.load_model_year(db, model_year_id)
    if y is None:
        raise not_found("Model year")
    model, maker = y.boat_model, y.boat_model.manufacturer
    synthetic = model.is_synthetic or maker.is_synthetic
    equipment = sorted(y.equipment, key=lambda o: (o.category.name, o.equipment_make, str(o.id)))
    return ModelYearDetail(
        **_year_response(y, len(equipment)).model_dump(),
        manufacturer=_maker_response(maker),
        boat_model=_model_response(model),
        equipment=[_oem_response(o, synthetic) for o in equipment],
    )


@boat_router.get("/model-years/{model_year_id}", response_model=ModelYearDetail)
async def get_model_year(model_year_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")) -> ModelYearDetail:
    """Model year with its OEM equipment (data source, confidence, verification, synthetic flag)."""
    return await _year_detail(db, model_year_id)


@boat_router.get("/model-years/{model_year_id}/equipment", response_model=list[OEMEquipmentResponse])
async def get_model_year_equipment(
    model_year_id: uuid.UUID, db: AsyncSession = Depends(get_db, scope="function")
) -> list[OEMEquipmentResponse]:
    return (await _year_detail(db, model_year_id)).equipment


@boat_router.get("/lookup", response_model=ModelYearDetail)
async def lookup_model_year(
    make: str = Query(min_length=1), model: str = Query(min_length=1), year: int = Query(ge=1900, le=2100),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> ModelYearDetail:
    """Exact (normalised) make/model/year lookup — the same match the vessel hook uses."""
    match = await boat_db.match_model_year(db, make, model, year)
    if match is None:
        raise not_found("Model year")
    return await _year_detail(db, match.id)


# =========================================================================== boat DB (admin)
@boat_router.post("/manufacturers", response_model=ManufacturerResponse, status_code=status.HTTP_201_CREATED)
async def create_manufacturer(
    body: ManufacturerCreate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ManufacturerResponse:
    if (await db.execute(select(Manufacturer.id).where(func.lower(Manufacturer.name) == body.name.lower()))).first():
        raise AppError(409, "duplicate", "A manufacturer with this name exists")
    m = Manufacturer(**body.model_dump())
    db.add(m)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.manufacturer_create", "manufacturer", m.id, body.model_dump())
    return _maker_response(m)


@boat_router.patch("/manufacturers/{manufacturer_id}", response_model=ManufacturerResponse)
async def update_manufacturer(
    manufacturer_id: uuid.UUID, body: ManufacturerUpdate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ManufacturerResponse:
    m = await _maker_or_404(db, manufacturer_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k in ("name", "is_synthetic", "mic_codes") and v is None)}
    if "name" in data and data["name"].lower() != m.name.lower():
        if (await db.execute(select(Manufacturer.id).where(func.lower(Manufacturer.name) == data["name"].lower()))).first():
            raise AppError(409, "duplicate", "A manufacturer with this name exists")
    for k, v in data.items():
        setattr(m, k, v)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.manufacturer_update", "manufacturer", m.id, data)
    return _maker_response(m)


@boat_router.delete("/manufacturers/{manufacturer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_manufacturer(manufacturer_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    m = await _maker_or_404(db, manufacturer_id)
    await audit.record(db, admin.id, "boat_db.manufacturer_delete", "manufacturer", m.id, {"name": m.name})
    await db.execute(sa_delete(Manufacturer).where(Manufacturer.id == m.id))  # DB cascades models/years/OEM


@boat_router.post(
    "/manufacturers/{manufacturer_id}/models", response_model=BoatModelResponse, status_code=status.HTTP_201_CREATED
)
async def create_model(
    manufacturer_id: uuid.UUID, body: BoatModelCreate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> BoatModelResponse:
    await _maker_or_404(db, manufacturer_id)
    exists = (
        await db.execute(
            select(BoatModel.id).where(BoatModel.manufacturer_id == manufacturer_id,
                                       func.lower(BoatModel.name) == body.name.lower())
        )
    ).first()
    if exists:
        raise AppError(409, "duplicate", "This manufacturer already has a model with this name")
    m = BoatModel(manufacturer_id=manufacturer_id, **body.model_dump())
    db.add(m)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.model_create", "boat_model", m.id, body.model_dump())
    return _model_response(m)


@boat_router.patch("/models/{model_id}", response_model=BoatModelResponse)
async def update_model(
    model_id: uuid.UUID, body: BoatModelUpdate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> BoatModelResponse:
    m = await _model_or_404(db, model_id)
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if not (k in ("name", "is_synthetic") and v is None)}
    for k, v in data.items():
        setattr(m, k, v)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.model_update", "boat_model", m.id, data)
    return _model_response(m, [y.year for y in m.years])


@boat_router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    m = await _model_or_404(db, model_id)
    await audit.record(db, admin.id, "boat_db.model_delete", "boat_model", m.id, {"name": m.name})
    await db.execute(sa_delete(BoatModel).where(BoatModel.id == m.id))


@boat_router.post("/models/{model_id}/years", response_model=ModelYearResponse, status_code=status.HTTP_201_CREATED)
async def create_model_year(
    model_id: uuid.UUID, body: ModelYearCreate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ModelYearResponse:
    m = await _model_or_404(db, model_id)
    if any(y.year == body.year for y in m.years):
        raise AppError(409, "duplicate", "This model year exists")
    y = ModelYear(boat_model_id=m.id, **body.model_dump())
    db.add(y)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.model_year_create", "model_year", y.id, body.model_dump())
    return _year_response(y)


@boat_router.patch("/model-years/{model_year_id}", response_model=ModelYearResponse)
async def update_model_year(
    model_year_id: uuid.UUID, body: ModelYearUpdate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> ModelYearResponse:
    y = await db.get(ModelYear, model_year_id)
    if y is None:
        raise not_found("Model year")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(y, k, v)
    await db.flush()
    await audit.record(db, admin.id, "boat_db.model_year_update", "model_year", y.id, data)
    return _year_response(y, (await _year_counts(db, [y.id])).get(y.id, 0))


@boat_router.delete("/model-years/{model_year_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_year(model_year_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    y = await db.get(ModelYear, model_year_id)
    if y is None:
        raise not_found("Model year")
    await audit.record(db, admin.id, "boat_db.model_year_delete", "model_year", y.id, {"year": y.year})
    await db.execute(sa_delete(ModelYear).where(ModelYear.id == y.id))


def _check_verifiable(confidence: Decimal, verification_status: str) -> None:
    if verification_status == "verified" and confidence < _threshold():
        raise AppError(
            422, "confidence_too_low",
            f"OEM data can only be verified with confidence ≥ {get_settings().fitment_min_confidence}",
        )


@boat_router.post(
    "/model-years/{model_year_id}/equipment", response_model=OEMEquipmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_oem_equipment(
    model_year_id: uuid.UUID, body: OEMEquipmentCreate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> OEMEquipmentResponse:
    if await db.get(ModelYear, model_year_id) is None:
        raise not_found("Model year")
    cat = await _category_or_422(db, body.category)
    confidence = (
        Decimal(str(body.confidence_score)) if body.confidence_score is not None
        else boat_db.default_confidence(body.data_source)
    )
    _check_verifiable(confidence, body.verification_status)
    o = OEMEquipment(
        model_year_id=model_year_id, category_id=cat.id, confidence_score=confidence,
        **body.model_dump(exclude={"category", "confidence_score"}),
    )
    db.add(o)
    await db.flush()
    await db.refresh(o, ["category"])
    await audit.record(db, admin.id, "boat_db.oem_create", "oem_equipment", o.id, body.model_dump())
    return _oem_response(o)


@boat_router.patch("/oem-equipment/{oem_id}", response_model=OEMEquipmentResponse)
async def update_oem_equipment(
    oem_id: uuid.UUID, body: OEMEquipmentUpdate, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")
) -> OEMEquipmentResponse:
    o = (
        await db.execute(select(OEMEquipment).where(OEMEquipment.id == oem_id).options(selectinload(OEMEquipment.category)))
    ).scalar_one_or_none()
    if o is None:
        raise not_found("OEM equipment")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items()
            if not (k in ("equipment_make", "is_standard", "data_source", "verification_status", "category",
                          "confidence_score") and v is None)}
    if "category" in data:
        o.category_id = (await _category_or_422(db, data.pop("category"))).id
    if "confidence_score" in data:
        data["confidence_score"] = Decimal(str(data["confidence_score"]))
    for k, v in data.items():
        setattr(o, k, v)
    _check_verifiable(Decimal(str(o.confidence_score)), o.verification_status)
    await db.flush()
    await db.refresh(o, ["category"])
    await audit.record(db, admin.id, "boat_db.oem_update", "oem_equipment", o.id,
                       {k: (str(v) if isinstance(v, Decimal) else v) for k, v in data.items()})
    return _oem_response(o)


@boat_router.delete("/oem-equipment/{oem_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_oem_equipment(oem_id: uuid.UUID, admin: AdminUser, db: AsyncSession = Depends(get_db, scope="function")) -> None:
    o = await db.get(OEMEquipment, oem_id)
    if o is None:
        raise not_found("OEM equipment")
    await audit.record(db, admin.id, "boat_db.oem_delete", "oem_equipment", o.id,
                       {"make": o.equipment_make, "model": o.equipment_model})
    await db.delete(o)
    await db.flush()


router.include_router(boat_router)
