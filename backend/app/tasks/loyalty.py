"""Crew Rewards tasks: the monthly crew multiplier bonus."""

from __future__ import annotations

from app.celery_app import celery
from app.tasks import run_async


@celery.task(name="app.tasks.loyalty.calculate_monthly_multipliers")
def calculate_monthly_multipliers(period: str | None = None) -> dict:
    """Award monthly bonuses for ``period`` ("YYYY-MM"; default: previous NZ month).

    Idempotent: each (crew, member, period) bonus has its own ledger key."""
    from app.services import loyalty

    return run_async(lambda s: loyalty.calculate_monthly_multipliers(s, period))
