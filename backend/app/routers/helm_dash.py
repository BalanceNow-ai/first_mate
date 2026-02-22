"""Helm Dash on-demand maritime delivery router."""

import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.helm_dash import HelmDashDelivery
from app.models.order import Order
from app.schemas.helm_dash import (
    HelmDashDeliveryResponse,
    HelmDashQuoteRequest,
    HelmDashQuoteResponse,
    HelmDashStatusUpdate,
)

router = APIRouter(prefix="/helm-dash", tags=["Helm Dash Delivery"])
settings = get_settings()


def _calculate_nautical_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in nautical miles between two points using Haversine formula."""
    R_NM = 3440.065  # Earth radius in nautical miles

    lat1_r, lat2_r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(R_NM * c, 2)


@router.post("/quote", response_model=HelmDashQuoteResponse)
async def get_delivery_quote(
    request: HelmDashQuoteRequest,
) -> HelmDashQuoteResponse:
    """Get a delivery quote for Helm Dash.

    Calculates the fee based on nautical distance from the warehouse
    to the delivery coordinates, and estimates delivery time based
    on average vessel speed.
    """
    nm = _calculate_nautical_miles(
        settings.warehouse_lat, settings.warehouse_lng,
        request.delivery_lat, request.delivery_lng,
    )

    delivery_fee = round(settings.helm_dash_base_fee + (nm * settings.helm_dash_per_nm_fee), 2)
    estimated_minutes = max(15, int((nm / settings.helm_dash_speed_knots) * 60) + 15)

    return HelmDashQuoteResponse(
        delivery_fee=delivery_fee,
        estimated_minutes=estimated_minutes,
        nautical_miles=nm,
    )


@router.get("/deliveries", response_model=list[HelmDashDeliveryResponse])
async def list_deliveries(
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> list[HelmDashDelivery]:
    """List the user's Helm Dash deliveries."""
    result = await db.execute(
        select(HelmDashDelivery)
        .join(Order)
        .where(Order.user_id == user_id)
        .order_by(HelmDashDelivery.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/deliveries/{delivery_id}", response_model=HelmDashDeliveryResponse)
async def get_delivery(
    delivery_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> HelmDashDelivery:
    """Get a specific Helm Dash delivery."""
    result = await db.execute(
        select(HelmDashDelivery)
        .join(Order)
        .where(HelmDashDelivery.id == delivery_id, Order.user_id == user_id)
    )
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        )
    return delivery


@router.patch("/deliveries/{delivery_id}/status", response_model=HelmDashDeliveryResponse)
async def update_delivery_status(
    delivery_id: uuid.UUID,
    status_update: HelmDashStatusUpdate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db),
) -> HelmDashDelivery:
    """Update the status of a Helm Dash delivery (operator/admin)."""
    result = await db.execute(
        select(HelmDashDelivery).where(HelmDashDelivery.id == delivery_id)
    )
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Delivery not found",
        )

    valid_statuses = {"pending", "assigned", "pickup", "en_route", "delivered", "cancelled"}
    if status_update.status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )

    delivery.status = status_update.status
    if status_update.operator_name:
        delivery.operator_name = status_update.operator_name

    await db.flush()
    return delivery
