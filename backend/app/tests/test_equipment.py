"""Vessel equipment (provenance/verification), OEM data, service records and reminders."""

from datetime import date

import pytest

from app.services import loyalty
from app.tests.conftest import add_fitment_rule, create_product, create_vessel
from app.tests.test_catalogue_support import API, audit_actions, categories, make_boat  # noqa: F401


def eq_url(vid, suffix=""):
    return f"{API}/vessels/{vid}/equipment{suffix}"


async def test_add_edit_remove_and_isolation(client, customer, other_customer, categories):  # noqa: F811
    vessel = await create_vessel(customer.id)
    r = await client.post(
        eq_url(vessel.id),
        json={"category": "chartplotter", "make": "Garmin", "model": "GPSMAP 1243"},
        headers=customer.headers,
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["origin"] == "user_added" and item["provenance"] == "owner_declared"
    assert item["confidence_score"] == 1.0 and item["verification_status"] == "unverified"
    assert item["reliability"] == "owner_declared" and item["category"]["slug"] == "chartplotter"
    eid = item["id"]
    assert (
        await client.post(eq_url(vessel.id), json={"category": "warp_drive", "make": "x"}, headers=customer.headers)
    ).status_code == 422
    assert (
        await client.post(
            eq_url(vessel.id), json={"category": "vhf_radio", "make": "x", "origin": "oem"}, headers=customer.headers
        )
    ).status_code == 422

    r = await client.patch(
        eq_url(vessel.id, f"/{eid}"), json={"model": "GPSMAP 1243xsv", "serial_number": "S1"}, headers=customer.headers
    )
    assert r.status_code == 200 and r.json()["model"] == "GPSMAP 1243xsv"

    # Another owner sees nothing and can change nothing.
    for method, kwargs in (("get", {}), ("post", {"json": {"category": "vhf_radio", "make": "x"}})):
        assert (
            await getattr(client, method)(eq_url(vessel.id), headers=other_customer.headers, **kwargs)
        ).status_code == 404
    assert (
        await client.patch(eq_url(vessel.id, f"/{eid}"), json={"make": "x"}, headers=other_customer.headers)
    ).status_code == 404
    assert (await client.delete(eq_url(vessel.id, f"/{eid}"), headers=other_customer.headers)).status_code == 404
    theirs = await create_vessel(other_customer.id)
    assert (
        await client.patch(eq_url(theirs.id, f"/{eid}"), json={"make": "x"}, headers=other_customer.headers)
    ).status_code == 404

    assert (await client.delete(eq_url(vessel.id, f"/{eid}"), headers=customer.headers)).status_code == 204
    assert (await client.get(eq_url(vessel.id), headers=customer.headers)).json()["items"] == []
    removed = (
        await client.get(eq_url(vessel.id), params={"include_removed": "true"}, headers=customer.headers)
    ).json()["items"]
    assert removed[0]["removed_at"] is not None
    assert (
        await client.patch(eq_url(vessel.id, f"/{eid}"), json={"make": "x"}, headers=customer.headers)
    ).status_code == 409


async def test_oem_provenance_and_low_confidence_not_fact(client, customer, categories):  # noqa: F811
    boat = await make_boat(
        oem=[
            ("engine", "Yamaha", "F150", "manufacturer", 1.0, "verified"),
            ("vhf_radio", "FixtureCom", "FC-25", "crowdsourced_unverified", 0.3, "unverified"),
            ("toilet", "Rejected", None, "dealer", 0.9, "rejected"),
        ]
    )
    vessel = await create_vessel(customer.id, engine_make=None, engine_model=None, engine_year=None)
    assert (
        await client.post(eq_url(vessel.id, "/apply-oem"), headers=customer.headers)
    ).status_code == 409  # not linked
    r = await client.patch(f"{API}/vessels/{vessel.id}", json={"year": 2022}, headers=customer.headers)
    assert r.json()["model_year_id"] == str(boat["model_year_id"])

    listing = (await client.get(eq_url(vessel.id), headers=customer.headers)).json()
    factory = {i["category"]["slug"]: i for i in listing["items"]}
    assert set(factory) == {"engine", "vhf_radio"}  # rejected OEM data hidden
    assert all(i["source"] == "factory_oem" for i in factory.values())
    assert factory["engine"]["reliability"] == "verified" and factory["engine"]["data_source"] == "manufacturer"
    assert (
        factory["vhf_radio"]["reliability"] == "unconfirmed"
        and "low confidence" in factory["vhf_radio"]["display_note"]
    )

    r = await client.post(eq_url(vessel.id, "/apply-oem"), headers=customer.headers)
    assert r.status_code == 200, r.text
    created = {i["category"]["slug"]: i for i in r.json()["created"]}
    assert created["engine"]["origin"] == "oem" and created["engine"]["provenance"] == "oem_database"
    assert created["engine"]["confidence_score"] == 1.0 and created["engine"]["verification_status"] == "verified"
    assert created["vhf_radio"]["confidence_score"] == 0.3 and created["vhf_radio"]["reliability"] == "unconfirmed"
    again = (await client.post(eq_url(vessel.id, "/apply-oem"), headers=customer.headers)).json()
    assert again["created"] == [] and len(again["skipped_already_applied"]) == 2
    listing = (await client.get(eq_url(vessel.id), headers=customer.headers)).json()["items"]
    assert {i["source"] for i in listing} == {"installed"} and len(listing) == 2

    # The high-confidence OEM engine now drives fitment; the low-confidence radio does not.
    plug = await create_product(fitment_scope="specific")
    await add_fitment_rule(plug.id, engine_make="Yamaha", engine_model="F150")
    radio_part = await create_product(fitment_scope="specific")
    await add_fitment_rule(
        radio_part.id,
        engine_make=None,
        engine_model=None,
        equipment_category_id=categories["vhf_radio"],
        equipment_make="FixtureCom",
    )
    h, params = customer.headers, {"vessel_id": str(vessel.id)}
    assert (await client.get(f"{API}/products/{plug.id}/fitment", params=params, headers=h)).json()[
        "status"
    ] == "verified_fit"
    radio = (await client.get(f"{API}/products/{radio_part.id}/fitment", params=params, headers=h)).json()
    assert radio["status"] == "unknown" and "unverified" in radio["message"]

    # Owner confirms the radio: it becomes an owner declaration (a fact for fitment).
    rid = created["vhf_radio"]["id"]
    r = await client.patch(eq_url(vessel.id, f"/{rid}"), json={"model": "FC-25"}, headers=h)
    assert r.json()["provenance"] == "owner_declared" and r.json()["confidence_score"] == 1.0
    assert (await client.get(f"{API}/products/{radio_part.id}/fitment", params=params, headers=h)).json()[
        "status"
    ] == "verified_fit"


@pytest.fixture
def loyalty_spy(monkeypatch):
    calls = []

    async def spy(db, user_id, request_id):
        calls.append((user_id, request_id))

    monkeypatch.setattr(loyalty, "award_profile_verification_bonus", spy)
    return calls


async def test_verification_request_approve_and_reject(client, customer, admin, loyalty_spy, categories):  # noqa: F811
    vessel = await create_vessel(customer.id)
    url = eq_url(vessel.id, "/verification-requests")
    assert (await client.post(url, json={}, headers=customer.headers)).status_code == 422  # nothing to verify
    e1 = (
        await client.post(
            eq_url(vessel.id), json={"category": "vhf_radio", "make": "Icom", "model": "M330"}, headers=customer.headers
        )
    ).json()
    e2 = (
        await client.post(
            eq_url(vessel.id),
            json={"category": "bilge_pump", "make": "Rule", "model": "1100"},
            headers=customer.headers,
        )
    ).json()
    r = await client.post(
        url, json={"note": "Brochure attached", "evidence_url": "https://example.test/b.pdf"}, headers=customer.headers
    )
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending" and set(req["equipment_ids"]) == {e1["id"], e2["id"]}
    assert (await client.post(url, json={}, headers=customer.headers)).status_code == 409
    items = (await client.get(eq_url(vessel.id), headers=customer.headers)).json()["items"]
    assert {i["verification_status"] for i in items} == {"pending_review"}

    queue_url = f"{API}/boat-db/verification-requests"
    assert (await client.get(queue_url, headers=customer.headers)).status_code == 403
    assert (await client.post(f"{queue_url}/{req['id']}/approve", headers=customer.headers)).status_code == 403
    queue = (await client.get(queue_url, headers=admin.headers)).json()
    assert [q["id"] for q in queue] == [req["id"]] and len(queue[0]["equipment"]) == 2

    r = await client.post(f"{queue_url}/{req['id']}/approve", json={"review_note": "ok"}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert loyalty_spy == [(customer.id, __import__("uuid").UUID(req["id"]))]
    items = (await client.get(eq_url(vessel.id), headers=customer.headers)).json()["items"]
    assert {(i["verification_status"], i["provenance"], i["reliability"]) for i in items} == {
        ("verified", "staff_verified", "verified")
    }
    assert (await client.post(f"{queue_url}/{req['id']}/approve", headers=admin.headers)).status_code == 409
    assert len(loyalty_spy) == 1  # awarded once
    assert "equipment_verification.approve" in await audit_actions(req["id"])

    # Rejection returns rows to unverified owner declarations, no bonus.
    await client.post(eq_url(vessel.id), json={"category": "autopilot", "make": "Raymarine"}, headers=customer.headers)
    req2 = (await client.post(url, json={}, headers=customer.headers)).json()
    assert len(req2["equipment_ids"]) == 1
    r = await client.post(
        f"{queue_url}/{req2['id']}/reject", json={"review_note": "No evidence"}, headers=admin.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    items = {
        i["category"]["slug"]: i
        for i in (await client.get(eq_url(vessel.id), headers=customer.headers)).json()["items"]
    }
    assert (
        items["autopilot"]["verification_status"] == "unverified"
        and items["autopilot"]["provenance"] == "owner_declared"
    )
    assert len(loyalty_spy) == 1
    history = (await client.get(url, headers=customer.headers)).json()
    assert [h["status"] for h in history] == ["rejected", "approved"]


async def test_service_records_and_reminders(client, customer, other_customer, categories):  # noqa: F811
    vessel = await create_vessel(customer.id, engine_hours=150)
    h = customer.headers
    base = f"{API}/vessels/{vessel.id}"
    eq = (
        await client.post(eq_url(vessel.id), json={"category": "engine", "make": "Yamaha", "model": "F150"}, headers=h)
    ).json()
    r = await client.post(
        f"{base}/service-records",
        json={
            "service_type": "100-hour service",
            "performed_on": "2026-10-01",
            "engine_hours": 100,
            "provider_name": "Marina Mechanics",
            "cost_cents": 45000,
            "equipment_id": eq["id"],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["cost_cents"] == 45000 and rec["currency"] == "NZD"
    r = await client.patch(f"{base}/service-records/{rec['id']}", json={"notes": "Replaced impeller"}, headers=h)
    assert r.json()["notes"] == "Replaced impeller"
    theirs = await create_vessel(other_customer.id)
    assert (
        await client.post(
            f"{base}/service-records",
            json={"service_type": "x", "performed_on": "2026-01-01", "equipment_id": eq["id"]},
            headers=other_customer.headers,
        )
    ).status_code == 404
    assert (
        await client.post(
            f"{API}/vessels/{theirs.id}/service-records",
            json={"service_type": "x", "performed_on": "2026-01-01", "equipment_id": eq["id"]},
            headers=other_customer.headers,
        )
    ).status_code == 422
    assert (await client.get(f"{base}/service-records", headers=other_customer.headers)).status_code == 404

    # Reminders: owner-defined due date and/or hours; complete creates the next from the interval.
    assert (await client.post(f"{base}/service-reminders", json={"title": "No due"}, headers=h)).status_code == 422
    r = await client.post(
        f"{base}/service-reminders",
        json={
            "title": "Engine service",
            "due_on": "2027-01-31",
            "due_engine_hours": 200,
            "interval_months": 1,
            "interval_hours": 100,
            "equipment_id": eq["id"],
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    rem = r.json()
    assert rem["source"] == "owner" and rem["status"] == "active" and rem["is_due"] is False
    r = await client.post(
        f"{base}/service-reminders/{rem['id']}/complete",
        json={"completed_on": "2027-01-31", "engine_hours": 205},
        headers=h,
    )
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["completed"]["status"] == "completed"
    assert done["next"]["due_on"] == "2027-02-28" and done["next"]["due_engine_hours"] == 305
    assert done["service_record"]["service_type"] == "Engine service" and done["service_record"]["engine_hours"] == 205
    assert (await client.post(f"{base}/service-reminders/{rem['id']}/complete", headers=h)).status_code == 409
    active = (await client.get(f"{base}/service-reminders", headers=h)).json()
    assert [a["id"] for a in active] == [done["next"]["id"]]
    assert len((await client.get(f"{base}/service-reminders", params={"status": "all"}, headers=h)).json()) == 2

    one_off = (
        await client.post(f"{base}/service-reminders", json={"title": "Antifoul", "due_on": "2020-01-01"}, headers=h)
    ).json()
    assert one_off["is_due"] is True
    done = (
        await client.post(
            f"{base}/service-reminders/{one_off['id']}/complete", json={"record_service": False}, headers=h
        )
    ).json()
    assert done["next"] is None and done["service_record"] is None
    r = await client.patch(
        f"{base}/service-reminders/{done['next'] or active[0]['id']}", json={"status": "dismissed"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "dismissed"
    assert (
        await client.patch(
            f"{base}/service-reminders/{active[0]['id']}", json={"due_on": None, "due_engine_hours": None}, headers=h
        )
    ).status_code == 422
    assert (
        await client.delete(f"{base}/service-reminders/{active[0]['id']}", headers=other_customer.headers)
    ).status_code == 404
    assert (await client.delete(f"{base}/service-reminders/{active[0]['id']}", headers=h)).status_code == 204
    assert (await client.delete(f"{base}/service-records/{rec['id']}", headers=h)).status_code == 204
    assert date.fromisoformat("2027-02-28")


async def test_boat_db_public_read_and_admin_curation(client, customer, admin, categories):  # noqa: F811
    h = admin.headers
    db = f"{API}/boat-db"
    cats = (await client.get(f"{db}/equipment-categories")).json()
    assert {"engine", "toilet", "inverter", "steering_hydraulic", "sail_rig"} <= {c["slug"] for c in cats}

    body = {"name": "Testcraft", "country": "NZ", "mic_codes": ["z9q"], "is_synthetic": True, "source": "fixture"}
    assert (await client.post(f"{db}/manufacturers", json=body, headers=customer.headers)).status_code == 403
    m = (await client.post(f"{db}/manufacturers", json=body, headers=h)).json()
    assert m["mic_codes"] == ["Z9Q"]
    assert (await client.post(f"{db}/manufacturers", json=body, headers=h)).status_code == 409
    assert (
        await client.post(f"{db}/manufacturers", json={**body, "name": "X", "mic_codes": ["TOOLONG"]}, headers=h)
    ).status_code == 422
    model = (
        await client.post(
            f"{db}/manufacturers/{m['id']}/models",
            json={"name": "T600", "propulsion_type": "outboard", "length_ft": 19.5, "is_synthetic": True},
            headers=h,
        )
    ).json()
    year = (await client.post(f"{db}/models/{model['id']}/years", json={"year": 2022}, headers=h)).json()
    assert (await client.post(f"{db}/models/{model['id']}/years", json={"year": 2022}, headers=h)).status_code == 409
    oem_body = {
        "category": "engine",
        "equipment_make": "Yamaha",
        "equipment_model": "F150",
        "data_source": "crowdsourced_unverified",
    }
    oem = (await client.post(f"{db}/model-years/{year['id']}/equipment", json=oem_body, headers=h)).json()
    assert oem["confidence_score"] == 0.3 and oem["reliable"] is False and oem["is_synthetic"] is False
    r = await client.post(
        f"{db}/model-years/{year['id']}/equipment", json={**oem_body, "verification_status": "verified"}, headers=h
    )
    assert r.status_code == 422 and r.json()["code"] == "confidence_too_low"
    r = await client.patch(
        f"{db}/oem-equipment/{oem['id']}",
        json={"data_source": "manufacturer", "confidence_score": 1.0, "verification_status": "verified"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["reliable"] is True

    makers = (await client.get(f"{db}/manufacturers", params={"q": "test"})).json()
    assert [x["name"] for x in makers] == ["Testcraft"] and makers[0]["model_count"] == 1
    detail = (await client.get(f"{db}/manufacturers/{m['id']}")).json()
    assert detail["models"][0]["years"] == [2022]
    assert (await client.get(f"{db}/models/{model['id']}/years")).json()[0]["equipment_count"] == 1
    my = (await client.get(f"{db}/model-years/{year['id']}")).json()
    assert my["manufacturer"]["name"] == "Testcraft" and my["equipment"][0]["is_synthetic"] is True  # synthetic parent
    lookup = await client.get(f"{db}/lookup", params={"make": "TESTCRAFT", "model": "t-600", "year": 2022})
    assert lookup.status_code == 200 and lookup.json()["id"] == year["id"]
    assert (await client.get(f"{db}/lookup", params={"make": "Nope", "model": "x", "year": 2022})).status_code == 404

    assert (await client.patch(f"{db}/manufacturers/{m['id']}", json={"website": "https://t.test"}, headers=h)).json()[
        "website"
    ] == "https://t.test"
    assert (await client.delete(f"{db}/oem-equipment/{oem['id']}", headers=h)).status_code == 204
    assert (await client.delete(f"{db}/manufacturers/{m['id']}", headers=h)).status_code == 204
    assert (await client.get(f"{db}/models/{model['id']}")).status_code == 404
    actions = await audit_actions()
    assert {
        "boat_db.manufacturer_create",
        "boat_db.model_create",
        "boat_db.model_year_create",
        "boat_db.oem_create",
        "boat_db.oem_update",
        "boat_db.oem_delete",
        "boat_db.manufacturer_delete",
    } <= set(actions)
