"""commerce tasks — placeholder replaced by the owning workstream."""

from app.celery_app import celery


@celery.task(name="app.tasks.commerce.release_expired_reservations")
def release_expired_reservations() -> str:
    raise NotImplementedError("release_expired_reservations is implemented by its workstream")
