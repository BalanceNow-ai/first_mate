"""Feedback reveal at window end (spec §9.3: time-based reveal runs reliably and idempotently)."""

from __future__ import annotations

from app.celery_app import celery
from app.tasks import run_async


@celery.task(name="app.tasks.service_feedback.reveal_due_feedback")
def reveal_due_feedback() -> dict:
    """Reveal every feedback window whose 14 days have passed (one-sided reveals included)."""
    from app.services.service_jobs import feedback

    return run_async(lambda s: feedback.reveal_due(s))
