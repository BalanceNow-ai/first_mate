"""Preparation items: provisional suggestions, contractor actions, catalogue candidates (SJ-05, SJ-09)."""

from __future__ import annotations

from sqlalchemy import func, select

from app.database import async_session
from app.models.cart import CartItem
from app.models.notifications import NotificationOutbox
from app.models.product import Product
from app.models.service_jobs import EvidenceRequest
from app.tests.conftest import add_fitment_rule, create_product
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_prep_support import job_url, measure


async def _suggest(client, actor, job_id):
    r = await client.post(job_url(job_id, "/preparation-items/suggest"), headers=actor.headers)
    assert r.status_code == 200, r.text
    return {i["specification"]["template"]: i for i in r.json() if i["origin"] == "assistant"}


async def _hose_measurements(client, w):
    j = w.job.id
    idm = await measure(
        client,
        w.owner,
        j,
        dimension="hose_internal_diameter",
        component="pump outlet hose",
        value_text="25 mm",
        method="marking_read",
    )
    od = await measure(
        client,
        w.owner,
        j,
        dimension="hose_external_diameter",
        component="pump outlet hose",
        value_text="32",
        unit="mm",
        method="owner_caliper",
    )
    return idm, od


async def test_sj05_suggestions_carry_evidence_unknowns_and_no_invented_quantities(client, world):  # noqa: F811
    """No catalogue products at all: 'no matching product' is valid and no SKU is invented."""
    items = await _suggest(client, world.owner, world.job.id)
    assert {"hose", "clamps", "fitting", "tools"} <= set(items)
    for item in items.values():
        assert item["quantity"] is None and item["status"] == "suggested" and item["requirement_state"] == "possible"
        assert item["catalogue_match"] == "none" and item["candidates"] == [] and item["confirmed_product"] is None
        assert item["purpose"] and item["source_note"] and item["open_requirements"]
        assert "not a purchase" in item["commercial_note"]
    hose = items["hose"]
    assert any("Application not confirmed" in r for r in hose["open_requirements"])
    assert any("internal diameter" in r.lower() for r in hose["open_requirements"])
    assert any("Length needed not known" in r for r in hose["open_requirements"])
    assert "Fitting thread not confirmed" in items["fitting"]["open_requirements"]
    assert any("OD not recorded" in r for r in items["clamps"]["open_requirements"])
    # Repeating the suggestion does not duplicate items.
    again = await client.post(job_url(world.job.id, "/preparation-items/suggest"), headers=world.owner.headers)
    assert len(again.json()) == len(items)


async def test_sj05_far_end_gap_and_measurements_shape_requirements(client, world):  # noqa: F811
    async with async_session() as s:
        s.add(
            EvidenceRequest(
                job_id=world.job.id,
                requester_role="assistant",
                category="connections",
                prompt="Photograph the far end of the hose",
                reason="Both ends determine the fittings",
                status="unavailable",
                unavailable_reason="cannot_safely_access",
            )
        )
        await s.commit()
    idm, od = await _hose_measurements(client, world)
    route = await measure(
        client,
        world.owner,
        world.job.id,
        dimension="route_length",
        component="visible run",
        value_text="0.8",
        unit="m",
        method="owner_tape",
    )
    items = await _suggest(client, world.owner, world.job.id)
    hose, clamps = items["hose"], items["clamps"]
    assert "Far-end connection not visible" in hose["open_requirements"]
    assert any("0.8 m recorded; total length and allowance not confirmed" in r for r in hose["open_requirements"])
    assert {d["measurement_id"] for d in hose["depends_on"]} == {idm["id"], route["id"]}
    assert hose["specification"]["internal_diameter"] == "25 mm"
    assert hose["specification"]["internal_diameter_state"] == "owner_declared"
    assert clamps["specification"]["required_od"] == "32 mm"
    assert any("include the recorded 32 mm hose OD" in r for r in clamps["open_requirements"])
    assert od["id"] in {d["measurement_id"] for d in clamps["depends_on"]}


async def test_sj04_sj05_a_25mm_clamp_is_not_assumed_to_fit_a_32mm_od_hose(client, world):  # noqa: F811
    small = await create_product(
        name="Hose clamp 20-25 mm (synthetic)",
        category="General",
        fitment_scope="universal",
        specifications={"clamp_range_mm": [20, 25]},
    )
    large = await create_product(
        name="Hose clamp 30-40 mm (synthetic)",
        category="General",
        fitment_scope="universal",
        specifications={"clamp_range_mm": [30, 40]},
    )
    unspecified = await create_product(name="Hose clamp assortment (synthetic)", category="General")
    # Only the ID is known: no clamp is excluded, none is "covering" — the ID is not the clamp size.
    await measure(
        client,
        world.owner,
        world.job.id,
        dimension="hose_internal_diameter",
        component="hose",
        value_text="25",
        unit="mm",
        method="marking_read",
    )
    clamps = (await _suggest(client, world.owner, world.job.id))["clamps"]
    checks = {c["name"]: c["dimension_check"]["status"] for c in clamps["candidates"]}
    assert checks == {small.name: "unknown", large.name: "unknown", unspecified.name: "unknown"}
    assert any("bore (ID) is not the clamp size" in r for r in clamps["open_requirements"])
    # Once the OD is measured, a fresh suggestion excludes the 20-25 mm clamp.
    od = await measure(
        client,
        world.owner,
        world.job.id,
        dimension="hose_external_diameter",
        component="hose",
        value_text="32",
        unit="mm",
        method="owner_caliper",
    )
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/reject"), json={}, headers=world.owner.headers
    )
    assert r.status_code == 200
    clamps = (await _suggest(client, world.owner, world.job.id))["clamps"]
    names = {c["name"]: c for c in clamps["candidates"]}
    assert small.name not in names
    assert names[large.name]["dimension_check"]["status"] == "range_includes_recorded_od"
    assert "not a verified fit" in names[large.name]["dimension_check"]["reason"]
    assert clamps["catalogue_match"] == "candidates"
    assert od["id"] in {d["measurement_id"] for d in clamps["depends_on"]}
    # Contractor confirms the requirement: catalogue match is still only "candidates".
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/confirm"),
        json={
            "expected_version": clamps["version"],
            "quantity": "2",
            "unit": "each",
            "quantity_basis": "two hose ends",
        },
        headers=world.tech.headers,
    )
    assert r.status_code == 200, r.text
    confirmed = r.json()
    assert confirmed["status"] == "contractor_confirmed" and confirmed["catalogue_match"] == "candidates"
    assert confirmed["quantity"] == "2" and confirmed["quantity_basis"] == "Contractor: two hose ends"
    assert confirmed["confirmed_by"] == str(world.tech.id)
    # The excluded clamp cannot be confirmed as the catalogue match; the covering one can.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/catalogue-match"),
        json={"product_id": str(small.id)},
        headers=world.tech.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "dimension_mismatch"
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/catalogue-match"),
        json={"product_id": str(large.id), "expected_version": confirmed["version"]},
        headers=world.tech.headers,
    )
    assert r.status_code == 200 and r.json()["catalogue_match"] == "confirmed"
    assert r.json()["confirmed_product"]["sku"] == large.sku
    # Nothing was added to any cart.
    async with async_session() as s:
        assert (await s.execute(select(func.count()).select_from(CartItem))).scalar_one() == 0


async def test_candidates_are_real_products_filtered_by_central_fitment(client, world):  # noqa: F811
    fits = await create_product(name="Yamaha F150 hose kit (synthetic)", category="Plumbing")
    await add_fitment_rule(fits.id)  # verified Yamaha F150 → the world vessel's engine
    wrong = await create_product(name="Suzuki DF140 hose kit (synthetic)", category="Plumbing")
    await add_fitment_rule(wrong.id, engine_make="Suzuki", engine_model="DF140")
    await create_product(name="Inactive hose (synthetic)", category="Plumbing", is_active=False)
    hose = (await _suggest(client, world.owner, world.job.id))["hose"]
    by_name = {c["name"]: c for c in hose["candidates"]}
    assert set(by_name) == {fits.name}
    assert by_name[fits.name]["fitment_status"] == "verified_fit"
    async with async_session() as s:
        real = {p.sku for p in (await s.execute(select(Product))).scalars()}
    assert {c["sku"] for c in hose["candidates"]} <= real
    # A non-candidate, non-existent product cannot be "confirmed".
    await client.post(
        job_url(world.job.id, f"/preparation-items/{hose['id']}/confirm"), json={}, headers=world.tech.headers
    )
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{hose['id']}/catalogue-match"),
        json={"product_id": str(wrong.id)},
        headers=world.tech.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "fitment_mismatch"


async def test_contractor_item_actions(client, world):  # noqa: F811
    items = await _suggest(client, world.owner, world.job.id)
    hose, tools, fitting = items["hose"], items["tools"], items["fitting"]
    # Owner cannot confirm; a stale version is a 409.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{hose['id']}/confirm"), json={}, headers=world.owner.headers
    )
    assert r.status_code == 403
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{hose['id']}/confirm"),
        json={"expected_version": 99},
        headers=world.tech.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    # A quantity needs a stated basis.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{hose['id']}/confirm"),
        json={"quantity": "1.5", "unit": "m"},
        headers=world.tech.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "quantity_basis_required"
    # Request more evidence → an EvidenceRequest from the contractor; the owner is notified.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{hose['id']}/request-evidence"),
        json={
            "category": "markings",
            "prompt": "Photograph the printed text along the hose without moving it",
            "reason": "The hose application rating is printed on the hose",
        },
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["item"]["status"] == "needs_evidence"
    assert body["evidence_request"]["requester_role"] == "contractor"
    assert body["item"]["evidence_request_ids"] == [body["evidence_request"]["id"]]
    async with async_session() as s:
        req = await s.get(EvidenceRequest, body["evidence_request"]["id"])
        assert req.organization_id == world.org_a and req.requested_by == world.tech.id
        assert req.component == "Replacement hose"
        notes = (
            await s.execute(select(NotificationOutbox).where(NotificationOutbox.user_id == world.owner.id))
        ).scalars()
        payloads = [n.payload for n in notes]
        assert {"kind": "evidence_requested", "job_id": str(world.job.id)} in payloads  # content-free
    # Replace → new contractor item; the original points to it.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{fitting['id']}/replace"),
        json={
            "category": "part",
            "name": "1/2 in NPT x 25 mm barb, bronze",
            "purpose": "Replace the cracked barb at the pump outlet",
            "quantity": "1",
            "unit": "each",
            "quantity_basis": "one outlet",
            "expected_version": fitting["version"],
        },
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["origin"] == "contractor" and new["status"] == "contractor_confirmed"
    listed = {
        i["id"]: i
        for i in (await client.get(job_url(world.job.id, "/preparation-items"), headers=world.owner.headers)).json()
    }
    assert listed[fitting["id"]]["status"] == "replaced" and listed[fitting["id"]]["replaced_by_id"] == new["id"]
    # Reject.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{tools['id']}/reject"),
        json={"note": "own tools"},
        headers=world.tech.headers,
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{tools['id']}/confirm"), json={}, headers=world.tech.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "item_inactive"
    # Owner adds a manual item; dependency ids must be on this job.
    r = await client.post(
        job_url(world.job.id, "/preparation-items"),
        json={"category": "consumable", "name": "Absorbent pads", "purpose": "Catch drips"},
        headers=world.owner.headers,
    )
    assert r.status_code == 201 and r.json()["origin"] == "owner" and r.json()["quantity"] is None


async def test_sj09_changed_measurement_supersedes_dependent_confirmation_and_selection(client, world):  # noqa: F811
    large = await create_product(
        name="Hose clamp 30-40 mm (synthetic)",
        category="General",
        fitment_scope="universal",
        specifications={"clamp_range_mm": [30, 40]},
    )
    _, od = await _hose_measurements(client, world)
    clamps = (await _suggest(client, world.owner, world.job.id))["clamps"]
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/confirm"), json={}, headers=world.tech.headers
    )
    assert r.status_code == 200
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/catalogue-match"),
        json={"product_id": str(large.id)},
        headers=world.tech.headers,
    )
    assert r.json()["catalogue_match"] == "confirmed"
    # The owner re-measures the OD: 42 mm.
    r = await client.post(
        job_url(world.job.id, f"/measurements/{od['id']}/revise"),
        json={
            "dimension": "hose_external_diameter",
            "component": "pump outlet hose",
            "value_text": "42",
            "unit": "mm",
            "method": "owner_caliper",
        },
        headers=world.owner.headers,
    )
    assert r.status_code == 201
    new_od = r.json()
    listed = {
        i["id"]: i
        for i in (await client.get(job_url(world.job.id, "/preparation-items"), headers=world.owner.headers)).json()
    }
    old = listed[clamps["id"]]
    assert old["status"] == "superseded" and old["confirmed_product"]["sku"] == large.sku  # history kept
    copy = listed[old["replaced_by_id"]]
    assert copy["status"] == "suggested" and copy["confirmed_by"] is None and copy["confirmed_product"] is None
    assert copy["catalogue_match"] == "candidates"
    assert new_od["id"] in {d["measurement_id"] for d in copy["depends_on"]}
    assert od["id"] not in {d["measurement_id"] for d in copy["depends_on"]}
    assert any("Re-check" in r for r in copy["open_requirements"])
    # The 30-40 mm clamp now fails the dimension check against 42 mm.
    cand = {c["sku"]: c for c in copy["candidates"]}
    assert cand[large.sku]["dimension_check"]["status"] == "range_excludes_recorded_od"
    # Confirming the superseded item is refused.
    r = await client.post(
        job_url(world.job.id, f"/preparation-items/{clamps['id']}/confirm"), json={}, headers=world.tech.headers
    )
    assert r.status_code == 409
