"""User administration commands (bootstrap the first admin)."""

from __future__ import annotations

from sqlalchemy import func, select

from app.database import async_session
from app.models.user import ROLES, User
from app.services import audit


async def _grant(args) -> int:
    async with async_session() as db:
        user = (await db.execute(select(User).where(func.lower(User.email) == args.email.lower()))).scalar_one_or_none()
        if user is None:
            print(f"No provisioned user with email {args.email}. They must sign up first.")
            return 1
        previous, user.role = user.role, args.role
        await audit.record(db, None, "set_role_cli", "user", user.id, {"from": previous, "to": args.role})
        await db.commit()
        print(f"{user.email}: {previous} -> {args.role}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("grant-role", help="Set a provisioned user's role (audited)")
    p.add_argument("email")
    p.add_argument("role", choices=ROLES)
    p.set_defaults(handler=_grant)
