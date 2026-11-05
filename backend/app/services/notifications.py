"""Notification outbox service — placeholder replaced by the rewards-delivery workstream."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order


async def order_paid(db: AsyncSession, order: Order) -> None:  # noqa: ARG001
    return None


async def order_refunded(db: AsyncSession, order: Order, newly_refunded_cents: int) -> None:  # noqa: ARG001
    return None


async def order_status_changed(db: AsyncSession, order: Order, previous: str) -> None:  # noqa: ARG001
    return None
