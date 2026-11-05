"""Commerce tasks: release stock held by unpaid orders whose reservation expired."""

from __future__ import annotations

from app.celery_app import celery
from app.services.reservations import release_expired
from app.tasks import run_async


@celery.task(name="app.tasks.commerce.release_expired_reservations")
def release_expired_reservations() -> str:
    """Scheduled every minute by beat (see celery_app). Safe to run concurrently and
    repeatedly: orders are claimed with FOR UPDATE SKIP LOCKED and every release is a
    conditional, exactly-once transition."""
    released = run_async(lambda session: release_expired(session))
    return f"released {released}"
