"""Crew Rewards service — placeholder replaced by the rewards-delivery workstream."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order


async def award_for_paid_order(db: AsyncSession, order: Order) -> None:  # noqa: ARG001
    return None


async def reverse_for_refund(db: AsyncSession, order: Order, newly_refunded_cents: int) -> None:  # noqa: ARG001
    return None


async def release_order_entitlement(db: AsyncSession, order: Order) -> None:  # noqa: ARG001
    return None


async def reserve_entitlement_for_order(db: AsyncSession, user_id, entitlement_id, subtotal_cents: int):  # noqa: ARG001
    """Lock and reserve a discount entitlement; return its amount in cents."""
    raise NotImplementedError


async def consume_order_entitlement(db: AsyncSession, order: Order) -> None:  # noqa: ARG001
    return None


async def award_profile_verification_bonus(db: AsyncSession, user_id, request_id) -> None:  # noqa: ARG001
    """1,000 CP once per approved crowdsourced profile (Boat DB spec §4.2)."""
    return None
