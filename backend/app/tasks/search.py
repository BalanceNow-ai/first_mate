"""Search index tasks (Typesense). Both are no-ops with a clear log when not configured."""

from __future__ import annotations

import uuid

from app.celery_app import celery
from app.services import search_index
from app.tasks import run_async


@celery.task(name="app.tasks.search.sync_products_to_typesense")
def sync_products_to_typesense() -> dict:
    """Full sync: ensure the collection, upsert active products, delete inactive ones."""
    return run_async(lambda db: search_index.full_sync(db))


@celery.task(
    name="app.tasks.search.sync_product",
    autoretry_for=(search_index.TypesenseError,),
    retry_backoff=True,
    max_retries=5,
)
def sync_product(product_id: str) -> dict:
    """Incremental sync of one product (queued after admin product/stock/fitment changes)."""
    return run_async(lambda db: search_index.sync_one(db, uuid.UUID(product_id)))
