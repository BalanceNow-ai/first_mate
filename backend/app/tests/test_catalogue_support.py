"""Shared helpers for the catalogue workstream tests (no tests collected here)."""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import select

from app.database import async_session
from app.models.boat_db import BoatModel, EquipmentCategory, Manufacturer, ModelYear, OEMEquipment
from app.models.ops import AuditLog
from app.services.boat_db import ensure_equipment_categories

API = "/api/v1"


@pytest_asyncio.fixture
async def categories() -> dict[str, uuid.UUID]:
    async with async_session() as s:
        await ensure_equipment_categories(s)
        await s.commit()
        return {c.slug: c.id for c in (await s.execute(select(EquipmentCategory))).scalars()}


async def make_boat(
    maker: str = "Stabicraft", model: str = "2050 Supercab", year: int = 2022, *, mic_codes=None,
    is_synthetic: bool = False, oem: list[tuple[str, str, str | None, str, float, str]] | None = None,
) -> dict:
    """Create manufacturer → model → year (+ OEM rows: slug, make, model, data_source, conf, status)."""
    async with async_session() as s:
        await ensure_equipment_categories(s)
        cats = {c.slug: c.id for c in (await s.execute(select(EquipmentCategory))).scalars()}
        m = (await s.execute(select(Manufacturer).where(Manufacturer.name == maker))).scalar_one_or_none()
        if m is None:
            m = Manufacturer(name=maker, mic_codes=mic_codes or [], is_synthetic=is_synthetic)
            s.add(m)
            await s.flush()
        bm = BoatModel(manufacturer_id=m.id, name=model, is_synthetic=is_synthetic)
        s.add(bm)
        await s.flush()
        my = ModelYear(boat_model_id=bm.id, year=year)
        s.add(my)
        await s.flush()
        oem_ids = []
        for slug, make, eq_model, source, conf, status in oem or []:
            o = OEMEquipment(model_year_id=my.id, category_id=cats[slug], equipment_make=make,
                             equipment_model=eq_model, data_source=source, confidence_score=conf,
                             verification_status=status)
            s.add(o)
            await s.flush()
            oem_ids.append(o.id)
        await s.commit()
        return {"manufacturer_id": m.id, "model_id": bm.id, "model_year_id": my.id, "oem_ids": oem_ids}


async def audit_actions(entity_id=None) -> list[str]:
    async with async_session() as s:
        q = select(AuditLog).order_by(AuditLog.created_at)
        if entity_id is not None:
            q = q.where(AuditLog.entity_id == str(entity_id))
        return [a.action for a in (await s.execute(q)).scalars()]
