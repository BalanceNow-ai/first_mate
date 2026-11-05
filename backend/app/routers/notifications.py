"""Notification preferences, push device registration and recent notifications."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.core.rate_limit import mutation_limit
from app.database import get_db, utcnow
from app.middleware.auth import CurrentUser
from app.models.notifications import NotificationOutbox, NotificationPreference, PushDevice
from app.schemas.notifications import (
    NotificationOut,
    PreferencesOut,
    PreferencesUpdate,
    PushDeviceCreate,
    PushDeviceOut,
)
from app.services import notifications
from app.services.notification_templates import render

router = APIRouter(prefix="/notifications", tags=["Notifications"])
Db = Annotated[AsyncSession, Depends(get_db)]
PREF_FIELDS = (
    "email_enabled",
    "push_enabled",
    "order_updates",
    "delivery_updates",
    "service_reminders",
    "rewards_updates",
    "marketing",
)


@router.get("/preferences", response_model=PreferencesOut)
async def get_preferences(user: CurrentUser, db: Db) -> NotificationPreference:
    return await notifications.preferences(db, user.id)


@router.put("/preferences", response_model=PreferencesOut, dependencies=[Depends(mutation_limit())])
async def update_preferences(body: PreferencesUpdate, user: CurrentUser, db: Db) -> NotificationPreference:
    current = await notifications.preferences(db, user.id)
    values = {f: getattr(current, f) for f in PREF_FIELDS}
    values.update({k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None})
    stmt = insert(NotificationPreference).values(user_id=user.id, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NotificationPreference.user_id], set_={**values, "updated_at": utcnow()}
    )
    await db.execute(stmt)
    return (
        await db.execute(
            select(NotificationPreference)
            .where(NotificationPreference.user_id == user.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


@router.post(
    "/push-devices",
    response_model=PushDeviceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def register_device(body: PushDeviceCreate, user: CurrentUser, db: Db) -> PushDevice:
    """Register (or move to this account) an FCM device token."""
    stmt = insert(PushDevice).values(user_id=user.id, token=body.token, platform=body.platform)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PushDevice.token],
        set_={"user_id": user.id, "platform": body.platform, "last_seen_at": utcnow()},
    )
    await db.execute(stmt)
    return (
        await db.execute(
            select(PushDevice).where(PushDevice.token == body.token).execution_options(populate_existing=True)
        )
    ).scalar_one()


@router.delete("/push-devices/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(token: str, user: CurrentUser, db: Db) -> None:
    result = await db.execute(delete(PushDevice).where(PushDevice.token == token, PushDevice.user_id == user.id))
    if result.rowcount == 0:
        raise not_found("Push device")


@router.get("", response_model=list[NotificationOut])
async def recent_notifications(user: CurrentUser, db: Db, limit: int = Query(50, ge=1, le=200)) -> list[dict]:
    rows = (
        await db.execute(
            select(NotificationOutbox)
            .where(NotificationOutbox.user_id == user.id)
            .order_by(NotificationOutbox.created_at.desc())
            .limit(limit)
        )
    ).scalars()
    out = []
    for row in rows:
        try:
            subject = render(row.template, row.payload or {}).subject
        except KeyError:
            subject = row.template
        out.append(
            {
                "id": row.id,
                "channel": row.channel,
                "category": row.category,
                "template": row.template,
                "subject": subject,
                "status": row.status,
                "created_at": row.created_at,
                "sent_at": row.sent_at,
            }
        )
    return out
