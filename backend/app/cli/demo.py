"""``seed-demo``: one-shot synthetic local acceptance data (development/test only).

Runs the catalogue and knowledge synthetic seeds and enables a Hauraki Gulf Helm Dash
operating area. Everything created is synthetic and labelled as such; production refuses.
"""

from __future__ import annotations

import argparse

from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.database import async_session
from app.models.helm_dash import OperatingArea

DEMO_AREA = {
    "id": "hauraki-gulf",
    "name": "Hauraki Gulf (local demo area)",
    "center_lat": -36.75,
    "center_lng": 175.0,
    "radius_nm": 25.0,
    "enabled": True,
}


async def seed_demo_area() -> bool:
    async with async_session() as db:
        result = await db.execute(insert(OperatingArea).values(**DEMO_AREA).on_conflict_do_nothing())
        await db.commit()
        return bool(result.rowcount)


async def _run(_args) -> int:
    from app.cli import catalogue, knowledge

    if not get_settings().is_local:
        print("Refusing: seed-demo creates synthetic data and is only allowed in development/test.")
        return 2
    rc = await catalogue._seed(argparse.Namespace(synthetic=True))
    if rc:
        return rc
    rc = await knowledge.run(
        argparse.Namespace(
            path=None,
            synthetic=True,
            admit=True,
            title=None,
            publisher=None,
            licence=None,
            domain=None,
            url=None,
            version=None,
            licence_verified=False,
            applies_to_json=None,
        )
    )
    if rc:
        return rc
    created = await seed_demo_area()
    print(f"Helm Dash demo area: {'created' if created else 'already present'} ({DEMO_AREA['id']})")
    return 0


def register(sub) -> None:
    p = sub.add_parser("seed-demo", help="Seed all synthetic local acceptance data (local only)")
    p.set_defaults(handler=_run)
