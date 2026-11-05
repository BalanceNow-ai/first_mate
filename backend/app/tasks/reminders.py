"""reminders tasks — placeholder replaced by the owning workstream."""

from app.celery_app import celery


@celery.task(name="app.tasks.reminders.notify_due_reminders")
def notify_due_reminders() -> str:
    raise NotImplementedError("notify_due_reminders is implemented by its workstream")
