"""Contractor organization provisioning (audited; local demos and operator bootstrap).

python -m app.cli create-contractor-org "Harbour Marine Services" [--trading-name T] [--nzbn N]
python -m app.cli add-contractor-member ORG_ID EMAIL --role admin|member
python -m app.cli remove-contractor-member ORG_ID EMAIL
python -m app.cli list-contractor-orgs
"""

from __future__ import annotations

import uuid

from app.core.errors import AppError
from app.database import async_session
from app.services.service_jobs import organizations


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        print(f"Not an organization id: {value}")
        return None


async def _create(args) -> int:
    async with async_session() as db:
        org = await organizations.create_org(db, None, name=args.name, trading_name=args.trading_name, nzbn=args.nzbn)
        await db.commit()
        print(f"{org.id}\t{org.name}")
    return 0


async def _add(args) -> int:
    org_id = _uuid(args.org_id)
    if org_id is None:
        return 1
    async with async_session() as db:
        user = await organizations.user_by_email(db, args.email)
        if user is None:
            print(f"No provisioned user with email {args.email}. They must sign up first.")
            return 1
        try:
            m = await organizations.add_member(db, None, org_id, user, args.role)
        except AppError as e:
            print(e.message)
            return 1
        await db.commit()
        print(f"{user.email}: {m.role} of {org_id}")
    return 0


async def _remove(args) -> int:
    org_id = _uuid(args.org_id)
    if org_id is None:
        return 1
    async with async_session() as db:
        user = await organizations.user_by_email(db, args.email)
        if user is None:
            print(f"No provisioned user with email {args.email}.")
            return 1
        try:
            await organizations.remove_member(db, None, org_id, user.id)
        except AppError as e:
            print(e.message)
            return 1
        await db.commit()
        print(f"{user.email}: removed from {org_id}")
    return 0


async def _list(args) -> int:
    async with async_session() as db:
        for org in await organizations.list_orgs(db, q=None, limit=500, offset=0, active_only=False):
            print(f"{org.id}\t{org.status}\t{org.name}")
    return 0


def register(sub) -> None:
    p = sub.add_parser("create-contractor-org", help="Provision a contractor organization (audited)")
    p.add_argument("name")
    p.add_argument("--trading-name", default=None)
    p.add_argument("--nzbn", default=None)
    p.set_defaults(handler=_create)

    p = sub.add_parser("add-contractor-member", help="Add/verify a member of a contractor organization (audited)")
    p.add_argument("org_id")
    p.add_argument("email")
    p.add_argument("--role", choices=("admin", "member"), default="member")
    p.set_defaults(handler=_add)

    p = sub.add_parser("remove-contractor-member", help="Remove a member from a contractor organization (audited)")
    p.add_argument("org_id")
    p.add_argument("email")
    p.set_defaults(handler=_remove)

    p = sub.add_parser("list-contractor-orgs", help="List contractor organizations")
    p.set_defaults(handler=_list)
