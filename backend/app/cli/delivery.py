"""Helm Dash local tooling: ``simulate-delivery`` (development/test only).

Posts positions along a straight line from the pickup to the delivery point for the
job's assigned operator. Every position is stored with ``source="simulated"`` and is
labelled to the customer as a local simulation — never as a real vessel position.
"""

from __future__ import annotations

import asyncio
import uuid

from app.config import get_settings
from app.database import async_session, utcnow
from app.services import delivery


async def _simulate(args) -> int:
    if not get_settings().is_local:
        print("simulate-delivery is only available when APP_ENV is development or test.")
        return 2
    try:
        delivery_id = uuid.UUID(args.delivery_id)
    except ValueError:
        print("DELIVERY_ID must be a UUID")
        return 2
    steps = max(1, args.steps)
    for i in range(steps):
        async with async_session() as db:
            try:
                job = await delivery.get_delivery(db, delivery_id)
            except Exception:  # noqa: BLE001
                print("Delivery not found")
                return 1
            if job.operator_id is None or job.status not in delivery.ACTIVE_TRACKING_STATUSES:
                print(f"Delivery is {job.status}; positions are accepted only once an operator has accepted it.")
                return 1
            start = job.pickup_location or job.delivery_coordinates
            end = job.delivery_coordinates
            frac = (i + 1) / steps
            lat = start["lat"] + (end["lat"] - start["lat"]) * frac
            lng = start["lng"] + (end["lng"] - start["lng"]) * frac
            await delivery.record_location(
                db,
                job,
                operator_id=job.operator_id,
                lat=lat,
                lng=lng,
                recorded_at=utcnow(),
                source="simulated",
            )
            await db.commit()
        print(f"[SIMULATED] position {i + 1}/{steps}: {lat:.5f}, {lng:.5f}")
        if i + 1 < steps and args.interval > 0:
            await asyncio.sleep(args.interval)
    return 0


def register(sub) -> None:
    p = sub.add_parser("simulate-delivery", help="Post labelled, simulated Helm Dash positions (local only)")
    p.add_argument("delivery_id", metavar="DELIVERY_ID")
    p.add_argument("--steps", type=int, default=5)
    p.add_argument("--interval", type=float, default=2.0, help="Seconds between positions")
    p.set_defaults(handler=_simulate)
