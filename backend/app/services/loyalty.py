"""Crew Rewards: the points ledger, earning, refunds, multipliers and redemptions.

Every balance change is one ``PointsTransaction`` with a unique ``idempotency_key``
and the resulting ``balance_after``, written under a row lock on the user's
``CrewPoints`` row so concurrent requests serialise and the balance can never go
negative (also enforced by a CHECK constraint).

Business rules (spec "The Crew", Part 1):

* Base earn: 1 CP per whole $1 NZD of *eligible* spend = subtotal - discount
  (shipping excluded) on an authentically paid order. Only paid orders ever earn and
  only earn rows feed multiplier progress and tiers.
* Refunds reverse earned points in proportion to the cumulative refunded share of the
  order total (rounded up, i.e. conservatively). Points already spent are reversed as
  far as the balance allows; the shortfall is recorded, never a negative balance.
* Monthly multiplier on collective crew spend (Pacific/Auckland calendar month):
  each member receives floor(net base points x (multiplier - 1)) as ``monthly_bonus``.
* Tiers (deckhand/mate/skipper/captain) are display-only: no cashback entitlement.
* Discounts: 100 CP = $1, single-use ``DiscountEntitlement``; this module issues and
  voids them. Applying them at checkout belongs to the commerce workflow.
"""

from __future__ import annotations

import math
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.loyalty import (
    CrewPoints,
    CrewTeam,
    CrewTeamMember,
    DiscountEntitlement,
    ExperienceRedemption,
    PointsTransaction,
)
from app.models.order import Order
from app.services import audit

NZ_TZ = ZoneInfo("Pacific/Auckland")
PAID_PAYMENT_STATUSES = ("succeeded", "partially_refunded", "refunded")

# (minimum collective spend in cents, multiplier) — spec table, ascending.
MULTIPLIER_TIERS: tuple[tuple[int, float], ...] = (
    (0, 1.0),
    (50_000, 1.25),
    (100_000, 1.5),
    (200_000, 2.0),
    (500_000, 3.0),
)
# Display-only status tiers from trailing-12-month eligible paid spend (cents).
STATUS_TIERS: tuple[tuple[int, str], ...] = (
    (0, "deckhand"),
    (50_000, "mate"),
    (200_000, "skipper"),
    (500_000, "captain"),
)
EARNING_KINDS = {"earn", "earn_reversal", "monthly_bonus", "profile_verification_bonus"}


# ---------------------------------------------------------------------------- periods
def period_of(moment: datetime) -> str:
    """Pacific/Auckland calendar month ("YYYY-MM") containing ``moment``."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(NZ_TZ).strftime("%Y-%m")


def parse_period(period: str) -> tuple[int, int]:
    try:
        year_s, month_s = period.split("-")
        year, month = int(year_s), int(month_s)
        if len(year_s) != 4 or not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        raise AppError(422, "invalid_period", "Period must be formatted YYYY-MM") from None
    return year, month


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """UTC [start, end) of a Pacific/Auckland calendar month."""
    year, month = parse_period(period)
    start = datetime(year, month, 1, tzinfo=NZ_TZ)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=NZ_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


def current_period(now: datetime | None = None) -> str:
    return period_of(now or utcnow())


def previous_period(now: datetime | None = None) -> str:
    local = (now or utcnow()).astimezone(NZ_TZ)
    first = local.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def multiplier_for(spend_cents: int) -> float:
    result = 1.0
    for threshold, mult in MULTIPLIER_TIERS:
        if spend_cents >= threshold:
            result = mult
    return result


def next_multiplier_threshold(spend_cents: int) -> tuple[int | None, float | None]:
    for threshold, mult in MULTIPLIER_TIERS:
        if spend_cents < threshold:
            return threshold, mult
    return None, None


def tier_for(spend_cents: int) -> str:
    result = STATUS_TIERS[0][1]
    for threshold, name in STATUS_TIERS:
        if spend_cents >= threshold:
            result = name
    return result


def next_tier(spend_cents: int) -> tuple[str | None, int | None]:
    for threshold, name in STATUS_TIERS:
        if spend_cents < threshold:
            return name, threshold
    return None, None


def refund_share_ceil(amount: int, refunded_cents: int, total_cents: int) -> int:
    """ceil(amount x refunded / total), capped at ``amount`` (conservative reversal)."""
    if amount <= 0 or refunded_cents <= 0:
        return 0
    if total_cents <= 0 or refunded_cents >= total_cents:
        return amount
    return min(amount, -(-amount * refunded_cents // total_cents))


# ----------------------------------------------------------------------------- ledger
class InsufficientPointsError(AppError):
    def __init__(self, balance: int, needed: int) -> None:
        super().__init__(
            409,
            "insufficient_points",
            "Not enough Crew Points for this redemption",
            extra={"points_balance": balance, "points_required": needed},
        )


async def lock_account(db: AsyncSession, user_id: uuid.UUID) -> CrewPoints:
    """Return the user's CrewPoints row locked FOR UPDATE, creating it race-safely."""
    await db.execute(
        insert(CrewPoints)
        .values(id=uuid.uuid4(), user_id=user_id, points_balance=0, lifetime_earned=0, tier="deckhand")
        .on_conflict_do_nothing(index_elements=[CrewPoints.user_id])
    )
    return (
        await db.execute(
            select(CrewPoints)
            .where(CrewPoints.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def lock_accounts(db: AsyncSession, user_ids) -> None:
    """Lock several CrewPoints rows in the one global order (D22: ascending str(user_id)).

    Every path that touches more than one account takes all of them through here first,
    so two such paths can never hold one account each while waiting for the other's."""
    for user_id in sorted(set(user_ids), key=str):
        await lock_account(db, user_id)


async def lock_crew_periods(db: AsyncSession, keys) -> None:
    """Transaction-scoped advisory locks on (crew, period), in ascending order (D22).

    Serialises a period's bonus run with refunds that claw that bonus back, so the set of
    bonus recipients a refund reads cannot change before it locks their accounts."""
    for team_id, period in sorted(set(keys), key=lambda k: (str(k[0]), k[1])):
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"crew:{team_id}:{period}", 0))))


async def get_by_key(db: AsyncSession, key: str) -> PointsTransaction | None:
    return (
        await db.execute(select(PointsTransaction).where(PointsTransaction.idempotency_key == key))
    ).scalar_one_or_none()


async def apply(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    points: int,
    idempotency_key: str,
    description: str | None = None,
    team_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    entitlement_id: uuid.UUID | None = None,
    redemption_id: uuid.UUID | None = None,
    period: str | None = None,
    eligible_spend_cents: int | None = None,
) -> tuple[PointsTransaction, bool]:
    """Apply one ledger entry exactly once. Returns (transaction, created).

    Raises ``InsufficientPointsError`` when a debit would make the balance negative."""
    if points == 0:
        raise ValueError("ledger entries must change the balance")
    account = await lock_account(db, user_id)
    # Same key => same user, so the row lock serialises concurrent duplicates.
    existing = await get_by_key(db, idempotency_key)
    if existing is not None:
        return existing, False
    if account.points_balance + points < 0:
        raise InsufficientPointsError(account.points_balance, -points)
    settled = 0
    if points > 0 and account.points_owed > 0:
        # Credits first pay down points owed from earlier refunds of spent points.
        settled = min(account.points_owed, points)
        account.points_owed -= settled
        description = (description + "; " if description else "") + f"{settled} CP applied to points owed"
    account.points_balance += points - settled
    if kind in EARNING_KINDS:
        account.lifetime_earned = max(0, account.lifetime_earned + points)
    tx = PointsTransaction(
        user_id=user_id,
        team_id=team_id,
        kind=kind,
        points=points,
        balance_after=account.points_balance,
        order_id=order_id,
        entitlement_id=entitlement_id,
        redemption_id=redemption_id,
        period=period,
        eligible_spend_cents=eligible_spend_cents,
        idempotency_key=idempotency_key,
        description=description,
    )
    db.add(tx)
    await db.flush()
    return tx, True


async def debit_or_owe(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    points: int,
    idempotency_key: str,
    description: str,
    **fields,
) -> tuple[int, int]:
    """Reverse ``points`` (> 0) in ONE ledger row; the part exceeding the balance becomes
    ``points_owed`` and is paid down by the user's next credits (see ``apply``).

    Ledger invariant: sum(points) == points_balance - points_owed. Idempotent on the key.
    Returns (debited_from_balance, owed_added)."""
    if points <= 0:
        return 0, 0
    account = await lock_account(db, user_id)
    if await get_by_key(db, idempotency_key) is not None:
        return 0, 0
    debited = min(points, account.points_balance)
    owed = points - debited
    if owed:
        description += f"; {owed} CP had already been redeemed and are owed from future credits"
    account.points_balance -= debited
    account.points_owed += owed
    if kind in EARNING_KINDS or kind == "monthly_bonus_reversal":
        account.lifetime_earned = max(0, account.lifetime_earned - points)
    db.add(
        PointsTransaction(
            user_id=user_id,
            kind=kind,
            points=-points,
            balance_after=account.points_balance,
            idempotency_key=idempotency_key,
            description=description,
            **fields,
        )
    )
    if owed:
        await audit.record(
            db, None, "points_owed", "user", user_id, {"idempotency_key": idempotency_key, "owed": owed, "kind": kind}
        )
    await db.flush()
    return debited, owed


async def crew_membership(db: AsyncSession, user_id: uuid.UUID) -> CrewTeamMember | None:
    return (await db.execute(select(CrewTeamMember).where(CrewTeamMember.user_id == user_id))).scalar_one_or_none()


# ---------------------------------------------------------------------------- earning
def eligible_spend_cents(order: Order) -> int:
    return max(0, order.subtotal_cents - order.discount_cents)


def _is_paid(order: Order) -> bool:
    return order.payment_status in ("succeeded", "partially_refunded")


async def award_for_paid_order(db: AsyncSession, order: Order) -> None:
    """Award base points for an authentically paid order (idempotent: ``earn:{id}``)."""
    if not _is_paid(order):
        return
    key = f"earn:{order.id}"
    if await get_by_key(db, key) is not None:
        return
    spend = eligible_spend_cents(order)
    points = spend // 100
    if points <= 0:
        return
    paid_at = order.paid_at or utcnow()
    membership = await crew_membership(db, order.user_id)
    tx, created = await apply(
        db,
        user_id=order.user_id,
        kind="earn",
        points=points,
        idempotency_key=key,
        description=f"Order {order.order_number}",
        team_id=membership.team_id if membership else None,
        order_id=order.id,
        period=period_of(paid_at),
        eligible_spend_cents=spend,
    )
    if created:
        await refresh_tier(db, order.user_id)
        from app.services import notifications

        await notifications.points_earned(db, order.user_id, tx)


async def reverse_for_refund(db: AsyncSession, order: Order, newly_refunded_cents: int) -> None:
    """Refund compensation. Three independent obligations, each idempotent (FM-03):

    1. reverse earned points in proportion to the cumulative refunded share
       (``earn_reversal:{order}:{refunded}``);
    2. recompute the crew bonus for the earn period from the crew's *net* spend, which
       falls with every refund even when no further whole point is reversed;
    3. on a full refund, return the points spent on the order's discount
       (``refund_entitlement:{order}``, D14) — whether or not the order earned points
       and whether or not an earlier partial refund already reversed them."""
    if newly_refunded_cents <= 0 and order.refunded_cents <= 0:
        return
    earn = await get_by_key(db, f"earn:{order.id}")
    # D22: every account this refund may debit (the customer and, for a crew bonus
    # clawback, the crew's bonus recipients) is locked up front in the global order.
    accounts = {order.user_id}
    if earn is not None and earn.team_id and earn.period:
        await lock_crew_periods(db, [(earn.team_id, earn.period)])
        accounts |= set(await _bonus_recipients(db, earn.team_id, earn.period))
    await lock_accounts(db, accounts)
    if earn is not None:
        await _reverse_earned_points(db, order, earn)
        if earn.team_id and earn.period:
            await clawback_period_bonus(db, earn.team_id, earn.period, trigger=f"{order.id}:{order.refunded_cents}")
    if order.refunded_cents >= order.total_cents and order.discount_entitlement_id:
        await _return_entitlement_points(db, order)
    await refresh_tier(db, order.user_id)


async def _reverse_earned_points(db: AsyncSession, order: Order, earn: PointsTransaction) -> None:
    key = f"earn_reversal:{order.id}:{order.refunded_cents}"
    if await get_by_key(db, key) is not None:
        return
    target = refund_share_ceil(earn.points, order.refunded_cents, order.total_cents)
    already = -(
        (
            await db.execute(
                select(func.coalesce(func.sum(PointsTransaction.points), 0)).where(
                    PointsTransaction.order_id == order.id,
                    PointsTransaction.kind == "earn_reversal",
                )
            )
        ).scalar_one()
    )
    delta = target - already
    if delta <= 0:
        return
    spend_target = refund_share_ceil(earn.eligible_spend_cents or 0, order.refunded_cents, order.total_cents)
    await debit_or_owe(
        db,
        user_id=order.user_id,
        kind="earn_reversal",
        points=delta,
        idempotency_key=key,
        description=f"Refund on order {order.order_number}",
        team_id=earn.team_id,
        order_id=order.id,
        period=earn.period,
        eligible_spend_cents=-spend_target,
    )


async def _return_entitlement_points(db: AsyncSession, order: Order) -> None:
    """A fully refunded order returns the points spent on the discount it consumed."""
    ent = await db.get(DiscountEntitlement, order.discount_entitlement_id)
    if ent is None or ent.status != "consumed" or ent.order_id != order.id:
        return
    await apply(
        db,
        user_id=order.user_id,
        kind="redemption_reversal",
        points=ent.points_cost,
        idempotency_key=f"refund_entitlement:{order.id}",
        description=f"Discount {ent.code} returned: order {order.order_number} fully refunded",
        entitlement_id=ent.id,
        order_id=order.id,
    )


async def _bonus_recipients(db: AsyncSession, team_id: uuid.UUID, period: str) -> list[uuid.UUID]:
    return list(
        (
            await db.execute(
                select(PointsTransaction.user_id)
                .where(
                    PointsTransaction.team_id == team_id,
                    PointsTransaction.period == period,
                    PointsTransaction.kind.in_(("monthly_bonus", "monthly_bonus_reversal")),
                )
                .distinct()
            )
        ).scalars()
    )


async def clawback_period_bonus(db: AsyncSession, team_id: uuid.UUID, period: str, *, trigger: str) -> None:
    """After a refund in a period whose crew bonus was already paid, recompute each
    member's bonus from the crew's *net* spend and claw back any excess (never raise it)."""
    paid = (
        await db.execute(
            select(PointsTransaction.user_id, func.sum(PointsTransaction.points))
            .where(
                PointsTransaction.team_id == team_id,
                PointsTransaction.period == period,
                PointsTransaction.kind.in_(("monthly_bonus", "monthly_bonus_reversal")),
            )
            .group_by(PointsTransaction.user_id)
        )
    ).all()
    if not paid:
        return
    await lock_accounts(db, [user_id for user_id, _ in paid])
    paid = sorted(paid, key=lambda r: str(r[0]))
    rows = await _earn_rows(db, PointsTransaction.team_id == team_id, PointsTransaction.period == period)
    multiplier = multiplier_for(sum(r.net_spend for r in rows))
    base_by_user: dict[uuid.UUID, int] = {}
    for r in rows:
        base_by_user[r.user_id] = base_by_user.get(r.user_id, 0) + r.net_points
    for user_id, net_paid in paid:
        effective = int(net_paid or 0)
        desired = max(0, math.floor(base_by_user.get(user_id, 0) * (multiplier - 1)))
        excess = effective - desired
        if excess > 0:
            await debit_or_owe(
                db,
                user_id=user_id,
                kind="monthly_bonus_reversal",
                points=excess,
                idempotency_key=f"bonus_clawback:{team_id}:{user_id}:{period}:{trigger}",
                description=f"Crew multiplier for {period} recalculated after a refund ({multiplier:g}x)",
                team_id=team_id,
                period=period,
            )


async def award_profile_verification_bonus(db: AsyncSession, user_id, request_id) -> None:
    """1,000 CP once per vessel whose crowdsourced profile is approved (Boat DB spec §4.2).

    Keyed on the vessel, so re-submitting the same vessel after edits cannot earn again."""
    from app.models.vessel import EquipmentVerificationRequest

    request = await db.get(EquipmentVerificationRequest, request_id)
    vessel_key = request.vessel_id if request is not None else request_id
    points = get_settings().profile_verification_bonus_points
    tx, created = await apply(
        db,
        user_id=user_id,
        kind="profile_verification_bonus",
        points=points,
        idempotency_key=f"profile_verification_vessel:{vessel_key}",
        description="Vessel profile verified — thank you for contributing",
    )
    if created:
        from app.services import notifications

        await notifications.points_earned(db, user_id, tx)


# ------------------------------------------------------------- spend / tiers / bonus
@dataclass
class _EarnRow:
    user_id: uuid.UUID
    team_id: uuid.UUID | None
    points: int
    spend: int
    refunded_cents: int
    total_cents: int

    @property
    def net_points(self) -> int:
        return self.points - refund_share_ceil(self.points, self.refunded_cents, self.total_cents)

    @property
    def net_spend(self) -> int:
        return self.spend - refund_share_ceil(self.spend, self.refunded_cents, self.total_cents)


async def _earn_rows(db: AsyncSession, *conditions) -> list[_EarnRow]:
    rows = await db.execute(
        select(
            PointsTransaction.user_id,
            PointsTransaction.team_id,
            PointsTransaction.points,
            PointsTransaction.eligible_spend_cents,
            Order.refunded_cents,
            Order.total_cents,
        )
        .join(Order, Order.id == PointsTransaction.order_id)
        .where(
            PointsTransaction.kind == "earn",
            Order.payment_status.in_(PAID_PAYMENT_STATUSES),
            *conditions,
        )
    )
    return [
        _EarnRow(r.user_id, r.team_id, r.points, r.eligible_spend_cents or 0, r.refunded_cents, r.total_cents)
        for r in rows
    ]


async def trailing_spend_cents(db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> int:
    since = (now or utcnow()) - timedelta(days=365)
    rows = await _earn_rows(db, PointsTransaction.user_id == user_id, Order.paid_at >= since)
    return sum(r.net_spend for r in rows)


async def refresh_tier(db: AsyncSession, user_id: uuid.UUID) -> tuple[str, int]:
    spend = await trailing_spend_cents(db, user_id)
    tier = tier_for(spend)
    account = await lock_account(db, user_id)
    if account.tier != tier:
        account.tier = tier
        await db.flush()
    return tier, spend


async def crew_period_spend(db: AsyncSession, team_id: uuid.UUID, period: str) -> int:
    rows = await _earn_rows(db, PointsTransaction.team_id == team_id, PointsTransaction.period == period)
    return sum(r.net_spend for r in rows)


async def member_count(db: AsyncSession, team_id: uuid.UUID) -> int:
    return (await db.execute(select(func.count()).where(CrewTeamMember.team_id == team_id))).scalar_one()


async def calculate_monthly_multipliers(db: AsyncSession, period: str | None = None) -> dict:
    """Award each crew member's monthly bonus for ``period`` (default: previous NZ month).

    Idempotent per (team, user, period). Crews need >= 2 current members."""
    period = period or previous_period()
    parse_period(period)
    settings = get_settings()
    rows = await _earn_rows(db, PointsTransaction.period == period, PointsTransaction.team_id.is_not(None))
    # D22: every crew-period lock, then every account, each in one global order — and the
    # spend is re-read under those locks.
    await lock_crew_periods(db, [(r.team_id, period) for r in rows])
    await lock_accounts(db, [r.user_id for r in rows])
    rows = await _earn_rows(db, PointsTransaction.period == period, PointsTransaction.team_id.is_not(None))
    by_team: dict[uuid.UUID, list[_EarnRow]] = {}
    for row in rows:
        by_team.setdefault(row.team_id, []).append(row)  # type: ignore[arg-type]
    summary = {"period": period, "crews": 0, "bonuses_awarded": 0, "points_awarded": 0}
    for team_id in sorted(by_team, key=str):
        team_rows = by_team[team_id]
        if await member_count(db, team_id) < settings.crew_min_members_for_multiplier:
            continue
        spend = sum(r.net_spend for r in team_rows)
        multiplier = multiplier_for(spend)
        summary["crews"] += 1
        if multiplier <= 1.0:
            continue
        base_by_user: dict[uuid.UUID, int] = {}
        for r in team_rows:
            base_by_user[r.user_id] = base_by_user.get(r.user_id, 0) + r.net_points
        for user_id in sorted(base_by_user, key=str):
            bonus = math.floor(base_by_user[user_id] * (multiplier - 1))
            if bonus <= 0:
                continue
            tx, created = await apply(
                db,
                user_id=user_id,
                kind="monthly_bonus",
                points=bonus,
                idempotency_key=f"bonus:{team_id}:{user_id}:{period}",
                description=f"Crew multiplier {multiplier:g}x for {period}",
                team_id=team_id,
                period=period,
            )
            if created:
                summary["bonuses_awarded"] += 1
                summary["points_awarded"] += bonus
                from app.services import notifications

                await notifications.points_earned(db, user_id, tx)
    return summary


async def multiplier_progress(db: AsyncSession, user_id: uuid.UUID, now: datetime | None = None) -> dict:
    settings = get_settings()
    period = current_period(now)
    membership = await crew_membership(db, user_id)
    if membership is None:
        spend, members, team_id = 0, 0, None
    else:
        team_id = membership.team_id
        spend = await crew_period_spend(db, team_id, period)
        members = await member_count(db, team_id)
    eligible = members >= settings.crew_min_members_for_multiplier
    threshold, next_mult = next_multiplier_threshold(spend)
    return {
        "period": period,
        "crew_id": team_id,
        "member_count": members,
        "eligible_for_multiplier": eligible,
        "min_members": settings.crew_min_members_for_multiplier,
        "crew_spend_cents": spend,
        "currency": "NZD",
        "current_multiplier": multiplier_for(spend) if eligible else 1.0,
        "spend_multiplier": multiplier_for(spend),
        "next_threshold_cents": threshold,
        "next_multiplier": next_mult,
        "remaining_to_next_cents": (threshold - spend) if threshold is not None else None,
        "tiers": [{"min_spend_cents": t, "multiplier": m} for t, m in MULTIPLIER_TIERS],
    }


async def points_summary(db: AsyncSession, user_id: uuid.UUID) -> dict:
    tier, spend = await refresh_tier(db, user_id)
    account = await lock_account(db, user_id)
    nxt, threshold = next_tier(spend)
    membership = await crew_membership(db, user_id)
    wallet = None
    if membership is not None:
        wallet = await crew_wallet_points(db, membership.team_id)
    return {
        "points_balance": account.points_balance,
        "lifetime_earned": account.lifetime_earned,
        "points_owed": account.points_owed,
        "points_per_dollar": get_settings().points_per_dollar_redemption,
        "points_value_cents": account.points_balance * 100 // get_settings().points_per_dollar_redemption,
        "currency": "NZD",
        "tier": tier,
        "tier_is_display_only": True,
        "trailing_12_month_spend_cents": spend,
        "next_tier": nxt,
        "next_tier_threshold_cents": threshold,
        "crew_id": membership.team_id if membership else None,
        "crew_wallet_points": wallet,
    }


async def crew_wallet_points(db: AsyncSession, team_id: uuid.UUID) -> int:
    """Display aggregate of members' balances. Only the owner can spend their points."""
    return (
        await db.execute(
            select(func.coalesce(func.sum(CrewPoints.points_balance), 0))
            .join(CrewTeamMember, CrewTeamMember.user_id == CrewPoints.user_id)
            .where(CrewTeamMember.team_id == team_id)
        )
    ).scalar_one()


# ------------------------------------------------------------------------ discounts
def _new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    body = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"CREW-{body[:4]}-{body[4:8]}-{body[8:]}"


async def redeem_discount(
    db: AsyncSession, user_id: uuid.UUID, points: int, request_key: str | None = None
) -> DiscountEntitlement:
    """Spend ``points`` (multiple of 100) for a single-use discount entitlement."""
    per_dollar = get_settings().points_per_dollar_redemption
    if points < per_dollar or points % per_dollar:
        raise AppError(422, "invalid_points", f"Redeem a positive multiple of {per_dollar} Crew Points")
    account = await lock_account(db, user_id)  # serialises concurrent redemptions
    if request_key:
        prior = await get_by_key(db, f"redeem_discount:{user_id}:{request_key}")
        if prior is not None and prior.entitlement_id is not None:
            return await db.get(DiscountEntitlement, prior.entitlement_id)  # type: ignore[return-value]
    if account.points_balance < points:
        raise InsufficientPointsError(account.points_balance, points)
    entitlement = DiscountEntitlement(
        user_id=user_id,
        code=_new_code(),
        amount_cents=points * 100 // per_dollar,
        points_cost=points,
        status="issued",
    )
    db.add(entitlement)
    await db.flush()
    await apply(
        db,
        user_id=user_id,
        kind="redeem_discount",
        points=-points,
        idempotency_key=(
            f"redeem_discount:{user_id}:{request_key}" if request_key else f"redeem_discount:{entitlement.id}"
        ),
        description=f"Discount {entitlement.code}",
        entitlement_id=entitlement.id,
    )
    await db.refresh(entitlement)
    return entitlement


async def void_entitlement(db: AsyncSession, user_id: uuid.UUID, entitlement_id: uuid.UUID) -> DiscountEntitlement:
    """Void an unused (issued) entitlement and restore its points.

    D22 lock order: the entitlement before the points account — the same order as
    payment success (order → entitlement → account), so the two cannot deadlock."""
    ent = (
        await db.execute(
            select(DiscountEntitlement)
            .where(DiscountEntitlement.id == entitlement_id, DiscountEntitlement.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if ent is None:
        raise not_found("Entitlement")
    await lock_account(db, user_id)
    if ent.status != "issued":
        raise AppError(409, "entitlement_not_voidable", f"A {ent.status} entitlement cannot be voided")
    ent.status = "voided"
    ent.voided_at = utcnow()
    await apply(
        db,
        user_id=user_id,
        kind="redemption_reversal",
        points=ent.points_cost,
        idempotency_key=f"void_entitlement:{ent.id}",
        description=f"Discount {ent.code} voided",
        entitlement_id=ent.id,
    )
    await db.refresh(ent)
    return ent


# ---------------------------------------------------------------------- experiences
async def redeem_experience(
    db: AsyncSession, user_id: uuid.UUID, experience_id: str, note: str | None, request_key: str | None = None
) -> ExperienceRedemption:
    """Validate against a fresh catalogue fetch, debit points, create the record.

    With ``request_key`` the operation is idempotent per user: a repeat returns the
    redemption created by the first request without debiting again."""
    from app.services import cms

    ledger_key = None
    if request_key:
        ledger_key = f"redeem_experience:{user_id}:{request_key}"
        await lock_account(db, user_id)
        prior = await get_by_key(db, ledger_key)
        if prior is not None and prior.redemption_id is not None:
            existing = await db.get(ExperienceRedemption, prior.redemption_id)
            if existing is not None:
                return existing

    catalogue = await cms.fetch_experiences(fresh=True)
    if not catalogue.available:
        raise AppError(
            503,
            "catalogue_unavailable",
            "The Signature Experiences catalogue is unavailable right now",
            extra={"reason": catalogue.reason},
        )
    item = next((i for i in catalogue.items if i["id"] == experience_id), None)
    if item is None:
        raise not_found("Experience")
    if not item.get("available", True):
        raise AppError(409, "experience_unavailable", "This experience is not currently available")
    cost = int(item["points_cost"])
    if cost <= 0:
        raise AppError(409, "experience_unavailable", "This experience has no valid points cost")
    account = await lock_account(db, user_id)
    if account.points_balance < cost:
        raise InsufficientPointsError(account.points_balance, cost)
    redemption = ExperienceRedemption(
        user_id=user_id,
        experience_id=experience_id,
        experience_title=item["title"],
        points_cost=cost,
        cms_provider=catalogue.provider,
        is_synthetic=bool(item.get("is_synthetic")),
        status="requested",
        customer_note=note,
    )
    db.add(redemption)
    await db.flush()
    await apply(
        db,
        user_id=user_id,
        kind="redeem_experience",
        points=-cost,
        idempotency_key=ledger_key or f"redeem_experience:{redemption.id}",
        description=f"Experience: {item['title']}",
        redemption_id=redemption.id,
    )
    from app.services import notifications

    await notifications.experience_redemption_updated(db, redemption)
    await db.refresh(redemption)
    return redemption


EXPERIENCE_TRANSITIONS = {
    "confirm": ({"requested"}, "confirmed"),
    "fulfil": ({"confirmed"}, "fulfilled"),
    "cancel": ({"requested", "confirmed"}, "cancelled"),
}


async def update_experience_redemption(
    db: AsyncSession, redemption_id: uuid.UUID, action: str, staff: uuid.UUID, staff_note: str | None
) -> ExperienceRedemption:
    allowed_from, target = EXPERIENCE_TRANSITIONS[action]
    redemption = (
        await db.execute(select(ExperienceRedemption).where(ExperienceRedemption.id == redemption_id).with_for_update())
    ).scalar_one_or_none()
    if redemption is None:
        raise not_found("Redemption")
    if redemption.status not in allowed_from:
        raise AppError(409, "invalid_transition", f"Cannot {action} a {redemption.status} redemption")
    previous = redemption.status
    redemption.status = target
    redemption.handled_by = staff
    if staff_note:
        redemption.staff_note = staff_note
    if target == "fulfilled":
        redemption.fulfilled_at = utcnow()
    if target == "cancelled":
        await apply(
            db,
            user_id=redemption.user_id,
            kind="redemption_reversal",
            points=redemption.points_cost,
            idempotency_key=f"experience_cancel:{redemption.id}",
            description=f"Experience cancelled: {redemption.experience_title}",
            redemption_id=redemption.id,
        )
    await audit.record(
        db,
        staff,
        f"experience_{action}",
        "experience_redemption",
        redemption.id,
        {"from": previous, "to": target},
    )
    from app.services import notifications

    await notifications.experience_redemption_updated(db, redemption)
    await db.flush()
    await db.refresh(redemption)
    return redemption


async def team_name(db: AsyncSession, team_id: uuid.UUID) -> str | None:
    team = await db.get(CrewTeam, team_id)
    return team.name if team else None
