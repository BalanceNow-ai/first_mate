"""Celery application: worker queues and the beat schedule.

Task modules (one per workstream) are listed in ``include`` so the worker registers
every task the schedule references. Start-up runs the same configuration validation
as the API.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_init

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "helm",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.ops",
        "app.tasks.commerce",
        "app.tasks.search",
        "app.tasks.loyalty",
        "app.tasks.notifications",
        "app.tasks.reminders",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Pacific/Auckland",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=240,
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    task_default_queue="default",
    task_routes={
        "app.tasks.search.*": {"queue": "search"},
        "app.tasks.notifications.*": {"queue": "notifications"},
    },
    beat_schedule={
        "worker-heartbeat": {"task": "app.tasks.ops.heartbeat", "schedule": 60.0},
        "release-expired-reservations": {
            "task": "app.tasks.commerce.release_expired_reservations",
            "schedule": 60.0,
        },
        "sync-products-to-typesense": {
            "task": "app.tasks.search.sync_products_to_typesense",
            "schedule": crontab(minute="*/15"),
        },
        "dispatch-notifications": {"task": "app.tasks.notifications.dispatch_pending", "schedule": 30.0},
        "service-reminders": {
            "task": "app.tasks.reminders.notify_due_reminders",
            "schedule": crontab(minute=5, hour=8),  # 08:05 Pacific/Auckland
        },
        # Monthly crew multiplier bonus for the *previous* NZ calendar month.
        "calculate-crew-multipliers": {
            "task": "app.tasks.loyalty.calculate_monthly_multipliers",
            "schedule": crontab(minute=15, hour=0, day_of_month=1),
        },
    },
)


@worker_init.connect
def _validate(**_kwargs) -> None:
    get_settings().validate_runtime()
