"""Helm Dash dispatch (dispatcher/admin), administration (admin) and operator jobs.

MVP: a responsive web dispatch workflow. Operators only ever see jobs assigned to
them; any other job id returns 404.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import AdminUser, DispatcherUser, require_roles
from app.models.helm_dash import (
    DeliveryOperator,
    HelmDashDelivery,
    OperatingArea,
    OperatorPayout,
)
from app.models.order import Order
from app.models.user import User
from app.schemas.dispatch import (
    AreaCreate,
    AreaOut,
    AreaUpdate,
    AssignBody,
    Availability,
    DeliveryDetailOut,
    DeliveryOut,
    LocationBody,
    LocationOut,
    OperatorCreate,
    OperatorOut,
    OperatorStatusBody,
    PayoutOut,
    ReasonBody,
    Reconciliation,
)
from app.services import audit, delivery, payouts
from app.services.loyalty import current_period, parse_period

router = APIRouter(prefix="/dispatch", tags=["Helm Dash Dispatch & Operators"])
Db = Annotated[AsyncSession, Depends(get_db, scope="function")]
OperatorRole = Annotated[User, Depends(require_roles("operator"))]
Mutation = [Depends(mutation_limit())]


async def _out(db: AsyncSession, d: HelmDashDelivery, detail: bool = False) -> dict:
    order_number = (await db.execute(select(Order.order_number).where(Order.id == d.order_id))).scalar_one_or_none()
    data = {c.key: getattr(d, c.key) for c in HelmDashDelivery.__table__.columns}
    data["order_number"] = order_number
    data["nautical_miles"] = float(d.nautical_miles) if d.nautical_miles is not None else None
    if detail:
        data["events"] = await delivery.timeline(db, d.id)
        data["latest_location"] = delivery.location_view(await delivery.latest_location(db, d))
    return data


# ------------------------------------------------------------------ dispatcher views
@router.get("/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    user: DispatcherUser,
    db: Db,
    status_filter: str | None = Query(None, alias="status"),
    area_id: str | None = None,
    operator_id: uuid.UUID | None = None,
    active_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[dict]:
    q = select(HelmDashDelivery).order_by(HelmDashDelivery.created_at).limit(limit).offset(offset)
    if status_filter:
        q = q.where(HelmDashDelivery.status == status_filter)
    if area_id:
        q = q.where(HelmDashDelivery.area_id == area_id)
    if operator_id:
        q = q.where(HelmDashDelivery.operator_id == operator_id)
    if active_only:
        q = q.where(HelmDashDelivery.status.not_in(delivery.TERMINAL_STATUSES))
    return [await _out(db, d) for d in (await db.execute(q)).scalars()]


@router.get("/deliveries/{delivery_id}", response_model=DeliveryDetailOut)
async def get_delivery(delivery_id: uuid.UUID, user: DispatcherUser, db: Db) -> dict:
    return await _out(db, await delivery.get_delivery(db, delivery_id), detail=True)


@router.post("/deliveries/{delivery_id}/assign", response_model=DeliveryOut, dependencies=Mutation)
async def assign_delivery(delivery_id: uuid.UUID, body: AssignBody, user: DispatcherUser, db: Db) -> dict:
    """Assign or reassign an active operator serving the delivery's area."""
    return await _out(db, await delivery.assign(db, delivery_id, body.operator_id, user.id, body.note))


@router.post("/deliveries/{delivery_id}/cancel", response_model=DeliveryOut, dependencies=Mutation)
async def cancel_delivery(delivery_id: uuid.UUID, body: ReasonBody, user: DispatcherUser, db: Db) -> dict:
    return await _out(db, await delivery.cancel(db, delivery_id, user.id, body.reason))


@router.post("/deliveries/{delivery_id}/fail", response_model=DeliveryOut, dependencies=Mutation)
async def fail_delivery(delivery_id: uuid.UUID, body: ReasonBody, user: DispatcherUser, db: Db) -> dict:
    """Record that an in-progress delivery could not be completed."""
    return await _out(db, await delivery.dispatcher_fail(db, delivery_id, user.id, body.reason))


@router.get("/operators", response_model=list[OperatorOut])
async def list_operators(
    user: DispatcherUser,
    db: Db,
    area_id: str | None = None,
    active: bool | None = None,
    online: bool | None = None,
) -> list:
    q = select(DeliveryOperator).order_by(DeliveryOperator.display_name)
    if area_id:
        q = q.where(DeliveryOperator.area_id == area_id)
    if active is not None:
        q = q.where(DeliveryOperator.active.is_(active))
    if online is not None:
        q = q.where(DeliveryOperator.is_online.is_(online))
    return list((await db.execute(q)).scalars())


@router.get("/areas", response_model=list[AreaOut])
async def list_areas(user: DispatcherUser, db: Db) -> list:
    return list((await db.execute(select(OperatingArea).order_by(OperatingArea.name))).scalars())


# ------------------------------------------------------------------------- admin
@router.post("/areas", response_model=AreaOut, status_code=status.HTTP_201_CREATED)
async def create_area(body: AreaCreate, admin: AdminUser, db: Db) -> OperatingArea:
    if await db.get(OperatingArea, body.id) is not None:
        raise AppError(409, "area_exists", "An operating area with that id already exists")
    area = OperatingArea(**body.model_dump())
    db.add(area)
    await audit.record(db, admin.id, "area_create", "operating_area", body.id, body.model_dump())
    await db.flush()
    await db.refresh(area)
    return area


@router.patch("/areas/{area_id}", response_model=AreaOut)
async def update_area(area_id: str, body: AreaUpdate, admin: AdminUser, db: Db) -> OperatingArea:
    area = await db.get(OperatingArea, area_id)
    if area is None:
        raise not_found("Operating area")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        if v is None:
            raise AppError(422, "invalid_value", f"{k} cannot be null")
        setattr(area, k, v)
    await audit.record(db, admin.id, "area_update", "operating_area", area_id, changes)
    await db.flush()
    return area


@router.post("/operators", response_model=OperatorOut, status_code=status.HTTP_201_CREATED)
async def create_operator(body: OperatorCreate, admin: AdminUser, db: Db) -> DeliveryOperator:
    """Create an operator profile (inactive). The user must already hold role operator."""
    target = await db.get(User, body.user_id)
    if target is None:
        raise not_found("User")
    if target.role != "operator":
        raise AppError(409, "role_required", "Grant the user the operator role before creating a profile")
    if await db.get(OperatingArea, body.area_id) is None:
        raise not_found("Operating area")
    if await db.get(DeliveryOperator, body.user_id) is not None:
        raise AppError(409, "operator_exists", "This user already has an operator profile")
    op = DeliveryOperator(**body.model_dump(), active=False, is_online=False)
    db.add(op)
    await audit.record(
        db,
        admin.id,
        "operator_create",
        "delivery_operator",
        body.user_id,
        {"area_id": body.area_id, "certification_reference_unverified": body.certification_reference},
    )
    await db.flush()
    await db.refresh(op)
    return op


async def _set_active(user_id: uuid.UUID, active: bool, admin: User, db: AsyncSession) -> DeliveryOperator:
    op = await db.get(DeliveryOperator, user_id)
    if op is None:
        raise not_found("Operator")
    if active:
        role = (await db.execute(select(User.role).where(User.id == user_id))).scalar_one()
        if role != "operator":
            raise AppError(409, "role_required", "The user no longer holds the operator role")
    op.active = active
    if not active:
        op.is_online = False
    await audit.record(
        db, admin.id, "operator_activate" if active else "operator_deactivate", "delivery_operator", user_id, None
    )
    await db.flush()
    return op


@router.post("/operators/{user_id}/activate", response_model=OperatorOut)
async def activate_operator(user_id: uuid.UUID, admin: AdminUser, db: Db) -> DeliveryOperator:
    return await _set_active(user_id, True, admin, db)


@router.post("/operators/{user_id}/deactivate", response_model=OperatorOut)
async def deactivate_operator(user_id: uuid.UUID, admin: AdminUser, db: Db) -> DeliveryOperator:
    return await _set_active(user_id, False, admin, db)


@router.get("/payouts", response_model=list[PayoutOut])
async def list_payouts(
    admin: AdminUser,
    db: Db,
    status_filter: str | None = Query(None, alias="status"),
    operator_id: uuid.UUID | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> list:
    q = select(OperatorPayout).order_by(OperatorPayout.created_at).limit(limit)
    if status_filter:
        q = q.where(OperatorPayout.status == status_filter)
    if operator_id:
        q = q.where(OperatorPayout.operator_id == operator_id)
    return list((await db.execute(q)).scalars())


@router.post("/payouts/{payout_id}/approve", response_model=PayoutOut)
async def approve_payout(payout_id: uuid.UUID, admin: AdminUser, db: Db) -> OperatorPayout:
    """Record approval only. Live payouts are disabled; no payout provider is called."""
    return await payouts.approve(db, payout_id, admin.id)


@router.get("/reconciliation", response_model=Reconciliation)
async def reconciliation(admin: AdminUser, db: Db, period: str | None = Query(None, pattern=r"^\d{4}-\d{2}$")) -> dict:
    period = period or current_period()
    parse_period(period)
    return await payouts.reconciliation(db, period)


# ---------------------------------------------------------------------- operators
@router.get("/me", response_model=OperatorOut)
async def my_operator_profile(user: OperatorRole, db: Db) -> DeliveryOperator:
    return await delivery.get_operator_profile(db, user.id)


@router.put("/me/availability", response_model=OperatorOut, dependencies=Mutation)
async def set_availability(body: Availability, user: OperatorRole, db: Db) -> DeliveryOperator:
    op = await delivery.get_operator_profile(db, user.id)
    if body.is_online and not op.active:
        raise AppError(403, "operator_not_active", "Your operator profile is not active")
    op.is_online = body.is_online
    await db.flush()
    return op


@router.get("/jobs", response_model=list[DeliveryOut])
async def my_jobs(user: OperatorRole, db: Db, include_finished: bool = False) -> list[dict]:
    q = select(HelmDashDelivery).where(HelmDashDelivery.operator_id == user.id).order_by(HelmDashDelivery.assigned_at)
    if not include_finished:
        q = q.where(HelmDashDelivery.status.not_in(delivery.TERMINAL_STATUSES))
    return [await _out(db, d) for d in (await db.execute(q)).scalars()]


@router.get("/jobs/{delivery_id}", response_model=DeliveryDetailOut)
async def my_job(delivery_id: uuid.UUID, user: OperatorRole, db: Db) -> dict:
    return await _out(db, await delivery.get_operator_job(db, user.id, delivery_id), detail=True)


@router.post("/jobs/{delivery_id}/accept", response_model=DeliveryOut, dependencies=Mutation)
async def accept_job(delivery_id: uuid.UUID, user: OperatorRole, db: Db) -> dict:
    return await _out(db, await delivery.operator_accept(db, user.id, delivery_id))


@router.post("/jobs/{delivery_id}/decline", response_model=DeliveryOut, dependencies=Mutation)
async def decline_job(delivery_id: uuid.UUID, body: ReasonBody, user: OperatorRole, db: Db) -> dict:
    """Decline an assigned job; it returns to awaiting_dispatch."""
    return await _out(db, await delivery.operator_decline(db, user.id, delivery_id, body.reason))


@router.post("/jobs/{delivery_id}/status", response_model=DeliveryOut, dependencies=Mutation)
async def job_status(delivery_id: uuid.UUID, body: OperatorStatusBody, user: OperatorRole, db: Db) -> dict:
    """accepted -> picked_up -> en_route -> delivered (or failed)."""
    return await _out(db, await delivery.operator_status(db, user.id, delivery_id, body.status, body.note))


@router.post(
    "/jobs/{delivery_id}/location",
    response_model=LocationOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=Mutation,
)
async def report_location(delivery_id: uuid.UUID, body: LocationBody, user: OperatorRole, db: Db):
    """Record a position reported by the assigned operator's device."""
    job = await delivery.get_operator_job(db, user.id, delivery_id)
    return await delivery.record_location(
        db,
        job,
        operator_id=user.id,
        lat=body.lat,
        lng=body.lng,
        recorded_at=body.recorded_at,
        accuracy_m=body.accuracy_m,
        heading_deg=body.heading_deg,
        speed_knots=body.speed_knots,
        source="operator_device",
    )
