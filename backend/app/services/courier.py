"""Courier label booking boundary.

Live NZ Post / Aramex booking is NOT implemented: no credentials or current API
documentation have been validated (decision D8). ``COURIER_BOOKING_ENABLED`` is refused
at start-up outside development/test. In development/test the *local contract adapter*
creates clearly-marked test shipments (``is_test=True``, tracking ``TEST-...``) so the
dispatch workflow can be exercised end to end; it never contacts a carrier.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError
from app.models.order import Order
from app.models.shipping import CourierShipment


@dataclass
class Booking:
    provider: str
    service_name: str
    label_reference: str
    tracking_number: str
    is_test: bool


class CourierAdapter:
    name: str

    async def book(self, order: Order) -> Booking:  # pragma: no cover - interface
        raise NotImplementedError


class LocalContractCourierAdapter(CourierAdapter):
    """Development/test only: returns a well-formed booking without contacting anyone."""

    name = "local_contract"

    async def book(self, order: Order) -> Booking:
        token = secrets.token_hex(5).upper()
        return Booking(
            provider=self.name,
            service_name=f"{get_settings().courier_service_name} (test booking)",
            label_reference=f"TEST-LABEL-{order.order_number}",
            tracking_number=f"TEST-{token}",
            is_test=True,
        )


def get_adapter() -> CourierAdapter:
    if get_settings().is_local:
        return LocalContractCourierAdapter()
    raise AppError(
        503,
        "courier_booking_unavailable",
        "Courier label booking is not available. Book the shipment with the carrier directly "
        "and record the tracking number on the order.",
    )


async def existing_shipment(db: AsyncSession, order_id) -> CourierShipment | None:
    return (
        await db.execute(select(CourierShipment).where(CourierShipment.order_id == order_id))
    ).scalar_one_or_none()


async def book_shipment(db: AsyncSession, order: Order) -> tuple[CourierShipment, bool]:
    """Create the order's shipment (idempotent: an existing shipment is returned)."""
    if order.delivery_type != "courier":
        raise AppError(409, "not_a_courier_order", "Only courier orders have courier shipments")
    if order.status not in ("paid", "ready_for_dispatch"):
        raise AppError(
            409, "order_not_ready", f"A {order.status} order cannot be booked with a courier"
        )
    shipment = await existing_shipment(db, order.id)
    if shipment is not None:
        return shipment, False
    adapter = get_adapter()
    booking = await adapter.book(order)
    shipment = CourierShipment(
        order_id=order.id,
        provider=booking.provider,
        service_name=booking.service_name,
        label_reference=booking.label_reference,
        tracking_number=booking.tracking_number,
        status="label_created",
        is_test=booking.is_test,
    )
    db.add(shipment)
    order.tracking_number = booking.tracking_number
    order.courier = booking.provider
    await db.flush()
    return shipment, True
