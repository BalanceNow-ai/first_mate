"""Notification outbox delivery task."""

from __future__ import annotations

from app.celery_app import celery
from app.tasks import run_async


@celery.task(name="app.tasks.notifications.dispatch_pending")
def dispatch_pending() -> dict:
    """Deliver due outbox rows (FOR UPDATE SKIP LOCKED; backoff; dead-letter)."""
    from app.services import notifications

    return run_async(lambda s: notifications.dispatch_pending(s))
