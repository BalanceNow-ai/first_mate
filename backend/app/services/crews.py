"""Crews: creation, invites, membership and captaincy.

Rules:
* A user belongs to at most one crew (unique ``crew_team_members.user_id``); joining
  is checked under row locks and the unique constraint is the final arbiter.
* Only the captain invites and removes members. A crew holds at most
  ``crew_max_members`` people *including* pending, unexpired invites.
* Invites expire after ``crew_invite_days``; the invitee must sign in with the invited
  (verified) email address to see, accept or decline an invite.
* A captain who leaves hands captaincy to the earliest-joined remaining member (ties
  broken by user id); a crew left empty is disbanded.
* The Crew Wallet is a display aggregate. Nobody can spend another member's points.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.loyalty import CrewInvite, CrewPoints, CrewTeam, CrewTeamMember
from app.models.user import User
from app.services import audit


def _norm(email: str) -> str:
    return email.strip().lower()


async def membership(db: AsyncSession, user_id: uuid.UUID) -> CrewTeamMember | None:
    return (await db.execute(select(CrewTeamMember).where(CrewTeamMember.user_id == user_id))).scalar_one_or_none()


async def _lock_team(db: AsyncSession, team_id: uuid.UUID) -> CrewTeam:
    team = (await db.execute(select(CrewTeam).where(CrewTeam.id == team_id).with_for_update())).scalar_one_or_none()
    if team is None:
        raise not_found("Crew")
    return team


async def _require_captain(db: AsyncSession, user_id: uuid.UUID) -> CrewTeamMember:
    m = await membership(db, user_id)
    if m is None:
        raise AppError(404, "not_in_crew", "You are not in a crew")
    if m.role != "captain":
        raise AppError(403, "captain_only", "Only the crew captain can do that")
    return m


async def _expire_stale(db: AsyncSession, team_id: uuid.UUID | None = None, email: str | None = None) -> None:
    q = update(CrewInvite).where(CrewInvite.status == "pending", CrewInvite.expires_at <= utcnow())
    if team_id is not None:
        q = q.where(CrewInvite.team_id == team_id)
    if email is not None:
        q = q.where(CrewInvite.invited_email == email)
    await db.execute(q.values(status="expired"))


async def _count_members(db: AsyncSession, team_id: uuid.UUID) -> int:
    return (await db.execute(select(func.count()).where(CrewTeamMember.team_id == team_id))).scalar_one()


async def _count_pending(db: AsyncSession, team_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).where(
                CrewInvite.team_id == team_id,
                CrewInvite.status == "pending",
                CrewInvite.expires_at > utcnow(),
            )
        )
    ).scalar_one()


async def _join(db: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, role: str) -> None:
    try:
        async with db.begin_nested():
            db.add(CrewTeamMember(team_id=team_id, user_id=user_id, role=role, joined_at=utcnow()))
            await db.flush()
    except IntegrityError:
        raise AppError(409, "already_in_crew", "You are already in a crew") from None


async def create_crew(db: AsyncSession, user: User, name: str) -> CrewTeam:
    # Lock the user row so concurrent create/accept for the same user serialise.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    if await membership(db, user.id) is not None:
        raise AppError(409, "already_in_crew", "You are already in a crew")
    team = CrewTeam(name=name, created_by=user.id)
    db.add(team)
    await db.flush()
    await _join(db, team.id, user.id, "captain")
    await audit.record(db, user.id, "crew_create", "crew", team.id, None)
    return team


async def invite(db: AsyncSession, captain: User, email: str) -> CrewInvite:
    settings = get_settings()
    m = await _require_captain(db, captain.id)
    team = await _lock_team(db, m.team_id)
    email = _norm(email)
    if email == _norm(captain.email):
        raise AppError(409, "cannot_invite_self", "You are already in this crew")
    await _expire_stale(db, team_id=team.id)
    existing_member = (
        await db.execute(
            select(User.id)
            .join(CrewTeamMember, CrewTeamMember.user_id == User.id)
            .where(func.lower(User.email) == email, CrewTeamMember.team_id == team.id)
        )
    ).first()
    if existing_member is not None:
        raise AppError(409, "already_member", "That person is already in your crew")
    duplicate = (
        await db.execute(
            select(CrewInvite.id).where(
                CrewInvite.team_id == team.id, CrewInvite.invited_email == email, CrewInvite.status == "pending"
            )
        )
    ).first()
    if duplicate is not None:
        raise AppError(409, "invite_pending", "That email already has a pending invite")
    sent_today = (
        await db.execute(
            select(func.count())
            .select_from(CrewInvite)
            .where(CrewInvite.team_id == team.id, CrewInvite.created_at >= utcnow() - timedelta(days=1))
        )
    ).scalar_one()
    if sent_today >= settings.crew_invites_per_day:
        # Bounds invite emails even when invites are revoked and re-sent.
        raise AppError(429, "invite_limit", "Daily invite limit reached for this crew; try again tomorrow")
    if await _count_members(db, team.id) + await _count_pending(db, team.id) >= settings.crew_max_members:
        raise AppError(
            409, "crew_full", f"A crew can have at most {settings.crew_max_members} members (including pending invites)"
        )
    inv = CrewInvite(
        team_id=team.id,
        invited_email=email,
        invited_by=captain.id,
        status="pending",
        expires_at=utcnow() + timedelta(days=settings.crew_invite_days),
    )
    db.add(inv)
    await db.flush()
    await audit.record(db, captain.id, "crew_invite", "crew", team.id, {"invite_id": str(inv.id)})
    from app.services import notifications

    await notifications.crew_invite(db, inv, team, captain)
    return inv


def _verified_email(user: User, principal_email: str | None) -> str:
    if not principal_email or _norm(principal_email) != _norm(user.email):
        raise AppError(403, "email_mismatch", "Sign in with the invited, verified email address to respond to invites")
    return _norm(principal_email)


async def my_invites(db: AsyncSession, user: User, principal_email: str | None) -> list[CrewInvite]:
    email = _verified_email(user, principal_email)
    await _expire_stale(db, email=email)
    rows = await db.execute(
        select(CrewInvite)
        .where(CrewInvite.invited_email == email, CrewInvite.status == "pending")
        .order_by(CrewInvite.created_at)
    )
    return list(rows.scalars())


async def _lock_invite_for(db: AsyncSession, invite_id: uuid.UUID, email: str) -> CrewInvite:
    inv = (
        await db.execute(select(CrewInvite).where(CrewInvite.id == invite_id).with_for_update())
    ).scalar_one_or_none()
    # Invites addressed to someone else are indistinguishable from missing ones.
    if inv is None or inv.invited_email != email:
        raise not_found("Invite")
    if inv.status == "pending" and inv.expires_at <= utcnow():
        inv.status = "expired"
        await db.flush()
    if inv.status != "pending":
        raise AppError(409, "invite_not_pending", f"This invite is {inv.status}")
    return inv


async def accept(db: AsyncSession, user: User, principal_email: str | None, invite_id: uuid.UUID) -> CrewTeam:
    settings = get_settings()
    email = _verified_email(user, principal_email)
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    inv = await _lock_invite_for(db, invite_id, email)
    team = await _lock_team(db, inv.team_id)
    if await membership(db, user.id) is not None:
        raise AppError(409, "already_in_crew", "Leave your current crew before joining another")
    if await _count_members(db, team.id) >= settings.crew_max_members:
        raise AppError(409, "crew_full", "This crew is full")
    await _join(db, team.id, user.id, "member")
    inv.status = "accepted"
    inv.responded_at = utcnow()
    await audit.record(db, user.id, "crew_join", "crew", team.id, {"invite_id": str(inv.id)})
    await db.flush()
    return team


async def decline(db: AsyncSession, user: User, principal_email: str | None, invite_id: uuid.UUID) -> CrewInvite:
    email = _verified_email(user, principal_email)
    inv = await _lock_invite_for(db, invite_id, email)
    inv.status = "declined"
    inv.responded_at = utcnow()
    await db.flush()
    return inv


async def revoke_invite(db: AsyncSession, captain: User, invite_id: uuid.UUID) -> CrewInvite:
    m = await _require_captain(db, captain.id)
    inv = (
        await db.execute(
            select(CrewInvite).where(CrewInvite.id == invite_id, CrewInvite.team_id == m.team_id).with_for_update()
        )
    ).scalar_one_or_none()
    if inv is None:
        raise not_found("Invite")
    if inv.status != "pending":
        raise AppError(409, "invite_not_pending", f"This invite is {inv.status}")
    inv.status = "revoked"
    inv.responded_at = utcnow()
    await db.flush()
    return inv


async def team_invites(db: AsyncSession, captain: User) -> list[CrewInvite]:
    m = await _require_captain(db, captain.id)
    await _expire_stale(db, team_id=m.team_id)
    rows = await db.execute(
        select(CrewInvite)
        .where(CrewInvite.team_id == m.team_id, CrewInvite.status == "pending")
        .order_by(CrewInvite.created_at)
    )
    return list(rows.scalars())


async def remove_member(db: AsyncSession, captain: User, member_id: uuid.UUID) -> None:
    m = await _require_captain(db, captain.id)
    if member_id == captain.id:
        raise AppError(409, "use_leave", "Captains leave the crew with the leave action")
    await _lock_team(db, m.team_id)
    result = await db.execute(
        delete(CrewTeamMember).where(CrewTeamMember.team_id == m.team_id, CrewTeamMember.user_id == member_id)
    )
    if result.rowcount == 0:
        raise not_found("Crew member")
    await audit.record(db, captain.id, "crew_remove_member", "crew", m.team_id, {"user_id": str(member_id)})


async def leave(db: AsyncSession, user: User) -> dict:
    m = await membership(db, user.id)
    if m is None:
        raise AppError(404, "not_in_crew", "You are not in a crew")
    team = await _lock_team(db, m.team_id)
    was_captain = m.role == "captain"
    await db.execute(delete(CrewTeamMember).where(CrewTeamMember.team_id == team.id, CrewTeamMember.user_id == user.id))
    result: dict = {"left_crew_id": team.id, "disbanded": False, "new_captain_id": None}
    if was_captain:
        successor = (
            await db.execute(
                select(CrewTeamMember)
                .where(CrewTeamMember.team_id == team.id)
                .order_by(CrewTeamMember.joined_at, CrewTeamMember.user_id)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if successor is None:
            # DB cascades remove invites; ledger rows keep their history (team_id -> NULL).
            await db.execute(delete(CrewTeam).where(CrewTeam.id == team.id))
            result["disbanded"] = True
        else:
            successor.role = "captain"
            result["new_captain_id"] = successor.user_id
    await audit.record(db, user.id, "crew_leave", "crew", team.id, {k: str(v) for k, v in result.items()})
    await db.flush()
    return result


async def crew_view(db: AsyncSession, user: User) -> dict:
    m = await membership(db, user.id)
    if m is None:
        raise AppError(404, "not_in_crew", "You are not in a crew")
    team = await db.get(CrewTeam, m.team_id)
    rows = await db.execute(
        select(CrewTeamMember, User.full_name, func.coalesce(CrewPoints.points_balance, 0))
        .join(User, User.id == CrewTeamMember.user_id)
        .outerjoin(CrewPoints, CrewPoints.user_id == CrewTeamMember.user_id)
        .where(CrewTeamMember.team_id == m.team_id)
        .order_by(CrewTeamMember.joined_at, CrewTeamMember.user_id)
    )
    members = [
        {
            "user_id": member.user_id,
            "display_name": full_name or "Crew member",
            "role": member.role,
            "joined_at": member.joined_at,
            "points_balance": balance,
            "is_you": member.user_id == user.id,
        }
        for member, full_name, balance in rows
    ]
    settings = get_settings()
    return {
        "id": team.id,
        "name": team.name,
        "my_role": m.role,
        "members": members,
        "member_count": len(members),
        "pending_invite_count": await _count_pending(db, team.id),
        "max_members": settings.crew_max_members,
        "wallet_points": sum(x["points_balance"] for x in members),
        "wallet_note": "The Crew Wallet shows members' combined balances; each member redeems only their own points.",
        "created_at": team.created_at,
    }
