"""Due service-reminder notifications (Celery: ``app.tasks.reminders.notify_due_reminders``).

A reminder is due when it is active and either its date has arrived (Pacific/Auckland
today) or the vessel's recorded engine hours reached ``due_engine_hours``. A due
reminder is notified at most once per ``SERVICE_REMINDER_RENOTIFY_DAYS`` (default 7).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import utcnow
from app.models.vessel import ServiceReminder, Vessel
from app.services import notifications
from app.services.loyalty import NZ_TZ


async def notify_due_reminders(db: AsyncSession, *, now: datetime | None = None) -> dict:
    now = now or utcnow()
    today: date = now.astimezone(NZ_TZ).date()
    cutoff = now - timedelta(days=get_settings().service_reminder_renotify_days)
    rows = (
        await db.execute(
            select(ServiceReminder, Vessel)
            .join(Vessel, Vessel.id == ServiceReminder.vessel_id)
            .where(
                ServiceReminder.status == "active",
                or_(
                    ServiceReminder.due_on <= today,
                    and_(
                        ServiceReminder.due_engine_hours.is_not(None),
                        Vessel.engine_hours.is_not(None),
                        Vessel.engine_hours >= ServiceReminder.due_engine_hours,
                    ),
                ),
                or_(ServiceReminder.last_notified_at.is_(None), ServiceReminder.last_notified_at < cutoff),
            )
            .order_by(ServiceReminder.created_at)
            .with_for_update(of=ServiceReminder, skip_locked=True)
        )
    ).all()
    queued = 0
    for reminder, vessel in rows:
        inserted = await notifications.service_reminder(
            db,
            reminder_id=reminder.id,
            user_id=vessel.user_id,
            today=today,
            payload={
                "reminder_id": str(reminder.id),
                "vessel_id": str(vessel.id),
                "vessel_name": vessel.nickname,
                "title": reminder.title,
                "due_on": reminder.due_on.isoformat() if reminder.due_on else None,
                "due_engine_hours": reminder.due_engine_hours,
                "engine_hours": vessel.engine_hours,
            },
        )
        queued += len(inserted)
        reminder.last_notified_at = now
    await db.flush()
    return {"due": len(rows), "queued": queued, "date": today.isoformat()}
