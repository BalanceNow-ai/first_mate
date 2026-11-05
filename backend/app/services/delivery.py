"""Helm Dash delivery service — placeholder replaced by the rewards-delivery workstream."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order


async def create_for_paid_order(db: AsyncSession, order: Order) -> None:  # noqa: ARG001
    return None
