"""Service reminder notification task."""

from __future__ import annotations

from app.celery_app import celery
from app.tasks import run_async


@celery.task(name="app.tasks.reminders.notify_due_reminders")
def notify_due_reminders() -> dict:
    """Queue service_reminder notifications for due reminders (max once per 7 days)."""
    from app.services import reminders

    return run_async(lambda s: reminders.notify_due_reminders(s))
