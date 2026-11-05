"""FM-02: a fitment rule may not silently drop a declared restriction.

Contract (app.core.fitment_rules): vessel model/years need a vessel make, engine
model/years need an engine make, equipment make/model need a category, ranges are
ordered, blank strings are absent. Enforced by the request schema, verification, the
database (migration 0004) and — fail closed, for legacy rows — the evaluator.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.cli.catalogue import _fitment_audit
from app.database import async_session, engine
from app.models.product import FITMENT_SCOPE_CHECKS, Product, ProductCompatibility
from app.services import fitment
from app.services.ai.tools import TurnRuntime
from app.services.fitment import EquipmentFact, VesselProfile, evaluate
from app.tests.conftest import add_fitment_rule, create_product, create_vessel

API = "/api/v1"
REVIEW_RULE = {"engine_make": "Yamaha", "engine_model": "F150", "vessel_model": "2250", "year_to": 2000}


def test_review_probe_is_unknown_not_verified_fit():
    """The review's exact rule against a 2022 Rayglass 2500 with a Yamaha F150."""
    profile = VesselProfile(
        uuid.uuid4(),
        "Boat",
        "Rayglass",
        "2500",
        2022,
        [EquipmentFact("engine", "Yamaha", "F150", 2022, Decimal("1"), "vessel_record")],
    )
    rule = ProductCompatibility(
        id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        verification_status="verified",
        confidence_score=Decimal("1"),
        **REVIEW_RULE,
    )
    product = Product(id=rule.product_id, name="Example", sku="EXAMPLE", fitment_scope="specific")
    result = evaluate(product, [rule], profile)
    assert result.status == "unknown"
    assert result.reasons == [fitment.INCOMPLETE_RULE_REASON]


@pytest.mark.parametrize(
    "body",
    [
        REVIEW_RULE,
        {"engine_make": "Yamaha", "year_from": 2010},
        {"vessel_make": "Stabicraft", "engine_model": "F150"},
        {"vessel_make": "Stabicraft", "engine_year_to": 2020},
        {"vessel_make": "Stabicraft", "equipment_make": "Lewmar"},
        {"engine_make": "Yamaha", "equipment_model": "V700"},
        {"vessel_make": "  ", "vessel_model": "2050"},
        {"engine_make": "", "engine_model": ""},
        {"vessel_make": "Stabicraft", "year_from": 2024, "year_to": 2020},
        {"engine_make": "Yamaha", "engine_year_from": 1066},
    ],
)
async def test_malformed_rules_are_rejected_at_create(client, admin, body):
    p = await create_product(fitment_scope="specific")
    r = await client.post(f"{API}/products/{p.id}/fitment-rules", json=body, headers=admin.headers)
    assert r.status_code == 422, r.text


async def test_well_formed_rules_still_accepted_and_blanks_normalised(client, admin):
    p = await create_product(fitment_scope="specific")
    body = {"engine_make": "Yamaha", "engine_model": " ", "vessel_model": ""}
    r = await client.post(f"{API}/products/{p.id}/fitment-rules", json=body, headers=admin.headers)
    assert r.status_code == 201, r.text
    assert r.json()["engine_model"] is None and r.json()["vessel_model"] is None


@pytest.mark.parametrize("name", sorted(FITMENT_SCOPE_CHECKS))
async def test_database_rejects_malformed_rows(name):
    p = await create_product(fitment_scope="specific")
    bad = {
        "nonblank_scope": {"engine_make": " "},
        "vessel_dependents": REVIEW_RULE,
        "engine_dependents": {"vessel_make": "Stabicraft", "engine_year_from": 2010},
        "equipment_dependents": {"engine_make": "Yamaha", "equipment_make": "Lewmar"},
        "vessel_year_order": {"vessel_make": "Stabicraft", "year_from": 2024, "year_to": 2020},
        "engine_year_order": {"engine_make": "Yamaha", "engine_year_from": 2024, "engine_year_to": 2020},
    }[name]
    with pytest.raises(IntegrityError, match=f"ck_product_compatibility_{name}"):
        async with async_session() as s:
            s.add(ProductCompatibility(product_id=p.id, verification_status="verified", **bad))
            await s.commit()


async def _legacy_malformed_rule(product_id) -> uuid.UUID:
    """Insert a row as an older release could have, bypassing the 0004 constraint."""
    rule_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE product_compatibility DROP CONSTRAINT ck_product_compatibility_vessel_dependents")
        )
        await conn.execute(
            text(
                "INSERT INTO product_compatibility (id, product_id, engine_make, engine_model, vessel_model, "
                "year_to, verification_status, confidence_score, fitment_type) VALUES "
                "(:id, :pid, 'Yamaha', 'F150', '2250', 2000, 'verified', 1.0, 'service_part')"
            ),
            {"id": rule_id, "pid": product_id},
        )
        await conn.execute(
            text(
                "ALTER TABLE product_compatibility ADD CONSTRAINT ck_product_compatibility_vessel_dependents "
                f"CHECK ({FITMENT_SCOPE_CHECKS['vessel_dependents']}) NOT VALID"
            )
        )
    return rule_id


async def test_legacy_malformed_rule_fails_closed_everywhere(client, admin, customer, capsys):
    vessel = await create_vessel(customer.id, make="Rayglass", model="2500", year=2022)
    plug = await create_product(sku="SYN-PLUG-150", name="Plug", part_role="spark_plug", fitment_scope="specific")
    rule_id = await _legacy_malformed_rule(plug.id)

    # Catalogue detail and the explicit fitment check.
    r = await client.get(f"{API}/products/{plug.id}", params={"vessel_id": str(vessel.id)}, headers=customer.headers)
    assert r.json()["fitment"]["status"] == "unknown"
    r = await client.get(
        f"{API}/products/{plug.id}/fitment", params={"vessel_id": str(vessel.id)}, headers=customer.headers
    )
    assert r.json()["status"] == "unknown" and r.json()["reasons"] == [fitment.INCOMPLETE_RULE_REASON]
    # Catalogue list and search with compatible_only exclude it.
    for path in ("/products/", "/search/products"):
        r = await client.get(
            f"{API}{path}", params={"vessel_id": str(vessel.id), "compatible_only": "true"}, headers=customer.headers
        )
        assert r.status_code == 200, r.text
        assert all(i["id"] != str(plug.id) for i in r.json()["items"]), path
    # The public "known to fit" list does not show it.
    assert (await client.get(f"{API}/products/{plug.id}/compatibility")).json()["known_to_fit"] == []
    # The AI tool sees the same central result.
    async with async_session() as db:
        from app.models.vessel import Vessel

        v = await db.get(Vessel, vessel.id)
        runtime = TurnRuntime(db=db, user_id=customer.id, vessel=v, profile=await fitment.load_vessel_profile(db, v))
        checked = await runtime.check_fitment(str(plug.id))
        assert checked["product"]["fitment_status"] == "unknown"
        proposal = await runtime.propose_cart_action(str(plug.id), 1)
        assert proposal["accepted"] is False
    # Re-verifying it is refused until corrected.
    r = await client.post(f"{API}/products/fitment-rules/{rule_id}/verify", headers=admin.headers)
    assert r.status_code == 422 and r.json()["code"] == "malformed_fitment_rule"
    # The audit lists it.
    assert await _fitment_audit(None) == 1
    assert str(rule_id) in capsys.readouterr().out


async def test_wellformed_rule_with_other_malformed_rule_still_fits(client, customer):
    """A malformed rule fails closed on its own; a correct verified rule still supports fit."""
    vessel = await create_vessel(customer.id)
    plug = await create_product(fitment_scope="specific")
    await _legacy_malformed_rule(plug.id)
    await add_fitment_rule(plug.id, engine_make="Yamaha", engine_model="F150")
    r = await client.get(f"{API}/products/{plug.id}", params={"vessel_id": str(vessel.id)}, headers=customer.headers)
    assert r.json()["fitment"]["status"] == "verified_fit"
