"""Fulfilment state machine for paid orders (shared by staff actions and Helm Dash).

Payment-driven transitions (pending_payment -> paid / cancelled / expired / refunded /
payment_review) belong to the payment workflow, not here.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.order import Order
from app.services import events

# (from_status, to_status) -> delivery types for which the transition is allowed
FULFILMENT_TRANSITIONS: dict[tuple[str, str], set[str]] = {
    ("paid", "ready_for_dispatch"): {"courier", "helm_dash", "click_and_collect"},
    ("ready_for_dispatch", "dispatched"): {"courier", "helm_dash"},
    ("paid", "dispatched"): {"helm_dash"},  # operator picked up directly from the warehouse
    ("dispatched", "delivered"): {"courier", "helm_dash"},
    ("ready_for_dispatch", "collected"): {"click_and_collect"},
    ("paid", "collected"): {"click_and_collect"},
}

# Which actor roles may drive each target status.
ROLE_TARGETS: dict[str, set[str]] = {
    "admin": {"ready_for_dispatch", "dispatched", "delivered", "collected"},
    "dispatcher": {"ready_for_dispatch", "dispatched", "delivered", "collected"},
    # Helm Dash operators only move orders via their delivery job.
    "helm_dash_workflow": {"dispatched", "delivered"},
}


def can_transition(order: Order, new_status: str) -> bool:
    allowed = FULFILMENT_TRANSITIONS.get((order.status, new_status))
    return bool(allowed) and (order.delivery_type or "courier") in allowed


async def transition_fulfilment(
    db: AsyncSession,
    order: Order,
    new_status: str,
    *,
    actor_role: str,
    tracking_number: str | None = None,
    courier: str | None = None,
) -> None:
    """Apply a fulfilment transition or raise AppError(409/403). Not idempotent by design:
    callers that may repeat (e.g. delivery events) should check ``order.status`` first."""
    if new_status not in ROLE_TARGETS.get(actor_role, set()):
        raise AppError(403, "forbidden", "This role cannot set that order status")
    if order.payment_status not in ("succeeded", "partially_refunded"):
        raise AppError(409, "order_not_paid", "Only paid orders can be fulfilled")
    if not can_transition(order, new_status):
        raise AppError(
            409,
            "invalid_transition",
            f"Cannot move a {order.delivery_type} order from {order.status} to {new_status}",
        )
    previous = order.status
    order.status = new_status
    if tracking_number:
        order.tracking_number = tracking_number
    if courier:
        order.courier = courier
    await db.flush()
    await events.order_status_changed(db, order, previous)
