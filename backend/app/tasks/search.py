"""search tasks — placeholder replaced by the owning workstream."""

from app.celery_app import celery


@celery.task(name="app.tasks.search.sync_products_to_typesense")
def sync_products_to_typesense() -> str:
    raise NotImplementedError("sync_products_to_typesense is implemented by its workstream")
