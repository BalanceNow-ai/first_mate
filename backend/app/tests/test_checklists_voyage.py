"""Voyage checklists: tier inheritance, tailoring, verified-fitment linking, persistence,
regeneration, idempotent add-missing, manual link rules and export."""

import pytest_asyncio
from sqlalchemy import select, update

from app.database import async_session
from app.models.product import Product
from app.models.vessel import Vessel
from app.seed.catalogue import seed_synthetic
from app.tests.conftest import create_vessel
from app.tests.test_catalogue_support import API


@pytest_asyncio.fixture
async def seeded():
    async with async_session() as s:
        await seed_synthetic(s)
        await s.commit()
        return {p.sku: p for p in (await s.execute(select(Product))).scalars()}


def gen_url(vid, regenerate=False):
    return f"{API}/checklists/vessel/{vid}/generate" + ("?regenerate=true" if regenerate else "")


def by_key(tier_body):
    return {i["template_key"]: i for i in tier_body["items"]}


async def _generate(client, actor, vessel):
    r = await client.post(gen_url(vessel.id), headers=actor.headers)
    assert r.status_code == 201, r.text
    return {t["tier"]: t for t in r.json()["tiers"]}


async def test_inheritance_one_row_per_item_and_introduced_in(client, customer, seeded):
    vessel = await create_vessel(customer.id)
    tiers = await _generate(client, customer, vessel)
    assert list(tiers) == ["grab_and_go", "coastal_cruising", "offshore_passage"]
    g, c, o = (set(by_key(tiers[t])) for t in tiers)
    assert g < c < o
    for key in g:
        ids = {by_key(tiers[t])[key]["id"] for t in tiers}
        assert len(ids) == 1  # the same row is inherited, not copied
        assert by_key(tiers["offshore_passage"])[key]["introduced_in"] == "grab_and_go"
    assert by_key(tiers["offshore_passage"])["c_impeller"]["introduced_in"] == "coastal_cruising"
    assert all(i["introduced_in"] == "grab_and_go" for i in tiers["grab_and_go"]["items"])
    assert tiers["grab_and_go"]["total"] == len(g)


async def test_tailoring_by_vessel_profile(client, customer):
    outboard = await create_vessel(customer.id)
    t = await _generate(client, customer, outboard)
    off = by_key(t["offshore_passage"])
    for absent in ("c_toilet_valves", "o_inverter", "o_steering_fluid", "o_sail_repair", "o_sail_hardware"):
        assert absent not in off
    assert off["g_spark_plugs"]["applicability"] == "applies"
    assert off["g_kill_switch"]["applicability"] == "applies"
    assert off["c_bilge_pump"]["applicability"] == "if_fitted"  # bilge pump not recorded
    assert off["c_belt"]["applicability"] == "if_fitted"

    # Recording a toilet, inverter and hydraulic steering adds their items on regeneration.
    for cat in ("toilet", "inverter", "steering_hydraulic", "bilge_pump"):
        r = await client.post(f"{API}/vessels/{outboard.id}/equipment", json={"category": cat, "make": "Fixture"},
                              headers=customer.headers)
        assert r.status_code == 201
    r = await client.post(gen_url(outboard.id, regenerate=True), headers=customer.headers)
    off = by_key({tt["tier"]: tt for tt in r.json()["tiers"]}["offshore_passage"])
    for present in ("c_toilet_valves", "o_inverter", "o_steering_fluid"):
        assert off[present]["applicability"] == "applies"
    assert off["c_bilge_pump"]["applicability"] == "applies"

    sail = await create_vessel(customer.id, nickname="Yacht", propulsion_type="sail", engine_make=None,
                               engine_model=None, engine_year=None, is_primary=False)
    off = by_key((await _generate(client, customer, sail))["offshore_passage"])
    assert off["o_sail_repair"]["applicability"] == "applies" and off["o_sail_hardware"]["applicability"] == "applies"
    assert "g_kill_switch" not in off  # known not to be an outboard
    assert off["g_spark_plugs"]["applicability"] == "if_fitted"  # auxiliary engine unknown
    assert off["g_propeller"]["applicability"] == "if_fitted"

    jet = await create_vessel(customer.id, nickname="Jet", propulsion_type="jet", is_primary=False)
    off = by_key((await _generate(client, customer, jet))["offshore_passage"])
    assert "g_propeller" not in off and off["g_fuel_filter"]["applicability"] == "applies"

    electric = await create_vessel(customer.id, nickname="Volt", propulsion_type="electric", engine_make=None,
                                   engine_model=None, engine_year=None, is_primary=False)
    off = by_key((await _generate(client, customer, electric))["offshore_passage"])
    assert "g_fuel_filter" not in off and "g_spark_plugs" not in off and "g_propeller" in off


async def test_linking_uses_verified_fitment_and_follows_engine_changes(client, customer, seeded):
    vessel = await create_vessel(customer.id)  # Yamaha F150
    t = await _generate(client, customer, vessel)
    g = by_key(t["grab_and_go"])
    assert g["g_spark_plugs"]["product"]["sku"] == "SYN-PLUG-150" and g["g_spark_plugs"]["link_status"] == "verified_fit"
    ff = g["g_fuel_filter"]
    assert ff["product"]["sku"] == "SYN-FF-150"  # in stock, lowest effective price
    assert [a["sku"] for a in ff["alternatives"]] == ["SYN-FF-150-PREM"]
    assert all(a["fitment"]["status"] in ("verified_fit", "universal") for a in ff["alternatives"])
    assert g["g_duct_tape"]["link_status"] == "universal"
    prop = g["g_propeller"]  # product exists but fitment is unknown → never auto-linked
    assert prop["link_status"] == "unlinked" and prop["product"] is None
    assert prop["search_hint"]["part_role"] == "propeller" and "part_role=propeller" in prop["search_hint"]["path"]

    async with async_session() as db:
        await db.execute(update(Vessel).where(Vessel.id == vessel.id).values(engine_make="Suzuki", engine_model="DF140"))
        await db.commit()
    g = by_key((await client.get(f"{API}/checklists/vessel/{vessel.id}/tiers/grab_and_go", headers=customer.headers)).json())
    assert g["g_spark_plugs"]["product"]["sku"] == "SYN-PLUG-140"
    assert g["g_fuel_filter"]["product"]["sku"] == "SYN-FF-140" and g["g_fuel_filter"]["product"]["in_stock"] is False

    async with async_session() as db:  # no engine recorded → engine parts become unlinked
        await db.execute(update(Vessel).where(Vessel.id == vessel.id).values(engine_make=None, engine_model=None))
        await db.commit()
    g = by_key((await client.get(f"{API}/checklists/vessel/{vessel.id}/tiers/grab_and_go", headers=customer.headers)).json())
    assert g["g_spark_plugs"]["link_status"] == "unlinked" and g["g_zip_ties"]["link_status"] == "universal"


async def test_checked_state_persists_and_regenerate_preserves(client, customer, other_customer, seeded):
    vessel = await create_vessel(customer.id)
    t = await _generate(client, customer, vessel)
    item = by_key(t["grab_and_go"])["g_duct_tape"]
    r = await client.patch(f"{API}/checklists/items/{item['id']}", json={"is_checked": True}, headers=customer.headers)
    assert r.status_code == 200 and r.json()["is_checked"] and r.json()["checked_at"]
    assert (await client.patch(f"{API}/checklists/items/{item['id']}", json={"is_checked": False}, headers=other_customer.headers)).status_code == 404
    assert (await client.post(f"{API}/checklists/items/{item['id']}/toggle", headers=other_customer.headers)).status_code == 404

    body = (await client.get(f"{API}/checklists/vessel/{vessel.id}", headers=customer.headers)).json()
    assert body["generated"] and "NOT a certified" in body["disclaimer"]
    for tier in body["tiers"]:  # shared across every tier that inherits it
        assert by_key(tier)["g_duct_tape"]["is_checked"] is True
    assert body["tiers"][0]["checked"] == 1

    assert (await client.post(gen_url(vessel.id), headers=customer.headers)).status_code == 409
    r = await client.post(gen_url(vessel.id, regenerate=True), headers=customer.headers)
    assert r.status_code == 201
    regenerated = by_key(r.json()["tiers"][2])
    assert regenerated["g_duct_tape"]["is_checked"] is True and regenerated["g_duct_tape"]["id"] != item["id"]
    assert regenerated["g_zip_ties"]["is_checked"] is False

    toggled = (await client.post(f"{API}/checklists/items/{regenerated['g_duct_tape']['id']}/toggle", headers=customer.headers)).json()
    assert toggled["is_checked"] is False and toggled["checked_at"] is None

    assert (await client.get(f"{API}/checklists/vessel/{vessel.id}", headers=other_customer.headers)).status_code == 404
    assert (await client.post(gen_url(vessel.id), headers=other_customer.headers)).status_code == 404
    assert (await client.delete(f"{API}/checklists/vessel/{vessel.id}", headers=other_customer.headers)).status_code == 404
    assert (await client.delete(f"{API}/checklists/vessel/{vessel.id}", headers=customer.headers)).status_code == 204
    after = (await client.get(f"{API}/checklists/vessel/{vessel.id}", headers=customer.headers)).json()
    assert after["generated"] is False and after["tiers"] == []
    assert (await client.get(f"{API}/checklists/vessel/{vessel.id}/tiers/grab_and_go", headers=customer.headers)).status_code == 404


async def test_add_missing_to_cart_is_idempotent_and_stock_limited(client, customer, other_customer, seeded):
    vessel = await create_vessel(customer.id)
    t = await _generate(client, customer, vessel)
    g = by_key(t["grab_and_go"])
    await client.patch(f"{API}/checklists/items/{g['g_zip_ties']['id']}", json={"is_checked": True}, headers=customer.headers)
    async with async_session() as db:  # fuel filter wanted ×2 but only 1 in stock
        await db.execute(update(Product).where(Product.sku == "SYN-FF-150").values(stock_quantity=1))
        await db.commit()
    url = f"{API}/checklists/vessel/{vessel.id}/add-missing-to-cart"
    r = await client.post(url, json={"tier": "grab_and_go"}, headers=customer.headers)
    assert r.status_code == 200, r.text
    first = r.json()
    lines = {line["template_key"]: line for line in first["lines"]}
    assert "g_zip_ties" not in lines  # already on board
    assert lines["g_fuel_filter"]["status"] == "limited" and lines["g_fuel_filter"]["quantity_in_cart"] == 1
    assert lines["g_spark_plugs"]["status"] == "added"
    assert {s["item_name"] for s in first["skipped"]} >= {g["g_propeller"]["item_name"]}
    assert first["added_count"] == len([line for line in first["lines"] if line["added"] > 0])

    cart1 = (await client.get(f"{API}/cart/", headers=customer.headers)).json()
    second = (await client.post(url, json={"tier": "grab_and_go"}, headers=customer.headers)).json()
    assert all(line["added"] == 0 for line in second["lines"]) and second["added_count"] == 0
    cart2 = (await client.get(f"{API}/cart/", headers=customer.headers)).json()
    assert cart1["item_count"] == cart2["item_count"]
    qty = {i["product"]["sku"]: i["quantity"] for i in cart2["items"]}
    assert qty["SYN-FF-150"] == 1 and "SYN-ZIP-TIES" not in qty
    assert (await client.post(url, json={"tier": "grab_and_go"}, headers=other_customer.headers)).status_code == 404
    assert (await client.post(url, json={"tier": "bogus"}, headers=customer.headers)).status_code == 422


async def test_manual_link_rules(client, customer, seeded):
    vessel = await create_vessel(customer.id)
    t = await _generate(client, customer, vessel)
    g = by_key(t["grab_and_go"])
    link = lambda iid: f"{API}/checklists/items/{iid}/link"  # noqa: E731
    r = await client.put(link(g["g_spark_plugs"]["id"]), json={"product_id": str(seeded["SYN-PLUG-140"].id)}, headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "fitment_mismatch"
    r = await client.put(link(g["g_propeller"]["id"]), json={"product_id": str(seeded["SYN-PROP-AL13"].id)}, headers=customer.headers)
    assert r.status_code == 200
    body = r.json()
    assert body["link_status"] == "user_linked_unverified" and "not been verified" in body["warning"]
    assert body["product"]["fitment"]["status"] == "unknown"
    again = by_key((await client.get(f"{API}/checklists/vessel/{vessel.id}/tiers/grab_and_go", headers=customer.headers)).json())
    assert again["g_propeller"]["link_status"] == "user_linked_unverified" and again["g_propeller"]["warning"]
    r = await client.put(link(g["g_tools"]["id"]), json={"product_id": str(seeded["SYN-TOOLKIT-COASTAL"].id)}, headers=customer.headers)
    assert r.json()["link_status"] == "universal" and r.json()["warning"] is None
    inactive = seeded["SYN-NAVBULB"]
    async with async_session() as db:
        await db.execute(update(Product).where(Product.id == inactive.id).values(is_active=False))
        await db.commit()
    r = await client.put(link(g["g_nav_bulbs"]["id"]), json={"product_id": str(inactive.id)}, headers=customer.headers)
    assert r.status_code == 404


async def test_export_csv_and_html(client, customer, other_customer, seeded):
    vessel = await create_vessel(customer.id, nickname="<script>alert(1)</script> Stabi")
    t = await _generate(client, customer, vessel)
    g = by_key(t["grab_and_go"])
    await client.patch(f"{API}/checklists/items/{g['g_duct_tape']['id']}", json={"is_checked": True}, headers=customer.headers)
    url = f"{API}/checklists/vessel/{vessel.id}/export"
    r = await client.get(url, params={"tier": "coastal_cruising", "format": "csv"}, headers=customer.headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.text
    assert "NOT a certified safety-equipment" in text
    assert "Spare water pump impeller & gasket" in text and "Duct tape" in text
    assert "SYN-PLUG-150" in text
    duct = next(line for line in text.splitlines() if line.startswith("grab_and_go,General,Duct tape"))
    assert ",yes," in duct

    r = await client.get(url, params={"tier": "grab_and_go"}, headers=customer.headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "Grab &amp; Go Kit" in html and "&#9744;" in html and "&#9745;" in html
    assert "NOT a certified safety-equipment list or a regulatory-compliance assessment" in html
    assert "Spare water pump impeller" not in html  # coastal item not in the grab & go export
    assert (await client.get(url, params={"tier": "grab_and_go"}, headers=other_customer.headers)).status_code == 404
    assert (await client.get(url, params={"tier": "nope"}, headers=customer.headers)).status_code == 422
