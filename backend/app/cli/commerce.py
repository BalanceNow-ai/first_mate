"""Commerce commands: release expired stock reservations on demand."""

from __future__ import annotations

from app.database import async_session
from app.services.reservations import release_expired


async def _release(args) -> int:  # noqa: ARG001
    async with async_session() as db:
        released = await release_expired(db)
        await db.commit()
    print(f"released {released}")
    return 0


def register(sub) -> None:
    p = sub.add_parser(
        "release-expired-reservations",
        help="Release stock held by expired unpaid orders (same as the Celery task)",
    )
    p.set_defaults(handler=_release)
