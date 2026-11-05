"""Catalogue commands: ``seed-catalogue [--synthetic]`` and ``sync-search``."""

from __future__ import annotations

from app.config import get_settings
from app.database import async_session


async def _seed(args) -> int:
    from app.seed.catalogue import SeedRefusedError, seed_reference, seed_synthetic

    if args.synthetic and not get_settings().is_local:
        print("Refusing: synthetic catalogue data may only be seeded when APP_ENV is development or test.")
        return 2
    async with async_session() as db:
        try:
            counts = await (seed_synthetic(db) if args.synthetic else seed_reference(db))
        except SeedRefusedError as exc:
            print(f"Refusing: {exc}")
            return 2
        await db.commit()
    kind = "reference + synthetic" if args.synthetic else "reference"
    print(f"Seeded {kind} catalogue data (created): " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


async def _sync(_args) -> int:
    from app.services import search_index

    async with async_session() as db:
        result = await search_index.full_sync(db)
    print(f"Search sync: {result}")
    return 0 if result.get("status") in ("ok", "skipped") else 1


def register(sub) -> None:
    p = sub.add_parser(
        "seed-catalogue",
        help="Seed equipment categories and spec boat brands; --synthetic adds synthetic test data (local only)",
    )
    p.add_argument("--synthetic", action="store_true", help="Also seed SYN- products, fitment and boat-DB fixtures")
    p.set_defaults(handler=_seed)
    s = sub.add_parser("sync-search", help="Run a full Typesense product sync now")
    s.set_defaults(handler=_sync)
