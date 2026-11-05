"""Helm Dash operator payout records (decision D10).

A payout *record* is created when a delivery is delivered. With
``HELM_DASH_OPERATOR_SHARE_BPS`` unset the record is ``rate_unconfigured`` with no
amount — no payout entitlement is implied. With a share configured the amount is
``floor(fee x bps / 10000)`` and the record awaits review. Approval records the
approval only: live payouts are disabled and no payout provider is ever called.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.helm_dash import HelmDashDelivery, OperatorPayout
from app.services import audit
from app.services.loyalty import period_bounds


async def create_for_delivery(db: AsyncSession, delivery: HelmDashDelivery) -> None:
    if delivery.operator_id is None:
        return
    bps = get_settings().helm_dash_operator_share_bps
    amount = None if bps is None else delivery.delivery_fee_cents * bps // 10_000
    await db.execute(
        insert(OperatorPayout)
        .values(
            id=uuid.uuid4(),
            delivery_id=delivery.id,
            operator_id=delivery.operator_id,
            gross_fee_cents=delivery.delivery_fee_cents,
            share_bps=bps,
            amount_cents=amount,
            status="rate_unconfigured" if bps is None else "pending_review",
        )
        .on_conflict_do_nothing(index_elements=[OperatorPayout.delivery_id])
    )


async def approve(db: AsyncSession, payout_id: uuid.UUID, admin_id: uuid.UUID) -> OperatorPayout:
    payout = (
        await db.execute(select(OperatorPayout).where(OperatorPayout.id == payout_id).with_for_update())
    ).scalar_one_or_none()
    if payout is None:
        raise not_found("Payout")
    if payout.status == "rate_unconfigured":
        raise AppError(
            409, "rate_unconfigured", "No operator share is configured, so this payout has no amount to approve"
        )
    if payout.status != "pending_review":
        raise AppError(409, "invalid_transition", f"A {payout.status} payout cannot be approved")
    payout.status = "approved"
    payout.approved_by = admin_id
    payout.approved_at = utcnow()
    await audit.record(
        db, admin_id, "payout_approve", "operator_payout", payout.id, {"amount_cents": payout.amount_cents}
    )
    await db.flush()
    await db.refresh(payout)
    return payout


async def reconciliation(db: AsyncSession, period: str) -> dict:
    start, end = period_bounds(period)
    delivered = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(HelmDashDelivery.delivery_fee_cents), 0)).where(
                HelmDashDelivery.status == "delivered",
                HelmDashDelivery.delivered_at >= start,
                HelmDashDelivery.delivered_at < end,
            )
        )
    ).one()
    rows = await db.execute(
        select(
            OperatorPayout.status,
            func.count(),
            func.coalesce(func.sum(OperatorPayout.amount_cents), 0),
            func.coalesce(func.sum(OperatorPayout.gross_fee_cents), 0),
        )
        .join(HelmDashDelivery, HelmDashDelivery.id == OperatorPayout.delivery_id)
        .where(HelmDashDelivery.delivered_at >= start, HelmDashDelivery.delivered_at < end)
        .group_by(OperatorPayout.status)
        .order_by(OperatorPayout.status)
    )
    settings = get_settings()
    return {
        "period": period,
        "currency": "NZD",
        "delivered_count": int(delivered[0]),
        "delivery_fees_cents": int(delivered[1]),
        "payouts_by_status": [
            {"status": s, "count": int(c), "amount_cents": int(a), "gross_fee_cents": int(g)} for s, c, a, g in rows
        ],
        "operator_share_bps": settings.helm_dash_operator_share_bps,
        "live_payouts_enabled": False,
    }
