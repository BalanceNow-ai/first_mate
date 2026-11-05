"""Helm Dash customer side: public operating areas and owner-only delivery tracking.

Tracking shows the latest position *reported* by the assigned skipper's device (or a
clearly labelled local simulation) with its age. It never interpolates or invents a
position: with no report yet the location is ``null`` with an explanatory message.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.database import get_db
from app.middleware.auth import CurrentUser
from app.models.helm_dash import DeliveryOperator, HelmDashDelivery, OperatingArea
from app.models.order import Order
from app.schemas.helm_dash import AreaPublic, TrackingOut
from app.services import delivery
from app.services.notification_templates import DELIVERY_STATUS_LABELS

router = APIRouter(prefix="/helm-dash", tags=["Helm Dash Delivery"])
Db = Annotated[AsyncSession, Depends(get_db)]
AWAITING_POSITION = "Awaiting first position report"


@router.get("/areas", response_model=list[AreaPublic])
async def list_areas(db: Db) -> list:
    """Enabled operating areas for the delivery map (public)."""
    q = select(OperatingArea).where(OperatingArea.enabled.is_(True)).order_by(OperatingArea.name)
    return list((await db.execute(q)).scalars())


async def _tracking(db: AsyncSession, d: HelmDashDelivery, order: Order) -> dict:
    events = await delivery.timeline(db, d.id)
    vessel_name = None
    if d.operator_id is not None:
        op = await db.get(DeliveryOperator, d.operator_id)
        vessel_name = op.vessel_name if op else None
    location = delivery.location_view(await delivery.latest_location(db, d))
    message = None
    if location is None:
        if d.status in delivery.ACTIVE_TRACKING_STATUSES:
            message = AWAITING_POSITION
        elif d.status in ("awaiting_dispatch", "assigned"):
            message = "Tracking starts once a skipper accepts the delivery"
    return {
        "id": d.id,
        "order_id": d.order_id,
        "order_number": order.order_number,
        "status": d.status,
        "status_label": DELIVERY_STATUS_LABELS.get(d.status, d.status),
        "area_id": d.area_id,
        "pickup_location": d.pickup_location,
        "delivery_coordinates": d.delivery_coordinates,
        "delivery_location_name": d.delivery_location_name,
        "nautical_miles": float(d.nautical_miles) if d.nautical_miles is not None else None,
        "delivery_fee_cents": d.delivery_fee_cents,
        "estimated_delivery_minutes": d.estimated_delivery_minutes,
        "operator_display_name": d.operator_name,
        "operator_vessel_name": vessel_name,
        "timeline": [
            {"status": e.to_status, "label": DELIVERY_STATUS_LABELS.get(e.to_status, e.to_status), "at": e.created_at}
            for e in events
        ],
        "latest_location": location,
        "location_message": message,
        "created_at": d.created_at,
        "updated_at": d.updated_at,
    }


@router.get("/deliveries", response_model=list[TrackingOut])
async def my_deliveries(user: CurrentUser, db: Db) -> list[dict]:
    rows = await db.execute(
        select(HelmDashDelivery, Order)
        .join(Order, Order.id == HelmDashDelivery.order_id)
        .where(Order.user_id == user.id)
        .order_by(HelmDashDelivery.created_at.desc())
    )
    return [await _tracking(db, d, o) for d, o in rows.all()]


@router.get("/deliveries/{delivery_id}", response_model=TrackingOut)
async def my_delivery(delivery_id: uuid.UUID, user: CurrentUser, db: Db) -> dict:
    row = (
        await db.execute(
            select(HelmDashDelivery, Order)
            .join(Order, Order.id == HelmDashDelivery.order_id)
            .where(HelmDashDelivery.id == delivery_id, Order.user_id == user.id)
        )
    ).first()
    if row is None:
        raise not_found("Delivery")
    return await _tracking(db, row[0], row[1])
