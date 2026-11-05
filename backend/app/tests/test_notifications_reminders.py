"""Service reminders task: due by NZ date or engine hours, at most once per 7 days."""

import asyncio
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.database import async_session
from app.models.notifications import NotificationOutbox, NotificationPreference
from app.models.vessel import ServiceReminder
from app.services import reminders
from app.tasks import reminders as reminder_tasks
from app.tests.conftest import create_vessel


async def _reminder(vessel_id, **kw):
    async with async_session() as s:
        r = ServiceReminder(vessel_id=vessel_id, title=kw.pop("title", "100-hour service"), **kw)
        s.add(r)
        await s.commit()
        await s.refresh(r)
        return r


async def _run(now):
    async with async_session() as s:
        result = await reminders.notify_due_reminders(s, now=now)
        await s.commit()
        return result


async def _queued():
    async with async_session() as s:
        rows = (
            await s.execute(select(NotificationOutbox).where(NotificationOutbox.template == "service_reminder"))
        ).scalars()
        return [r.payload["title"] for r in rows]


async def test_due_by_date_hours_and_renotify_window(customer):
    vessel = await create_vessel(customer.id, engine_hours=150)
    # 2026-05-31T12:30Z is 2026-06-01 00:30 NZST: a reminder due 2026-06-01 is due "today".
    now = datetime(2026, 5, 31, 12, 30, tzinfo=UTC)
    await _reminder(vessel.id, title="Due today (NZ)", due_on=date(2026, 6, 1))
    await _reminder(vessel.id, title="Due tomorrow", due_on=date(2026, 6, 2))
    await _reminder(vessel.id, title="Hours reached", due_engine_hours=150)
    await _reminder(vessel.id, title="Hours not reached", due_engine_hours=200)
    await _reminder(vessel.id, title="Dismissed", due_on=date(2026, 1, 1), status="dismissed")
    await _reminder(
        vessel.id, title="Recently notified", due_on=date(2026, 1, 1), last_notified_at=now - timedelta(days=3)
    )
    result = await _run(now)
    assert result["due"] == 2 and result["date"] == "2026-06-01"
    assert sorted(await _queued()) == ["Due today (NZ)", "Hours reached"]
    # Six days later: the first two are inside the 7-day window; "Due tomorrow" is now
    # due and "Recently notified" (9 days ago) is due again.
    assert (await _run(now + timedelta(days=6)))["due"] == 2
    assert sorted(await _queued()) == ["Due today (NZ)", "Due tomorrow", "Hours reached", "Recently notified"]
    # Eight days later only the reminders notified 8 days ago are re-sent.
    later = await _run(now + timedelta(days=8))
    assert later["due"] == 2 and later["queued"] == 2
    async with async_session() as s:
        stamped = list(
            (await s.execute(select(ServiceReminder).where(ServiceReminder.title == "Hours reached"))).scalars()
        )
    assert stamped[0].last_notified_at == now + timedelta(days=8)


async def test_reminder_preference_respected(customer):
    vessel = await create_vessel(customer.id)
    async with async_session() as s:
        s.add(NotificationPreference(user_id=customer.id, service_reminders=False))
        await s.commit()
    await _reminder(vessel.id, due_on=date(2020, 1, 1))
    await _run(datetime(2026, 6, 1, tzinfo=UTC))
    async with async_session() as s:
        row = (await s.execute(select(NotificationOutbox))).scalar_one()
    assert row.status == "suppressed" and row.payload["vessel_name"] == "My Stabi"


async def test_celery_task_runs(customer):
    vessel = await create_vessel(customer.id)
    await _reminder(vessel.id, due_on=date(2020, 1, 1))
    result = await asyncio.to_thread(reminder_tasks.notify_due_reminders.run)
    assert result["due"] == 1 and result["queued"] == 1
    again = await asyncio.to_thread(reminder_tasks.notify_due_reminders.run)
    assert again["due"] == 0
