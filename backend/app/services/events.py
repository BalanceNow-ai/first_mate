"""Domain events raised by the commerce workflow, inside the same DB transaction.

Commerce calls these; the rewards/delivery/notification services implement the
effects. Every handler must be idempotent (keyed on the order id) because provider
events can be delivered more than once.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order


async def order_paid(db: AsyncSession, order: Order) -> None:
    """Payment confirmed by an authentic provider event (exactly once per order)."""
    from app.services import delivery, loyalty, notifications

    await loyalty.award_for_paid_order(db, order)
    await delivery.create_for_paid_order(db, order)
    await notifications.order_paid(db, order)


async def order_refunded(db: AsyncSession, order: Order, newly_refunded_cents: int) -> None:
    """Additional refund amount recorded on a paid order (partial or full)."""
    from app.services import delivery, loyalty, notifications

    await loyalty.reverse_for_refund(db, order, newly_refunded_cents)
    await delivery.cancel_for_refunded_order(db, order)
    await notifications.order_refunded(db, order, newly_refunded_cents)


async def order_released(db: AsyncSession, order: Order) -> None:  # noqa: ARG001
    """An unpaid order was cancelled or expired; its reservation has been released.

    The commerce release path has already returned the stock, restored the cart and
    re-issued any reserved discount entitlement (services.entitlements) before this is
    raised, so there is currently nothing further to do here.
    """
    return None


async def order_status_changed(db: AsyncSession, order: Order, previous: str) -> None:
    """Fulfilment status changed by staff (dispatched, delivered, collected...)."""
    from app.services import notifications

    await notifications.order_status_changed(db, order, previous)
