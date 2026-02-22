"""Celery application configuration for background tasks."""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "helm",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Pacific/Auckland",
    enable_utc=True,
    task_routes={
        "app.tasks.search.*": {"queue": "search"},
        "app.tasks.email.*": {"queue": "email"},
        "app.tasks.ai.*": {"queue": "ai"},
    },
    beat_schedule={
        # Sync products to Typesense every 15 minutes
        "sync-products-to-typesense": {
            "task": "app.tasks.search.sync_products_to_typesense",
            "schedule": crontab(minute="*/15"),
        },
        # Calculate monthly crew multipliers at midnight on the 1st
        "calculate-crew-multipliers": {
            "task": "app.tasks.loyalty.calculate_monthly_multipliers",
            "schedule": crontab(minute=0, hour=0, day_of_month=1),
        },
    },
)
