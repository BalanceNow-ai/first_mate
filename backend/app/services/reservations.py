"""Stock reservations and the shared order release path.

Stock moves only through conditional statements, so each transition happens exactly
once even when callers race or repeat:

    reserve   UPDATE products SET stock = stock - q WHERE id AND is_active AND stock >= q
    consume   reservation reserved -> consumed            (payment succeeded)
    release   reservation reserved -> released, stock + q (cancel / expiry / provider cancel)
    restock   reservation consumed -> restocked, stock + q (full refund before dispatch)
    re-reserve released -> consumed, stock - q            (payment succeeded after release)

Rows are always touched in product-id order to avoid deadlocks.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.database import utcnow
from app.models.cart import CartItem
from app.models.order import Order, StockReservation
from app.models.product import Product
from app.services import entitlements, events
from app.services.cart_service import MAX_LINE_QUANTITY

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- stock
async def decrement_stock(db: AsyncSession, lines: list[tuple[uuid.UUID, int]]) -> list[uuid.UUID]:
    """Conditionally take stock for every line. Returns the product ids that could not be
    reserved (the caller must roll back when the list is non-empty)."""
    failed: list[uuid.UUID] = []
    for product_id, qty in sorted(lines):
        row = (
            await db.execute(
                update(Product)
                .where(
                    Product.id == product_id,
                    Product.is_active.is_(True),
                    Product.stock_quantity >= qty,
                )
                .values(stock_quantity=Product.stock_quantity - qty)
                .returning(Product.id)
                .execution_options(synchronize_session=False)
            )
        ).first()
        if row is None:
            failed.append(product_id)
    return failed


async def increment_stock(db: AsyncSession, lines: list[tuple[uuid.UUID, int]]) -> None:
    for product_id, qty in sorted(lines):
        await db.execute(
            update(Product)
            .where(Product.id == product_id)
            .values(stock_quantity=Product.stock_quantity + qty)
            .execution_options(synchronize_session=False)
        )


async def _transition(
    db: AsyncSession, order_id: uuid.UUID, src: str, dst: str
) -> list[tuple[uuid.UUID, int]]:
    rows = await db.execute(
        update(StockReservation)
        .where(StockReservation.order_id == order_id, StockReservation.status == src)
        .values(status=dst, updated_at=utcnow())
        .returning(StockReservation.product_id, StockReservation.quantity)
        .execution_options(synchronize_session=False)
    )
    return [(r[0], r[1]) for r in rows]


async def reservation_count(db: AsyncSession, order_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(StockReservation)
            .where(StockReservation.order_id == order_id)
        )
    ).scalar_one()


async def consume(db: AsyncSession, order: Order) -> int:
    """reserved -> consumed. Returns the number of reservations consumed now."""
    return len(await _transition(db, order.id, "reserved", "consumed"))


async def release(db: AsyncSession, order: Order) -> list[tuple[uuid.UUID, int]]:
    """reserved -> released and give the stock back (exactly once)."""
    released = await _transition(db, order.id, "reserved", "released")
    await increment_stock(db, released)
    return released


async def restock_consumed(db: AsyncSession, order: Order) -> list[tuple[uuid.UUID, int]]:
    """consumed -> restocked and give the stock back (full refund before dispatch)."""
    restocked = await _transition(db, order.id, "consumed", "restocked")
    await increment_stock(db, restocked)
    return restocked


async def rereserve_released(db: AsyncSession, order: Order) -> bool:
    """For a payment that succeeded after release: take the stock again and mark the
    reservations consumed. Returns False (with nothing changed by this call's caller
    savepoint) when any line can no longer be reserved."""
    rows = (
        await db.execute(
            select(StockReservation.product_id, StockReservation.quantity).where(
                StockReservation.order_id == order.id, StockReservation.status == "released"
            )
        )
    ).all()
    if not rows:
        return False
    failed = await decrement_stock(db, [(r[0], r[1]) for r in rows])
    if failed:
        return False
    await _transition(db, order.id, "released", "consumed")
    return True


# --------------------------------------------------------------------------- cart
async def restore_cart(db: AsyncSession, order: Order) -> None:
    """Merge the order's lines back into the customer's cart (capped per line)."""
    for item in sorted(order.items, key=lambda i: i.product_id):
        stmt = insert(CartItem).values(
            id=uuid.uuid4(),
            user_id=order.user_id,
            product_id=item.product_id,
            quantity=min(item.quantity, MAX_LINE_QUANTITY),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[CartItem.user_id, CartItem.product_id],
            set_={
                "quantity": func.least(
                    CartItem.quantity + stmt.excluded.quantity, MAX_LINE_QUANTITY
                ),
                "updated_at": utcnow(),
            },
        )
        await db.execute(stmt)


async def remove_from_cart(db: AsyncSession, order: Order) -> None:
    """Undo ``restore_cart`` when a released order is paid after all (best effort)."""
    for item in sorted(order.items, key=lambda i: i.product_id):
        where = and_(CartItem.user_id == order.user_id, CartItem.product_id == item.product_id)
        await db.execute(delete(CartItem).where(where, CartItem.quantity <= item.quantity))
        await db.execute(
            update(CartItem)
            .where(where, CartItem.quantity > item.quantity)
            .values(quantity=CartItem.quantity - item.quantity)
            .execution_options(synchronize_session=False)
        )


# --------------------------------------------------------------------------- orders
async def lock_order(
    db: AsyncSession, order_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> Order | None:
    """Load and row-lock an order (fresh attributes, items loaded)."""
    q = select(Order).where(Order.id == order_id)
    if user_id is not None:
        q = q.where(Order.user_id == user_id)
    q = q.with_for_update(of=Order).execution_options(populate_existing=True)
    order = (await db.execute(q)).scalar_one_or_none()
    if order is not None:
        await db.refresh(order, attribute_names=["items"])
    return order


async def load_items(db: AsyncSession, order: Order) -> None:
    await db.refresh(order, attribute_names=["items"])


async def release_order(
    db: AsyncSession,
    order: Order,
    *,
    new_status: str,
    reason: str,
    cancel_provider: bool = True,
) -> bool:
    """Release an unpaid order (row already locked): cancel the provider intent, give the
    stock back, restore the cart and the discount, record why. Returns False when the
    order must not be released (it is no longer pending, or the provider reports the
    payment succeeded / is processing — the webhook will settle it)."""
    assert new_status in ("cancelled", "expired")
    if order.status != "pending_payment" or order.payment_status == "succeeded":
        return False
    if cancel_provider and order.payment_intent_id and order.payment_provider == "stripe":
        from app.services.payment_providers import get_provider

        provider_status = await get_provider("stripe").cancel_intent(order)
        if provider_status == "succeeded":
            logger.info("Order %s not released: provider reports payment succeeded", order.id)
            return False
        if provider_status not in ("canceled",):
            raise AppError(
                409,
                "payment_processing",
                "This payment is being processed and cannot be cancelled now",
            )
    await load_items(db, order)
    await release(db, order)
    await restore_cart(db, order)
    await entitlements.release_for_order(db, order)
    order.status = new_status
    order.cancelled_at = utcnow()
    order.cancel_reason = reason
    await db.flush()
    await events.order_released(db, order)
    logger.info("Order %s released (%s)", order.id, reason)
    return True


async def release_expired(db: AsyncSession, *, now=None, limit: int | None = None) -> int:
    """Release pending orders whose reservation expired. Orders locked by another
    transaction are skipped (SKIP LOCKED); payments that are processing or awaiting
    customer authentication get a grace window. Each order is released in its own
    savepoint so one provider failure does not undo the others."""
    settings = get_settings()
    now = now or utcnow()
    limit = limit or settings.reservation_release_batch_size
    grace = timedelta(minutes=settings.payment_processing_grace_minutes)
    orders = list(
        (
            await db.execute(
                select(Order)
                .where(Order.status == "pending_payment", Order.expires_at < now)
                .order_by(Order.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    released = 0
    for order in orders:
        if (
            order.payment_status in ("processing", "requires_action")
            and order.expires_at + grace > now
        ):
            continue
        try:
            async with db.begin_nested():
                if await release_order(
                    db, order, new_status="expired", reason="reservation_expired"
                ):
                    released += 1
        except AppError:
            logger.warning("Order %s could not be released now; will retry", order.id)
        except Exception:
            logger.exception("Order %s release failed; will retry", order.id)
    await db.flush()
    return released
