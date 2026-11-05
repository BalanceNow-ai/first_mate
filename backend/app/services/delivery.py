"""Helm Dash delivery lifecycle: creation from paid orders, dispatch, operator workflow,
reported positions and customer tracking.

MVP scope: dispatch is a responsive web workflow (dispatcher/admin + operator roles);
there is no native skipper app. Positions are only ever those *reported* by the
assigned operator's device (or explicitly labelled local simulations) — never
interpolated or invented. The platform does not certify operators or dangerous-goods
carriage; ``certification_reference`` is recorded as unverified free text.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.helm_dash import (
    DeliveryLocationUpdate,
    DeliveryOperator,
    DeliveryStatusEvent,
    HelmDashDelivery,
)
from app.models.order import Order
from app.models.shipping import DeliveryQuote
from app.services import audit

ACTIVE_TRACKING_STATUSES = ("accepted", "picked_up", "en_route")
TERMINAL_STATUSES = ("delivered", "failed", "cancelled")

# Explicit allowed transitions: (from, to) -> actors allowed to perform it.
TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("awaiting_dispatch", "assigned"): {"dispatcher"},
    ("assigned", "assigned"): {"dispatcher"},  # reassign
    ("accepted", "assigned"): {"dispatcher"},  # reassign before pickup
    ("assigned", "accepted"): {"operator"},
    ("assigned", "awaiting_dispatch"): {"operator", "dispatcher"},  # decline / unassign
    ("accepted", "picked_up"): {"operator"},
    ("picked_up", "en_route"): {"operator"},
    ("en_route", "delivered"): {"operator"},
    ("accepted", "failed"): {"operator", "dispatcher"},
    ("picked_up", "failed"): {"operator", "dispatcher"},
    ("en_route", "failed"): {"operator", "dispatcher"},
    ("accepted", "cancelled"): {"dispatcher", "system"},
    ("awaiting_dispatch", "cancelled"): {"dispatcher", "system"},
    ("assigned", "cancelled"): {"dispatcher", "system"},
}
OPERATOR_STATUS_TARGETS = {"picked_up", "en_route", "delivered", "failed"}


def _point(lat: float, lng: float, name: str | None = None) -> dict:
    data: dict = {"lat": float(lat), "lng": float(lng)}
    if name:
        data["name"] = name
    return data


async def create_for_paid_order(db: AsyncSession, order: Order) -> None:
    """Create the Helm Dash job for a paid helm_dash order (idempotent: unique order_id)."""
    if order.delivery_type != "helm_dash":
        return
    if order.payment_status not in ("succeeded", "partially_refunded"):
        return
    coords = order.helm_dash_coordinates or {}
    if "lat" not in coords or "lng" not in coords:
        await audit.record(db, None, "helm_dash_missing_coordinates", "order", order.id, None)
        return
    quote = await db.get(DeliveryQuote, order.delivery_quote_id) if order.delivery_quote_id else None
    settings = get_settings()
    delivery_id = uuid.uuid4()
    stmt = (
        insert(HelmDashDelivery)
        .values(
            id=delivery_id,
            order_id=order.id,
            area_id=quote.operating_area_id if quote else None,
            status="awaiting_dispatch",
            pickup_location=_point(settings.warehouse_lat, settings.warehouse_lng, "Helm warehouse"),
            delivery_coordinates=_point(coords["lat"], coords["lng"]),
            delivery_location_name=coords.get("name") or coords.get("location_name"),
            nautical_miles=quote.nautical_miles if quote else None,
            delivery_fee_cents=quote.price_cents if quote else order.shipping_cents,
            estimated_delivery_minutes=quote.estimated_minutes if quote else None,
        )
        .on_conflict_do_nothing(index_elements=[HelmDashDelivery.order_id])
        .returning(HelmDashDelivery.id)
    )
    if (await db.execute(stmt)).first() is None:
        return  # already created by an earlier delivery of the event
    db.add(
        DeliveryStatusEvent(
            delivery_id=delivery_id,
            from_status=None,
            to_status="awaiting_dispatch",
            actor_id=None,
            actor_role="system",
            note="Created from paid order",
        )
    )
    await db.flush()


# ----------------------------------------------------------------------------- access
async def get_delivery(db: AsyncSession, delivery_id: uuid.UUID, *, lock: bool = False) -> HelmDashDelivery:
    """With ``lock``: the delivery's order is locked first, then the delivery (D22 —
    the same order as refunds, which hold the order and then cancel the delivery)."""
    q = select(HelmDashDelivery).where(HelmDashDelivery.id == delivery_id)
    if lock:
        order_id = (
            await db.execute(select(HelmDashDelivery.order_id).where(HelmDashDelivery.id == delivery_id))
        ).scalar_one_or_none()
        if order_id is None:
            raise not_found("Delivery")
        await db.execute(select(Order.id).where(Order.id == order_id).with_for_update())
        q = q.with_for_update().execution_options(populate_existing=True)
    d = (await db.execute(q)).scalar_one_or_none()
    if d is None:
        raise not_found("Delivery")
    return d


async def get_operator_job(
    db: AsyncSession, operator_id: uuid.UUID, delivery_id: uuid.UUID, *, lock: bool = False
) -> HelmDashDelivery:
    """A job assigned to this operator; any other job is indistinguishable from missing."""
    d = await get_delivery(db, delivery_id, lock=lock)
    if d.operator_id != operator_id:
        raise not_found("Delivery")
    return d


async def get_operator_profile(db: AsyncSession, user_id: uuid.UUID) -> DeliveryOperator:
    op = await db.get(DeliveryOperator, user_id)
    if op is None:
        raise AppError(404, "not_an_operator", "No Helm Dash operator profile for this account")
    return op


async def require_active_operator(db: AsyncSession, user_id: uuid.UUID) -> DeliveryOperator:
    """A deactivated operator may decline jobs but cannot progress them or report positions."""
    op = await get_operator_profile(db, user_id)
    if not op.active:
        raise AppError(403, "operator_not_active", "Your operator profile is not active")
    return op


UNDELIVERABLE_ORDER_STATUSES = {"refunded", "cancelled", "expired", "payment_review"}


async def _require_deliverable_order(db: AsyncSession, delivery: HelmDashDelivery) -> None:
    order = await db.get(Order, delivery.order_id)
    if order is None or order.status in UNDELIVERABLE_ORDER_STATUSES or order.payment_status == "refunded":
        raise AppError(409, "order_not_deliverable", "The order for this delivery is no longer deliverable")


async def cancel_for_refunded_order(db: AsyncSession, order: Order) -> None:
    """A fully refunded order's delivery job is cancelled if it has not been picked up."""
    if order.delivery_type != "helm_dash" or order.payment_status != "refunded":
        return
    delivery = (
        await db.execute(select(HelmDashDelivery).where(HelmDashDelivery.order_id == order.id).with_for_update())
    ).scalar_one_or_none()
    if delivery is None or delivery.status not in ("awaiting_dispatch", "assigned", "accepted"):
        return
    await _transition(db, delivery, "cancelled", actor_id=None, actor="system", note="Order fully refunded")


# ------------------------------------------------------------------------ transitions
async def _transition(
    db: AsyncSession,
    delivery: HelmDashDelivery,
    to_status: str,
    *,
    actor_id: uuid.UUID | None,
    actor: str,
    note: str | None = None,
) -> DeliveryStatusEvent:
    allowed = TRANSITIONS.get((delivery.status, to_status))
    if not allowed or actor not in allowed:
        raise AppError(409, "invalid_transition", f"Cannot move a delivery from {delivery.status} to {to_status}")
    order = (await db.execute(select(Order).where(Order.id == delivery.order_id).with_for_update())).scalar_one()
    from app.services import order_lifecycle

    # Keep the order's fulfilment status in step (skip if it is already there).
    if to_status == "picked_up" and order.status not in ("dispatched", "delivered"):
        await order_lifecycle.transition_fulfilment(db, order, "dispatched", actor_role="helm_dash_workflow")
    if to_status == "delivered" and order.status != "delivered":
        if order.status != "dispatched":
            await order_lifecycle.transition_fulfilment(db, order, "dispatched", actor_role="helm_dash_workflow")
        await order_lifecycle.transition_fulfilment(db, order, "delivered", actor_role="helm_dash_workflow")

    previous = delivery.status
    now = utcnow()
    delivery.status = to_status
    if to_status == "assigned":
        delivery.assigned_at = now
        delivery.accepted_at = None
    elif to_status == "awaiting_dispatch":
        delivery.operator_id = None
        delivery.operator_name = None
        delivery.assigned_at = None
        delivery.accepted_at = None
    elif to_status == "accepted":
        delivery.accepted_at = now
    elif to_status == "picked_up":
        delivery.picked_up_at = now
    elif to_status == "delivered":
        delivery.delivered_at = now
    event = DeliveryStatusEvent(
        delivery_id=delivery.id,
        from_status=previous,
        to_status=to_status,
        actor_id=actor_id,
        actor_role=actor,
        note=note,
    )
    db.add(event)
    await db.flush()
    if to_status == "delivered":
        from app.services import payouts

        await payouts.create_for_delivery(db, delivery)
    from app.services import notifications

    await notifications.helm_dash_status(db, delivery, order, event.id)
    return event


async def assign(
    db: AsyncSession, delivery_id: uuid.UUID, operator_user_id: uuid.UUID, dispatcher_id: uuid.UUID, note: str | None
) -> HelmDashDelivery:
    delivery = await get_delivery(db, delivery_id, lock=True)
    await _require_deliverable_order(db, delivery)
    op = await db.get(DeliveryOperator, operator_user_id)
    if op is None or not op.active:
        raise AppError(409, "operator_not_active", "Assign an active Helm Dash operator")
    if delivery.area_id is not None and op.area_id != delivery.area_id:
        raise AppError(409, "operator_wrong_area", "That operator does not serve this delivery's area")
    if delivery.status == "assigned" and delivery.operator_id == op.user_id:
        raise AppError(409, "already_assigned", "That operator is already assigned")
    if (delivery.status, "assigned") not in TRANSITIONS:
        raise AppError(409, "invalid_transition", f"Cannot assign a {delivery.status} delivery")
    delivery.operator_id = op.user_id
    delivery.operator_name = op.display_name
    await _transition(db, delivery, "assigned", actor_id=dispatcher_id, actor="dispatcher", note=note)
    await audit.record(db, dispatcher_id, "helm_dash_assign", "delivery", delivery.id, {"operator_id": str(op.user_id)})
    await db.flush()
    return delivery


async def cancel(
    db: AsyncSession, delivery_id: uuid.UUID, dispatcher_id: uuid.UUID, reason: str | None
) -> HelmDashDelivery:
    delivery = await get_delivery(db, delivery_id, lock=True)
    await _transition(db, delivery, "cancelled", actor_id=dispatcher_id, actor="dispatcher", note=reason)
    await audit.record(db, dispatcher_id, "helm_dash_cancel", "delivery", delivery.id, {"reason": reason})
    return delivery


async def dispatcher_fail(
    db: AsyncSession, delivery_id: uuid.UUID, dispatcher_id: uuid.UUID, reason: str | None
) -> HelmDashDelivery:
    delivery = await get_delivery(db, delivery_id, lock=True)
    await _transition(db, delivery, "failed", actor_id=dispatcher_id, actor="dispatcher", note=reason)
    return delivery


async def operator_accept(db: AsyncSession, operator_id: uuid.UUID, delivery_id: uuid.UUID) -> HelmDashDelivery:
    await require_active_operator(db, operator_id)
    delivery = await get_operator_job(db, operator_id, delivery_id, lock=True)
    await _require_deliverable_order(db, delivery)
    await _transition(db, delivery, "accepted", actor_id=operator_id, actor="operator")
    return delivery


async def operator_decline(
    db: AsyncSession, operator_id: uuid.UUID, delivery_id: uuid.UUID, reason: str | None
) -> HelmDashDelivery:
    delivery = await get_operator_job(db, operator_id, delivery_id, lock=True)
    await _transition(
        db, delivery, "awaiting_dispatch", actor_id=operator_id, actor="operator", note=reason or "Declined by operator"
    )
    return delivery


async def operator_status(
    db: AsyncSession, operator_id: uuid.UUID, delivery_id: uuid.UUID, status: str, note: str | None
) -> HelmDashDelivery:
    if status not in OPERATOR_STATUS_TARGETS:
        raise AppError(422, "invalid_status", "Operators can set picked_up, en_route, delivered or failed")
    await require_active_operator(db, operator_id)
    delivery = await get_operator_job(db, operator_id, delivery_id, lock=True)
    await _transition(db, delivery, status, actor_id=operator_id, actor="operator", note=note)
    return delivery


# --------------------------------------------------------------------------- location
async def record_location(
    db: AsyncSession,
    delivery: HelmDashDelivery,
    *,
    operator_id: uuid.UUID,
    lat: float,
    lng: float,
    recorded_at: datetime,
    accuracy_m: float | None = None,
    heading_deg: float | None = None,
    speed_knots: float | None = None,
    source: str = "operator_device",
    now: datetime | None = None,
) -> DeliveryLocationUpdate:
    settings = get_settings()
    now = now or utcnow()
    if delivery.operator_id != operator_id:
        raise not_found("Delivery")
    await require_active_operator(db, operator_id)
    if delivery.status not in ACTIVE_TRACKING_STATUSES:
        raise AppError(409, "not_trackable", f"Positions are not accepted while the delivery is {delivery.status}")
    if recorded_at.tzinfo is None:
        raise AppError(422, "timezone_required", "recorded_at must include a timezone")
    if recorded_at > now + timedelta(seconds=settings.helm_dash_location_future_skew_seconds):
        raise AppError(422, "location_in_future", "recorded_at is in the future")
    if recorded_at < now - timedelta(seconds=settings.helm_dash_location_max_age_seconds):
        raise AppError(422, "location_stale", "recorded_at is too old to be a live position")
    update = DeliveryLocationUpdate(
        delivery_id=delivery.id,
        operator_id=operator_id,
        lat=lat,
        lng=lng,
        accuracy_m=accuracy_m,
        heading_deg=heading_deg,
        speed_knots=speed_knots,
        source=source,
        recorded_at=recorded_at,
    )
    db.add(update)
    await db.flush()
    return update


async def latest_location(db: AsyncSession, delivery: HelmDashDelivery) -> DeliveryLocationUpdate | None:
    """Most recent position reported by the *currently assigned* operator."""
    if delivery.operator_id is None:
        return None
    return (
        await db.execute(
            select(DeliveryLocationUpdate)
            .where(
                DeliveryLocationUpdate.delivery_id == delivery.id,
                DeliveryLocationUpdate.operator_id == delivery.operator_id,
            )
            .order_by(DeliveryLocationUpdate.recorded_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def location_view(update: DeliveryLocationUpdate | None, now: datetime | None = None) -> dict | None:
    if update is None:
        return None
    now = now or utcnow()
    simulated = update.source == "simulated"
    return {
        "lat": update.lat,
        "lng": update.lng,
        "accuracy_m": update.accuracy_m,
        "heading_deg": update.heading_deg,
        "speed_knots": update.speed_knots,
        "recorded_at": update.recorded_at,
        "source": update.source,
        "is_simulated": simulated,
        "source_label": (
            "Local simulation — not a real vessel position" if simulated else "Reported by the skipper's device"
        ),
        "age_seconds": max(0, int((now - update.recorded_at).total_seconds())),
    }


async def timeline(db: AsyncSession, delivery_id: uuid.UUID) -> list[DeliveryStatusEvent]:
    return list(
        (
            await db.execute(
                select(DeliveryStatusEvent)
                .where(DeliveryStatusEvent.delivery_id == delivery_id)
                .order_by(DeliveryStatusEvent.created_at, DeliveryStatusEvent.id)
            )
        ).scalars()
    )
