"""Measurements: typed dimensions, provenance, revisions and confirmation (SJ-04, SJ-09)."""

from __future__ import annotations

from sqlalchemy import select

from app.database import async_session
from app.models.ops import AuditLog
from app.models.service_jobs import Measurement, ServiceJob
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_prep_support import analyse, job_url, make_asset, measure, store, synthetic  # noqa: F401


async def _obs_with_text(client, actor, job_id, text):
    r = await client.get(job_url(job_id, "/observations"), headers=actor.headers)
    return next(o for o in r.json() if o["extracted_text"] == text)


async def test_sj04_marking_owner_od_and_grade_stay_distinct(client, world, store):  # noqa: F811
    """'25 mm ID' marking, owner-measured '32 mm OD' and '316' on a clamp are three records;
    316 never becomes a diameter; the ID is never recorded as the OD."""
    job = world.job
    await make_asset(job, synthetic("hose-marking-25mm-id"))
    await make_asset(job, synthetic("clamp-marking-316"))
    await analyse(client, world.owner, job.id)
    hose = await _obs_with_text(client, world.owner, job.id, "25 mm ID")
    grade = await _obs_with_text(client, world.owner, job.id, "316")
    assert hose["state"] == "model_suggested" and hose["is_measurement"] is False
    assert hose["assertion"] == 'Image marking text appears to read "25 mm ID"'
    # Analysis alone produced no measurements.
    r = await client.get(job_url(job.id, "/measurements"), headers=world.owner.headers)
    assert r.json() == []

    # 316 cannot become a diameter, with or without a unit supplied by the client.
    for dim in ("hose_internal_diameter", "hose_external_diameter", "clamp_range"):
        bad = await measure(
            client,
            world.owner,
            job.id,
            expect=422,
            dimension=dim,
            component="clamp",
            value_text="316" if dim != "clamp_range" else "300-316",
            unit="mm",
            method="marking_read",
            source_observation_id=grade["id"],
        )
        assert bad["code"] == "marking_has_no_unit"
    # The ID marking cannot be recorded as the outside diameter.
    bad = await measure(
        client,
        world.owner,
        job.id,
        expect=422,
        dimension="hose_external_diameter",
        component="pump outlet hose",
        value_text="25",
        unit="mm",
        method="marking_read",
        source_observation_id=hose["id"],
    )
    assert bad["code"] == "marking_semantics_mismatch"

    id_m = await measure(
        client,
        world.owner,
        job.id,
        dimension="hose_internal_diameter",
        component="pump outlet hose",
        value_text="25",
        unit="mm",
        method="marking_read",
        source_observation_id=hose["id"],
    )
    od_m = await measure(
        client,
        world.owner,
        job.id,
        dimension="hose_external_diameter",
        component="pump outlet hose",
        value_text="32",
        unit="mm",
        method="owner_caliper",
        tool="vernier caliper",
        precision="±0.5 mm",
    )
    assert id_m["state"] == "owner_declared" and id_m["provenance"]["label"] == "Owner declared (read from a marking)"
    assert od_m["state"] == "owner_measured" and od_m["precision"] == "±0.5 mm"
    assert id_m["normalized_min_mm"] == "25" and od_m["normalized_min_mm"] == "32"
    assert id_m["precision"] == "as written: nearest 1 mm"
    rows = (await client.get(job_url(job.id, "/measurements"), headers=world.owner.headers)).json()
    assert sorted(m["dimension"] for m in rows) == ["hose_external_diameter", "hose_internal_diameter"]
    assert all(m["value_text"] != "316" for m in rows)
    obs = (await client.get(job_url(job.id, "/observations"), headers=world.owner.headers)).json()
    assert any(o["extracted_text"] == "316" and o["state"] == "model_suggested" for o in obs)


async def test_sj04_unscaled_photo_never_yields_measured_or_confirmed(client, world, store):  # noqa: F811
    asset = await make_asset(world.job, b"some photo")
    body = {
        "dimension": "hose_external_diameter",
        "component": "hose",
        "value_text": "30",
        "unit": "mm",
        "method": "image_estimate_with_reference",
        "source_asset_id": str(asset),
    }
    missing = await measure(client, world.owner, world.job.id, expect=422, **body)
    assert missing["code"] == "estimate_needs_reference"
    est = await measure(
        client, world.owner, world.job.id, **body, reference="credit card (85.6 mm) beside hose", precision="±5 mm"
    )
    assert est["state"] == "unknown" and est["provenance"]["badge"] == "unknown"
    r = await client.post(
        job_url(world.job.id, f"/measurements/{est['id']}/confirm"),
        json={"method": "contractor_site"},
        headers=world.tech.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "estimate_cannot_be_confirmed"
    # An owner cannot claim contractor methods, nor a contractor owner methods.
    for actor, method in ((world.owner, "contractor_site"), (world.tech, "owner_tape")):
        bad = await measure(
            client, actor, world.job.id, expect=422, **{**body, "method": method, "source_asset_id": None}
        )
        assert bad["code"] == "method_not_allowed"


async def test_sj04_typed_dimensions_and_units(client, world):  # noqa: F811
    j = world.job.id
    clamp = await measure(
        client,
        world.owner,
        j,
        dimension="clamp_range",
        component="clamp",
        value_text="20-32",
        unit="mm",
        method="owner_tape",
    )
    assert (clamp["value_min"], clamp["value_max"]) == ("20", "32")
    single = await measure(
        client,
        world.owner,
        j,
        expect=422,
        dimension="clamp_range",
        component="clamp",
        value_text="25",
        unit="mm",
        method="owner_tape",
    )
    assert single["code"] == "clamp_range_needs_range"
    inch = await measure(
        client,
        world.owner,
        j,
        dimension="fitting_outside_diameter",
        component="barb",
        value_text='1 1/4"',
        method="owner_tape",
    )
    assert inch["unit"] == "in" and inch["value_text"] == '1 1/4"' and inch["normalized_min_mm"] == "31.75"
    assert inch["resolution_mm"] == "6.35"
    route = await measure(
        client,
        world.owner,
        j,
        dimension="route_length",
        component="visible hose run",
        value_text="0.8",
        unit="m",
        method="owner_tape",
    )
    assert route["normalized_min_mm"] == "800" and route["precision"] == "as written: nearest 0.1 m"
    thread = await measure(
        client,
        world.tech,
        j,
        dimension="thread",
        component="pump outlet",
        value_text="1/2 NPT",
        method="contractor_site",
    )
    assert thread["thread"] == {"standard": "NPT", "size": "1/2", "pitch": None}
    assert thread["state"] == "contractor_confirmed"
    assert thread["confirmation"]["confirmed_by"] == str(world.tech.id)
    no_unit = await measure(
        client,
        world.owner,
        j,
        expect=422,
        dimension="hose_internal_diameter",
        component="h",
        value_text="25",
        method="owner_tape",
    )
    assert no_unit["code"] == "invalid_length"


async def test_sj09_revision_is_a_new_row_and_confirmation_records_who_what_when(client, world):  # noqa: F811
    j = world.job.id
    od = await measure(
        client,
        world.owner,
        j,
        dimension="hose_external_diameter",
        component="hose",
        value_text="32",
        unit="mm",
        method="owner_tape",
    )
    async with async_session() as s:
        rev_before = (await s.get(ServiceJob, j)).evidence_revision
    conf = await client.post(
        job_url(j, f"/measurements/{od['id']}/confirm"),
        json={"method": "contractor_site", "note": "checked on site"},
        headers=world.tech.headers,
    )
    assert conf.status_code == 200, conf.text
    c = conf.json()
    assert c["state"] == "contractor_confirmed" and c["confirmation"]["method"] == "contractor_site"
    assert c["provenance"]["recorded_by_role"] == "owner"
    async with async_session() as s:
        log = (await s.execute(select(AuditLog).where(AuditLog.action == "service_measurement.confirmed"))).scalar_one()
        assert log.actor_id == world.tech.id and log.detail["value_text"] == "32"
        assert log.detail["measurement_revision"] == od["id"]
        assert (await s.get(ServiceJob, j)).evidence_revision == rev_before + 1
    # Owner cannot "confirm".
    r = await client.post(
        job_url(j, f"/measurements/{od['id']}/confirm"), json={"method": "contractor_site"}, headers=world.owner.headers
    )
    assert r.status_code == 403 and r.json()["code"] == "contractor_only"
    # Owner corrects the value: a new revision; the confirmed original is kept, superseded.
    r = await client.post(
        job_url(j, f"/measurements/{od['id']}/revise"),
        json={
            "dimension": "hose_external_diameter",
            "component": "hose",
            "value_text": "33",
            "unit": "mm",
            "method": "owner_caliper",
        },
        headers=world.owner.headers,
    )
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["supersedes_id"] == od["id"] and new["state"] == "owner_measured" and new["confirmation"] is None
    rows = {m["id"]: m for m in (await client.get(job_url(j, "/measurements"), headers=world.owner.headers)).json()}
    assert rows[od["id"]]["state"] == "superseded" and rows[od["id"]]["value_text"] == "32"
    assert rows[od["id"]]["superseded_by_id"] == new["id"]
    async with async_session() as s:
        stored = await s.get(Measurement, od["id"])
        assert stored.confirmed_by == world.tech.id  # history preserved, not overwritten
    # The superseded revision can no longer be confirmed or revised.
    for path, body in (
        ("confirm", {"method": "contractor_site"}),
        (
            "revise",
            {
                "dimension": "hose_external_diameter",
                "component": "hose",
                "value_text": "34",
                "unit": "mm",
                "method": "contractor_site",
            },
        ),
    ):
        r = await client.post(job_url(j, f"/measurements/{od['id']}/{path}"), json=body, headers=world.tech.headers)
        assert r.status_code == 409 and r.json()["code"] == "measurement_superseded"
    current = (await client.get(job_url(j, "/measurements?include_inactive=false"), headers=world.owner.headers)).json()
    assert [m["id"] for m in current] == [new["id"]]
    # Rejecting is recorded and keeps the row.
    r = await client.post(
        job_url(j, f"/measurements/{new['id']}/reject"), json={"note": "wrong hose"}, headers=world.owner.headers
    )
    assert r.status_code == 200 and r.json()["state"] == "rejected"


async def test_measurement_source_asset_must_be_this_jobs_available_asset(client, world, store):  # noqa: F811
    other_asset = await make_asset(world.other_job, b"other job photo")
    pending = await make_asset(world.job, b"pending photo", status="quarantined")
    base = {
        "dimension": "hose_external_diameter",
        "component": "hose",
        "value_text": "32",
        "unit": "mm",
        "method": "owner_tape",
    }
    r = await client.post(
        job_url(world.job.id, "/measurements"),
        json={**base, "source_asset_id": str(other_asset)},
        headers=world.owner.headers,
    )
    assert r.status_code == 404
    r = await client.post(
        job_url(world.job.id, "/measurements"),
        json={**base, "source_asset_id": str(pending)},
        headers=world.owner.headers,
    )
    assert r.status_code == 422 and r.json()["code"] == "asset_not_available"
