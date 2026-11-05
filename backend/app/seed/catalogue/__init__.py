"""Idempotent catalogue / boat-database seeding.

``seed_reference`` (safe in any environment): equipment categories plus the boat brands
and model families named in the Boat Database spec's priority table (names only).

``seed_synthetic`` (development/test only): a synthetic manufacturer with model years and
synthetic OEM equipment, ~30 ``SYN-`` products and synthetic verified fitment rules.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import utcnow
from app.models.boat_db import (
    DATA_SOURCE_CONFIDENCE,
    BoatModel,
    EquipmentCategory,
    Manufacturer,
    ModelYear,
    OEMEquipment,
)
from app.models.product import Product, ProductCompatibility
from app.seed.catalogue import data
from app.services.boat_db import ensure_equipment_categories

SYNTHETIC_DESCRIPTION = "Synthetic test product — not a real catalogue item. "


class SeedRefused(RuntimeError):
    pass


async def _manufacturer(db: AsyncSession, name: str, **fields) -> tuple[Manufacturer, bool]:
    m = (await db.execute(select(Manufacturer).where(Manufacturer.name == name))).scalar_one_or_none()
    if m is not None:
        return m, False
    m = Manufacturer(name=name, **fields)
    db.add(m)
    await db.flush()
    return m, True


async def _model(db: AsyncSession, maker: Manufacturer, name: str, **fields) -> tuple[BoatModel, bool]:
    m = (
        await db.execute(select(BoatModel).where(BoatModel.manufacturer_id == maker.id, BoatModel.name == name))
    ).scalar_one_or_none()
    if m is not None:
        return m, False
    m = BoatModel(manufacturer_id=maker.id, name=name, **fields)
    db.add(m)
    await db.flush()
    return m, True


async def seed_reference(db: AsyncSession) -> dict[str, int]:
    counts = {"equipment_categories": await ensure_equipment_categories(db), "manufacturers": 0, "boat_models": 0}
    for brand, country, models in data.SPEC_MANUFACTURERS:
        maker, created = await _manufacturer(db, brand, country=country, mic_codes=[], source=data.SPEC_SOURCE)
        counts["manufacturers"] += created
        for name in models:
            _, created = await _model(db, maker, name, source_url=None)
            counts["boat_models"] += created
    return counts


async def seed_synthetic(db: AsyncSession) -> dict[str, int]:
    if not get_settings().is_local:
        raise SeedRefused("Synthetic catalogue data may only be seeded when APP_ENV is development or test")
    counts = await seed_reference(db)
    counts.update({"model_years": 0, "oem_equipment": 0, "products": 0, "fitment_rules": 0})
    cats = {c.slug: c for c in (await db.execute(select(EquipmentCategory))).scalars()}
    synthetic_conf = DATA_SOURCE_CONFIDENCE["synthetic_fixture"]

    spec = dict(data.SYNTHETIC_MANUFACTURER)
    maker, created = await _manufacturer(db, spec.pop("name"), **spec)
    counts["manufacturers"] += created
    for m in data.SYNTHETIC_MODELS:
        model, created = await _model(
            db, maker, m["name"], hull_type=m["hull_type"], propulsion_type=m["propulsion_type"],
            length_ft=Decimal(str(m["length_ft"])), is_synthetic=True,
        )
        counts["boat_models"] += created
        equipment = list(data.SYNTHETIC_OEM_COMMON)
        if m["engine"]:
            equipment.insert(0, ("engine", m["engine"][0], m["engine"][1]))
        if m["propulsion_type"] == "sail":
            equipment += data.SYNTHETIC_OEM_SAIL
        for year in m["years"]:
            my = (
                await db.execute(select(ModelYear).where(ModelYear.boat_model_id == model.id, ModelYear.year == year))
            ).scalar_one_or_none()
            if my is None:
                my = ModelYear(boat_model_id=model.id, year=year, hin_prefix="Z9X")
                db.add(my)
                await db.flush()
                counts["model_years"] += 1
            for slug, make, model_name in equipment:
                exists = (
                    await db.execute(
                        select(OEMEquipment.id).where(
                            OEMEquipment.model_year_id == my.id, OEMEquipment.category_id == cats[slug].id,
                            OEMEquipment.equipment_make == make, OEMEquipment.equipment_model == model_name,
                        )
                    )
                ).first()
                if exists:
                    continue
                db.add(OEMEquipment(
                    model_year_id=my.id, category_id=cats[slug].id, equipment_make=make,
                    equipment_model=model_name, is_standard=True, data_source="synthetic_fixture",
                    confidence_score=synthetic_conf, verification_status="unverified",
                ))
                counts["oem_equipment"] += 1
    await db.flush()

    now = utcnow()
    for spec in data.SYNTHETIC_PRODUCTS:
        if spec["sku"] in data.NEVER_SEED_SKUS:  # deliberate conflict fixture: never sellable
            continue
        spec = dict(spec)
        fits = spec.pop("fits", [])
        stock = spec.pop("stock")
        product = (await db.execute(select(Product).where(Product.sku == spec["sku"]))).scalar_one_or_none()
        if product is None:
            product = Product(
                **spec, stock_quantity=stock, oem_part_numbers=[spec["sku"]],
                description=SYNTHETIC_DESCRIPTION + spec["name"],
                specifications={"synthetic": True},
            )
            db.add(product)
            await db.flush()
            counts["products"] += 1
        for engine_make, engine_model in fits:
            exists = (
                await db.execute(
                    select(ProductCompatibility.id).where(
                        ProductCompatibility.product_id == product.id,
                        ProductCompatibility.engine_make == engine_make,
                        ProductCompatibility.engine_model == engine_model,
                        ProductCompatibility.data_source == "synthetic_fixture",
                    )
                )
            ).first()
            if exists:
                continue
            db.add(ProductCompatibility(
                product_id=product.id, engine_make=engine_make, engine_model=engine_model,
                fitment_type="service_part", verification_status="verified", confidence_score=Decimal("0.90"),
                data_source="synthetic_fixture", notes=data.FITMENT_NOTES, verified_at=now,
            ))
            counts["fitment_rules"] += 1
    await db.flush()
    return counts
