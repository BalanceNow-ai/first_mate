"""Boat OEM database helpers (Helm_Boat_Database_Design_Specification §5)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.boat_db import (
    DATA_SOURCE_CONFIDENCE,
    BoatModel,
    EquipmentCategory,
    Manufacturer,
    ModelYear,
    OEMEquipment,
)

# Equipment categories used by the vessel profile, checklists and fitment rules.
# (slug, name, parent slug)
EQUIPMENT_CATEGORIES: list[tuple[str, str, str | None]] = [
    ("propulsion", "Propulsion", None),
    ("engine", "Engine", "propulsion"),
    ("electronics", "Electronics", None),
    ("chartplotter", "Chartplotter / GPS", "electronics"),
    ("vhf_radio", "VHF Radio", "electronics"),
    ("autopilot", "Autopilot", "electronics"),
    ("fish_finder", "Fish Finder / Sounder", "electronics"),
    ("electrical", "Electrical", None),
    ("battery", "Battery", "electrical"),
    ("inverter", "Inverter / Charger", "electrical"),
    ("solar", "Solar Panel / Controller", "electrical"),
    ("plumbing", "Plumbing", None),
    ("bilge_pump", "Bilge Pump", "plumbing"),
    ("freshwater_pump", "Freshwater Pump", "plumbing"),
    ("toilet", "Marine Toilet", "plumbing"),
    ("deck", "Deck & Anchoring", None),
    ("anchor_winch", "Anchor Winch", "deck"),
    ("steering", "Steering", None),
    ("steering_hydraulic", "Hydraulic Steering", "steering"),
    ("steering_cable", "Cable Steering", "steering"),
    ("galley", "Galley", None),
    ("galley_stove", "Galley Stove", "galley"),
    ("rig", "Rig & Sails", None),
    ("sail_rig", "Sail Rig", "rig"),
]

VERIFICATION_STATUSES = ("unverified", "verified", "rejected")


REFERENCE_SLUGS = frozenset(slug for slug, _, _ in EQUIPMENT_CATEGORIES)


async def ensure_equipment_categories(db: AsyncSession) -> int:
    """Idempotently (and race-safely) insert the reference equipment categories.

    Reference data, not synthetic: called by ``seed-catalogue`` and lazily the first time
    a reference category is needed. Returns the number of rows created.
    """
    existing = set((await db.execute(select(EquipmentCategory.slug))).scalars())
    if REFERENCE_SLUGS <= existing:
        return 0
    created = 0
    for slug, name, parent in EQUIPMENT_CATEGORIES:
        if slug in existing:
            continue
        parent_id = (
            select(EquipmentCategory.id).where(EquipmentCategory.slug == parent).scalar_subquery() if parent else None
        )
        result = await db.execute(
            pg_insert(EquipmentCategory)
            .values(id=uuid.uuid4(), slug=slug, name=name, parent_id=parent_id)
            .on_conflict_do_nothing(index_elements=["slug"])
        )
        created += result.rowcount or 0
    return created


async def category_by_slug(db: AsyncSession, slug: str) -> EquipmentCategory | None:
    slug = slug.strip().lower()
    q = select(EquipmentCategory).where(EquipmentCategory.slug == slug)
    cat = (await db.execute(q)).scalar_one_or_none()
    if cat is None and slug in REFERENCE_SLUGS:
        await ensure_equipment_categories(db)
        cat = (await db.execute(q)).scalar_one_or_none()
    return cat


def _n(col):
    return func.upper(func.regexp_replace(col, r"[\s\-_./]+", "", "g"))


async def match_model_year(db: AsyncSession, make: str, model: str, year: int) -> ModelYear | None:
    """Exact (normalised) make/model/year match against the boat DB; None if not exactly one."""
    from app.services.fitment import norm

    rows = list(
        (
            await db.execute(
                select(ModelYear)
                .join(BoatModel, ModelYear.boat_model_id == BoatModel.id)
                .join(Manufacturer, BoatModel.manufacturer_id == Manufacturer.id)
                .where(
                    _n(Manufacturer.name) == norm(make),
                    _n(BoatModel.name) == norm(model),
                    ModelYear.year == year,
                )
            )
        ).scalars()
    )
    return rows[0] if len(rows) == 1 else None


def default_confidence(data_source: str) -> Decimal:
    return DATA_SOURCE_CONFIDENCE.get(data_source, Decimal("0.3"))


def is_reliable(confidence: Decimal | float, verification_status: str) -> bool:
    """OEM data may be shown as fact only when not rejected and confident enough."""
    threshold = Decimal(str(get_settings().fitment_min_confidence))
    return verification_status != "rejected" and Decimal(str(confidence)) >= threshold


async def load_model_year(db: AsyncSession, model_year_id: uuid.UUID) -> ModelYear | None:
    return (
        await db.execute(
            select(ModelYear)
            .where(ModelYear.id == model_year_id)
            .options(
                selectinload(ModelYear.boat_model).selectinload(BoatModel.manufacturer),
                selectinload(ModelYear.equipment).selectinload(OEMEquipment.category),
            )
        )
    ).scalar_one_or_none()
