"""Crew Rewards and notification operations."""

from __future__ import annotations

import json

from app.database import async_session
from app.services import loyalty, notifications, reminders


async def _multipliers(args) -> int:
    async with async_session() as db:
        summary = await loyalty.calculate_monthly_multipliers(db, args.period)
        await db.commit()
    print(json.dumps(summary))
    return 0


async def _dispatch(args) -> int:  # noqa: ARG001
    async with async_session() as db:
        counts = await notifications.dispatch_pending(db)
    print(json.dumps(counts))
    return 0


async def _reminders(args) -> int:  # noqa: ARG001
    async with async_session() as db:
        summary = await reminders.notify_due_reminders(db)
        await db.commit()
    print(json.dumps(summary))
    return 0


def register(sub) -> None:
    p = sub.add_parser("calculate-multipliers", help="Award monthly crew multiplier bonuses (idempotent)")
    p.add_argument("--period", help="YYYY-MM (default: previous Pacific/Auckland month)")
    p.set_defaults(handler=_multipliers)
    p = sub.add_parser("dispatch-notifications", help="Deliver due notification outbox rows once")
    p.set_defaults(handler=_dispatch)
    p = sub.add_parser("notify-reminders", help="Queue due service-reminder notifications")
    p.set_defaults(handler=_reminders)
