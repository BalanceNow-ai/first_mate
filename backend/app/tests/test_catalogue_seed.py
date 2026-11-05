"""seed-catalogue: idempotent, local-only synthetic data, honest provenance."""

import re

import pytest
from sqlalchemy import func, select

from app.cli.__main__ import main as cli_main
from app.config import get_settings
from app.database import async_session
from app.models.boat_db import EquipmentCategory, Manufacturer, OEMEquipment
from app.models.product import Product, ProductCompatibility
from app.seed.catalogue import SeedRefused, data, seed_synthetic
from app.services.checklists import TEMPLATES
from app.tests.test_catalogue_support import API


async def _counts():
    async with async_session() as s:
        out = {}
        for model in (EquipmentCategory, Manufacturer, OEMEquipment, Product, ProductCompatibility):
            out[model.__tablename__] = (await s.execute(select(func.count()).select_from(model))).scalar_one()
        return out


async def test_synthetic_seed_is_idempotent_and_honest():
    async with async_session() as s:
        first = await seed_synthetic(s)
        await s.commit()
    snapshot = await _counts()
    async with async_session() as s:
        second = await seed_synthetic(s)
        await s.commit()
    assert all(v == 0 for v in second.values()) and await _counts() == snapshot
    assert first["products"] >= 30 and first["fitment_rules"] >= 8

    async with async_session() as s:
        products = list((await s.execute(select(Product))).scalars())
        assert all(p.sku.startswith("SYN-") and "Synthetic test product" in p.description for p in products)
        assert all(n.startswith("SYN-") for p in products for n in p.oem_part_numbers)
        assert any(p.dangerous_goods for p in products) and any(p.stock_quantity == 0 for p in products)
        assert any(p.sale_price_cents for p in products) and any(p.fitment_scope == "universal" for p in products)
        assert all(p.weight_grams and p.price_cents > 0 for p in products)
        roles = {p.part_role for p in products}
        assert {"spark_plug", "fuel_filter", "impeller", "engine_oil", "duct_tape", "zip_ties"} <= roles
        assert len({t.part_role for t in TEMPLATES} & roles) >= 25

        rules = list((await s.execute(select(ProductCompatibility))).scalars())
        assert all(r.data_source == "synthetic_fixture" and r.verification_status == "verified" for r in rules)
        assert all(r.notes == "Synthetic test fixture — not real fitment data" for r in rules)
        engines = {(r.engine_make, r.engine_model) for r in rules}
        assert {("Yamaha", "F150"), ("Suzuki", "DF140")} <= engines

        # Codes cited by the synthetic knowledge corpus exist exactly, with verified fitment.
        by_sku = {p.sku: p for p in products}
        for sku, (role, make, model) in data.KNOWLEDGE_CORPUS_SKUS.items():
            p = by_sku[sku]
            assert p.part_role == role and p.oem_part_numbers == [sku] and p.is_active
            assert any(r.product_id == p.id and (r.engine_make, r.engine_model) == (make, model) for r in rules)
        assert not data.NEVER_SEED_SKUS & set(by_sku)  # Helmsynth HX90 conflict fixture stays unsellable

        makers = list((await s.execute(select(Manufacturer))).scalars())
        real = [m for m in makers if not m.is_synthetic]
        assert {m.name for m in real} >= {"Stabicraft", "Haines Hunter", "Rayglass", "Maritimo"}
        assert all(m.mic_codes == [] for m in real)  # never invented
        synthetic = [m for m in makers if m.is_synthetic]
        assert len(synthetic) == 1 and all(re.search(r"\d", c) for c in synthetic[0].mic_codes)
        oem = list((await s.execute(select(OEMEquipment))).scalars())
        assert oem and all(o.data_source == "synthetic_fixture" for o in oem)


async def test_synthetic_seed_refused_outside_local(monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    async with async_session() as s:
        with pytest.raises(SeedRefused):
            await seed_synthetic(s)
    assert (await _counts())["products"] == 0


def test_cli_seed_reference_and_refusal(monkeypatch, capsys):
    assert cli_main(["seed-catalogue"]) == 0
    assert "reference" in capsys.readouterr().out
    monkeypatch.setattr(get_settings(), "app_env", "staging")
    assert cli_main(["seed-catalogue", "--synthetic"]) == 2
    assert "Refusing" in capsys.readouterr().out


async def test_hin_decodes_synthetic_mic_after_seed(client):
    async with async_session() as s:
        await seed_synthetic(s)
        await s.commit()
    body = (await client.post(f"{API}/boat-db/hin/decode", json={"hin": "Z9X00042C323"})).json()
    assert body["manufacturer"]["is_synthetic"] is True and body["model_year"] == 2023
    makers = (await client.get(f"{API}/boat-db/manufacturers", params={"include_synthetic": "false"})).json()
    assert all(not m["is_synthetic"] for m in makers) and len(makers) == 10
