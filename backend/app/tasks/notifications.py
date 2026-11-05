"""notifications tasks — placeholder replaced by the owning workstream."""

from app.celery_app import celery


@celery.task(name="app.tasks.notifications.dispatch_pending")
def dispatch_pending() -> str:
    raise NotImplementedError("dispatch_pending is implemented by its workstream")
