"""Transactional notification outbox.

Domain code calls ``enqueue`` (directly or through the hooks below) inside its own
database transaction, so a notification exists if and only if the business change
committed. ``dispatch_pending`` (Celery: ``app.tasks.notifications.dispatch_pending``)
claims due rows with ``FOR UPDATE SKIP LOCKED`` and delivers them through the configured
providers with exponential backoff; rows become ``dead`` after
``NOTIFICATION_MAX_ATTEMPTS`` or a permanent provider error.

Preferences: order confirmations and refund receipts are transactional and always
queued by email; every other category (order status, delivery, reminder, rewards)
follows the user's category and channel toggles. A row suppressed by preference is
recorded as ``suppressed`` (auditable, never sent).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import utcnow
from app.models.helm_dash import HelmDashDelivery
from app.models.loyalty import CrewInvite, CrewTeam, ExperienceRedemption, PointsTransaction
from app.models.notifications import NotificationOutbox, NotificationPreference, PushDevice
from app.models.order import Order, OrderItem
from app.models.user import User
from app.services import notification_providers as providers
from app.services.notification_templates import render

logger = logging.getLogger(__name__)

CATEGORY_PREFERENCE = {
    "order": "order_updates",
    "delivery": "delivery_updates",
    "reminder": "service_reminders",
    "rewards": "rewards_updates",
}
POINTS_REASONS = {
    "earn": "purchase",
    "monthly_bonus": "crew multiplier bonus",
    "profile_verification_bonus": "vessel profile verified",
}


async def preferences(db: AsyncSession, user_id: uuid.UUID) -> NotificationPreference:
    """The user's preferences (defaults when none are stored; not persisted)."""
    pref = await db.get(NotificationPreference, user_id)
    if pref is None:
        pref = NotificationPreference(
            user_id=user_id,
            email_enabled=True,
            push_enabled=True,
            order_updates=True,
            delivery_updates=True,
            service_reminders=True,
            rewards_updates=True,
            marketing=False,
        )
    return pref


async def enqueue(
    db: AsyncSession,
    *,
    template: str,
    category: str,
    idempotency_key: str,
    payload: dict[str, Any],
    user_id: uuid.UUID | None = None,
    recipient_email: str | None = None,
    transactional: bool = False,
    channels: tuple[str, ...] = ("email", "push"),
) -> list[str]:
    """Queue a notification once per (key, channel). Returns the keys newly inserted."""
    pref: NotificationPreference | None = None
    email = recipient_email
    has_devices = False
    if user_id is not None:
        pref = await preferences(db, user_id)
        if email is None:
            email = (await db.execute(select(User.email).where(User.id == user_id))).scalar_one_or_none()
        has_devices = (
            await db.execute(select(PushDevice.id).where(PushDevice.user_id == user_id).limit(1))
        ).first() is not None
    category_on = pref is None or bool(getattr(pref, CATEGORY_PREFERENCE.get(category, ""), True))
    inserted: list[str] = []
    for channel in channels:
        if channel == "email":
            if not email:
                continue
            allowed = transactional or (category_on and (pref is None or pref.email_enabled))
            recipient = email
        else:
            if user_id is None or not has_devices:
                continue
            allowed = pref is not None and pref.push_enabled and (transactional or category_on)
            recipient = None
        key = f"{idempotency_key}:{channel}"
        stmt = (
            insert(NotificationOutbox)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                channel=channel,
                category=category,
                template=template,
                recipient=recipient,
                payload=payload,
                idempotency_key=key,
                status="pending" if allowed else "suppressed",
                last_error=None if allowed else "suppressed_by_preference",
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=[NotificationOutbox.idempotency_key])
            .returning(NotificationOutbox.id)
        )
        if (await db.execute(stmt)).first() is not None:
            inserted.append(key)
    return inserted


# ----------------------------------------------------------------------- domain hooks
async def order_paid(db: AsyncSession, order: Order) -> None:
    item_count = (
        await db.execute(select(func.coalesce(func.sum(OrderItem.quantity), 0)).where(OrderItem.order_id == order.id))
    ).scalar_one()
    await enqueue(
        db,
        template="order_confirmed",
        category="order",
        idempotency_key=f"order_confirmed:{order.id}",
        user_id=order.user_id,
        transactional=True,
        payload={
            "order_id": str(order.id),
            "order_number": order.order_number,
            "total_cents": order.total_cents,
            "currency": order.currency,
            "item_count": int(item_count),
            "delivery_type": order.delivery_type,
        },
    )


async def order_refunded(db: AsyncSession, order: Order, newly_refunded_cents: int) -> None:
    if newly_refunded_cents <= 0:
        return
    await enqueue(
        db,
        template="order_refunded",
        category="order",
        idempotency_key=f"order_refunded:{order.id}:{order.refunded_cents}",
        user_id=order.user_id,
        transactional=True,
        payload={
            "order_id": str(order.id),
            "order_number": order.order_number,
            "refunded_now_cents": newly_refunded_cents,
            "refunded_total_cents": order.refunded_cents,
            "currency": order.currency,
        },
    )


async def order_status_changed(db: AsyncSession, order: Order, previous: str) -> None:
    if order.status not in ("dispatched", "delivered", "collected") or order.status == previous:
        return
    if order.delivery_type == "helm_dash":
        has_delivery = (
            await db.execute(select(HelmDashDelivery.id).where(HelmDashDelivery.order_id == order.id))
        ).first()
        if has_delivery is not None:
            return  # Helm Dash status notifications already cover this order
    await enqueue(
        db,
        template="order_status_changed",
        category="order",
        idempotency_key=f"order_status:{order.id}:{order.status}",
        user_id=order.user_id,
        payload={
            "order_id": str(order.id),
            "order_number": order.order_number,
            "status": order.status,
            "previous_status": previous,
            "tracking_number": order.tracking_number,
            "courier": order.courier,
        },
    )


async def helm_dash_status(db: AsyncSession, delivery: HelmDashDelivery, order: Order, event_id: uuid.UUID) -> None:
    await enqueue(
        db,
        template="helm_dash_status",
        category="delivery",
        idempotency_key=f"helm_dash:{delivery.id}:{event_id}",
        user_id=order.user_id,
        payload={
            "delivery_id": str(delivery.id),
            "order_id": str(order.id),
            "order_number": order.order_number,
            "status": delivery.status,
            "operator_name": delivery.operator_name,
        },
    )


async def points_earned(db: AsyncSession, user_id: uuid.UUID, tx: PointsTransaction) -> None:
    await enqueue(
        db,
        template="points_earned",
        category="rewards",
        idempotency_key=f"points:{tx.id}",
        user_id=user_id,
        payload={
            "points": tx.points,
            "balance": tx.balance_after,
            "kind": tx.kind,
            "reason": POINTS_REASONS.get(tx.kind, "Crew Rewards"),
        },
    )


async def experience_redemption_updated(db: AsyncSession, redemption: ExperienceRedemption) -> None:
    await enqueue(
        db,
        template="experience_redemption_updated",
        category="rewards",
        idempotency_key=f"experience:{redemption.id}:{redemption.status}",
        user_id=redemption.user_id,
        payload={
            "redemption_id": str(redemption.id),
            "title": redemption.experience_title,
            "status": redemption.status,
            "points_cost": redemption.points_cost,
        },
    )


async def crew_invite(db: AsyncSession, invite: CrewInvite, team: CrewTeam, inviter: User) -> None:
    invitee_id = (
        await db.execute(select(User.id).where(func.lower(User.email) == invite.invited_email))
    ).scalar_one_or_none()
    await enqueue(
        db,
        template="crew_invite",
        category="rewards",
        idempotency_key=f"crew_invite:{invite.id}",
        user_id=invitee_id,
        recipient_email=invite.invited_email,
        payload={
            "invite_id": str(invite.id),
            "crew_name": team.name,
            "inviter_name": inviter.full_name,
            "expires_on": invite.expires_at.date().isoformat(),
        },
    )


async def service_reminder(
    db: AsyncSession, *, reminder_id: uuid.UUID, user_id: uuid.UUID, payload: dict[str, Any], today: date
) -> list[str]:
    return await enqueue(
        db,
        template="service_reminder",
        category="reminder",
        idempotency_key=f"service_reminder:{reminder_id}:{today.isoformat()}",
        user_id=user_id,
        payload=payload,
    )


# ------------------------------------------------------------------------- dispatcher
def backoff_seconds(attempts: int) -> int:
    s = get_settings()
    return min(s.notification_backoff_base_seconds * 2 ** max(0, attempts - 1), s.notification_backoff_max_seconds)


async def _claim(db: AsyncSession, now: datetime, limit: int) -> tuple[list[NotificationOutbox], uuid.UUID]:
    s = get_settings()
    rows = (
        (
            await db.execute(
                select(NotificationOutbox)
                .where(
                    NotificationOutbox.status.in_(("pending", "failed", "sending")),
                    or_(NotificationOutbox.next_attempt_at.is_(None), NotificationOutbox.next_attempt_at <= now),
                )
                .order_by(NotificationOutbox.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    lease = now + timedelta(seconds=s.notification_claim_lease_seconds)
    token = uuid.uuid4()
    for row in rows:
        row.status = "sending"  # a crashed worker's rows are reclaimed when the lease ends
        row.attempts += 1
        row.next_attempt_at = lease
        row.lease_token = token
    await db.commit()
    return list(rows), token


async def _renew_lease(db: AsyncSession, row: NotificationOutbox, token: uuid.UUID) -> bool:
    """Extend this claim's lease just before sending; False when another worker owns the row.

    A batch is sent sequentially, so later rows would otherwise outlive the lease taken at
    claim time and be reclaimed (and sent twice) by another worker."""
    seconds = get_settings().notification_claim_lease_seconds
    renewed = (
        await db.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == row.id,
                NotificationOutbox.lease_token == token,
                NotificationOutbox.status == "sending",
            )
            .values(next_attempt_at=utcnow() + timedelta(seconds=seconds))
            .returning(NotificationOutbox.id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    await db.commit()
    return renewed is not None


async def _still_owned(db: AsyncSession, row: NotificationOutbox, token: uuid.UUID | None) -> bool:
    """Fence the completion write: lock the row and check our claim still owns it."""
    with db.no_autoflush:
        current = (
            await db.execute(
                select(NotificationOutbox.lease_token)
                .where(NotificationOutbox.id == row.id)
                .with_for_update()
                .execution_options(populate_existing=False)
            )
        ).scalar_one_or_none()
    return current == token


async def _record_reached_devices(db: AsyncSession, row_id: uuid.UUID, reached: dict[str, dict]) -> None:
    current = (
        await db.execute(
            select(NotificationOutbox.push_targets).where(NotificationOutbox.id == row_id).with_for_update()
        )
    ).scalar_one_or_none()
    if current is None:
        await db.rollback()
        return
    merged = dict(current)
    for key, outcome in reached.items():
        if merged.get(key, {}).get("status") not in PUSH_FINAL:
            merged[key] = outcome
    await db.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.id == row_id)
        .values(push_targets=merged)
        .execution_options(synchronize_session=False)
    )
    await db.commit()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


PUSH_FINAL = {"sent", "invalid", "failed_permanent"}


async def _deliver(db: AsyncSession, row: NotificationOutbox) -> tuple[str, str | None]:
    rendered = render(row.template, row.payload or {})
    if row.channel == "email":
        if not row.recipient:
            raise providers.Suppressed("no_recipient")
        result = await providers.send_email(
            providers.Email(to=row.recipient, subject=rendered.subject, text=rendered.text, html=rendered.html),
            outbox_id=str(row.id),
            template=row.template,
        )
        return result.provider, result.message_id
    tokens = (
        list((await db.execute(select(PushDevice.token).where(PushDevice.user_id == row.user_id))).scalars())
        if row.user_id
        else []
    )
    # Per-device outcomes persist across attempts (FM-04): a retry targets only devices
    # that have not received the message nor failed permanently.
    targets: dict[str, dict] = dict(row.push_targets or {})
    pending = [t for t in tokens if targets.get(_token_key(t), {}).get("status") not in PUSH_FINAL]
    delivered = [v for v in targets.values() if v.get("status") == "sent"]
    if not pending and delivered:
        return row.provider or get_settings().push_provider, _message_ids(targets)
    data = {"template": row.template, "outbox_id": str(row.id)}
    for k in ("order_id", "delivery_id", "redemption_id"):
        if (row.payload or {}).get(k):
            data[k] = str(row.payload[k])
    push = await providers.send_push(
        pending,
        title=rendered.push_title,
        body=rendered.push_body,
        data=data,
        outbox_id=str(row.id),
        template=row.template,
    )
    for token, message_id in push.sent.items():
        targets[_token_key(token)] = {"status": "sent", "message_id": message_id}
    for token in push.invalid_tokens:
        targets[_token_key(token)] = {"status": "invalid"}
    transient: list[providers.ProviderError] = []
    for token, error in push.failed.items():
        targets[_token_key(token)] = {"status": "failed_permanent" if error.permanent else "retry", "error": error.code}
        if not error.permanent:
            transient.append(error)
    row.push_targets = targets  # a new dict, so the JSONB change is persisted
    row.provider = push.provider
    if push.invalid_tokens:
        await db.execute(delete(PushDevice).where(PushDevice.token.in_(push.invalid_tokens)))
    if transient:
        raise transient[0]  # retried later, for the pending devices only
    if push.provider == "fcm" and not any(v.get("status") == "sent" for v in targets.values()):
        errors = [v["error"] for v in targets.values() if v.get("error")]
        raise providers.ProviderError(errors[0] if errors else "fcm_all_tokens_unregistered", permanent=True)
    return push.provider, _message_ids(targets)


def _message_ids(targets: dict[str, dict]) -> str | None:
    return (
        ",".join(v["message_id"] for v in targets.values() if v.get("status") == "sent" and v.get("message_id"))[:500]
        or None
    )


async def dispatch_pending(db: AsyncSession, *, now: datetime | None = None, limit: int | None = None) -> dict:
    """Deliver due outbox rows. Safe to run concurrently (SKIP LOCKED + leases)."""
    settings = get_settings()
    now = now or utcnow()
    rows, token = await _claim(db, now, limit or settings.notification_batch_size)
    counts = {"claimed": len(rows), "sent": 0, "failed": 0, "dead": 0, "suppressed": 0, "lease_lost": 0}
    for row in rows:
        # The fencing token is this claim's, never re-read from the row (another worker
        # that reclaimed the row has written its own token there).
        if sa_inspect(row).expired:  # after a rollback for a lost lease
            await db.refresh(row)
        if not await _renew_lease(db, row, token):
            counts["lease_lost"] += 1
            continue
        try:
            provider, message_id = await _deliver(db, row)
        except providers.Suppressed as exc:
            row.status, row.last_error = "suppressed", exc.reason
            row.next_attempt_at = None
        except providers.ProviderError as exc:
            row.last_error = exc.code
            if exc.permanent or row.attempts >= settings.notification_max_attempts:
                row.status, row.next_attempt_at = "dead", None
            else:
                row.status = "failed"
                row.next_attempt_at = now + timedelta(seconds=backoff_seconds(row.attempts))
        except Exception as exc:  # noqa: BLE001 - never let one row stop the batch
            logger.error("notification outbox=%s unexpected %s", row.id, type(exc).__name__)
            row.last_error = f"unexpected_{type(exc).__name__}"
            if row.attempts >= settings.notification_max_attempts:
                row.status, row.next_attempt_at = "dead", None
            else:
                row.status = "failed"
                row.next_attempt_at = now + timedelta(seconds=backoff_seconds(row.attempts))
        else:
            row.status, row.provider, row.provider_message_id = "sent", provider, message_id
            row.sent_at, row.last_error, row.next_attempt_at = utcnow(), None, None
        if row.status == "suppressed" and row.provider is None:
            row.provider = settings.email_provider if row.channel == "email" else settings.push_provider
        if not await _still_owned(db, row, token):
            # Our lease ended and another worker reclaimed the row: its claim decides the
            # row's status, but devices we did reach are recorded so no retry repeats them.
            reached = {k: v for k, v in (row.push_targets or {}).items() if v.get("status") in PUSH_FINAL}
            row_id = row.id
            await db.rollback()
            if reached:
                await _record_reached_devices(db, row_id, reached)
            counts["lease_lost"] += 1
            continue
        if row.status != "sending":
            row.lease_token = None
        counts[row.status] = counts.get(row.status, 0) + 1
        await db.commit()
    return counts
