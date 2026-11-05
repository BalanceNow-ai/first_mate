"""Discount entitlement lifecycle as seen by checkout and payments.

issued --(checkout)--> reserved --(payment succeeded)--> consumed
                          \\--(order released)--> issued

Every transition is a conditional update so it happens at most once, however many
times a provider event or the expiry task is delivered.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.database import utcnow
from app.models.loyalty import DiscountEntitlement
from app.models.order import Order


async def lock_for_checkout(
    db: AsyncSession, user_id: uuid.UUID, entitlement_id: uuid.UUID, merchandise_subtotal_cents: int
) -> DiscountEntitlement:
    """Lock an entitlement for use at checkout and validate it (no state change yet)."""
    ent = (
        await db.execute(
            select(DiscountEntitlement)
            .where(DiscountEntitlement.id == entitlement_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if ent is None or ent.user_id != user_id:
        raise AppError(404, "entitlement_not_found", "Discount not found")
    if ent.status != "issued":
        raise AppError(409, "entitlement_unavailable", "This discount has already been used or is in use")
    if ent.amount_cents > merchandise_subtotal_cents:
        raise AppError(
            422,
            "discount_exceeds_subtotal",
            "This discount is larger than the order's merchandise total",
            extra={"amount_cents": ent.amount_cents},
        )
    return ent


async def reserve_for_order(db: AsyncSession, ent: DiscountEntitlement, order: Order) -> None:
    """issued -> reserved, bound to ``order`` (the entitlement row is already locked)."""
    ent.status = "reserved"
    ent.order_id = order.id
    ent.reserved_at = utcnow()
    await db.flush()


async def consume_for_order(db: AsyncSession, order: Order) -> bool:
    """reserved -> consumed for the order's entitlement. Returns True if it happened now."""
    if order.discount_entitlement_id is None:
        return False
    result = await db.execute(
        update(DiscountEntitlement)
        .where(
            DiscountEntitlement.id == order.discount_entitlement_id,
            DiscountEntitlement.order_id == order.id,
            DiscountEntitlement.status == "reserved",
        )
        .values(status="consumed", consumed_at=utcnow())
        .returning(DiscountEntitlement.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def release_for_order(db: AsyncSession, order: Order) -> bool:
    """reserved -> issued (unbound) so the customer can use the discount again."""
    if order.discount_entitlement_id is None:
        return False
    result = await db.execute(
        update(DiscountEntitlement)
        .where(
            DiscountEntitlement.id == order.discount_entitlement_id,
            DiscountEntitlement.order_id == order.id,
            DiscountEntitlement.status == "reserved",
        )
        .values(status="issued", order_id=None, reserved_at=None)
        .returning(DiscountEntitlement.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None


async def reclaim_for_paid_order(db: AsyncSession, order: Order) -> bool:
    """For a payment that succeeded after the order was released: the charged amount
    included the discount, so the (re-issued) entitlement is consumed by this order.
    Returns False when it has since been used elsewhere (staff review needed)."""
    if order.discount_entitlement_id is None:
        return True
    result = await db.execute(
        update(DiscountEntitlement)
        .where(
            DiscountEntitlement.id == order.discount_entitlement_id,
            DiscountEntitlement.user_id == order.user_id,
            DiscountEntitlement.status == "issued",
        )
        .values(status="consumed", order_id=order.id, consumed_at=utcnow())
        .returning(DiscountEntitlement.id)
        .execution_options(synchronize_session=False)
    )
    return result.first() is not None
