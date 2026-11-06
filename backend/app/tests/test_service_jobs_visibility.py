"""What a contractor reads of a job's content (``access.visibility``): live updates on/off and
the organization boundary after a reassignment; neutral invitation/inbox labels.

* live updates off (the default): job content — summary, photos/documents, observations,
  measurements, preparation items — only as of the latest published brief (plus what the
  organization itself recorded); collaboration channels stay live;
* live updates on: the granted sections live;
* reassignment: the next organization does not see the previous one's records (scope
  prices/decisions, notes, uploads, evidence requests); measurements stay as evidence
  without that organization's member identities.
"""

from __future__ import annotations

import uuid

from sqlalchemy import update

from app.database import async_session
from app.models.service_jobs import EvidenceAsset, JobAssignment
from app.services.service_jobs import storage
from app.tests.service_jobs_support import DEFAULT_SECTIONS, world  # noqa: F401
from app.tests.test_service_prep_support import job_url, make_asset, measure, store  # noqa: F401

API = "/api/v1"


def key() -> str:
    return f"k-{uuid.uuid4().hex}"


async def set_live_updates(assignment_id, live: bool) -> None:
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == assignment_id).values(live_updates=live))
        await s.commit()


async def contractor_asset(job, uploader, org_id, data: bytes = b"contractor photo") -> uuid.UUID:
    key_ = storage.new_key("derived")
    storage.get_store().put(key_, data, "image/jpeg")
    async with async_session() as s:
        asset = EvidenceAsset(
            owner_id=job.owner_id,
            job_id=job.id,
            uploaded_by=uploader.id,
            uploader_organization_id=org_id,
            purpose="job_photo",
            max_bytes=1024 * 1024,
            storage_key=storage.new_key("original"),
            derivative_key=key_,
            detected_type="image/jpeg",
            size_bytes=len(data),
            status="available",
        )
        s.add(asset)
        await s.commit()
        return asset.id


async def get_job(client, actor, job_id) -> dict:
    r = await client.get(f"{API}/service-jobs/{job_id}", headers=actor.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def ids(client, actor, job_id, suffix: str) -> set[str]:
    r = await client.get(job_url(job_id, suffix), headers=actor.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = body["items"] if isinstance(body, dict) else body
    return {row["id"] for row in rows}


async def publish_brief(client, w) -> dict:
    r = await client.post(job_url(w.job.id, "/briefs/preview"), headers=w.owner.headers)
    assert r.status_code == 201, r.text
    brief = r.json()
    r = await client.post(
        job_url(w.job.id, f"/briefs/{brief['id']}/publish"),
        json={"content_digest": brief["content_digest"]},
        headers=w.owner.headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def edit_job(client, w, **changes) -> None:
    job = await get_job(client, w.owner, w.job.id)
    r = await client.patch(
        f"{API}/service-jobs/{w.job.id}",
        json={"expected_version": job["version"], **changes},
        headers=w.owner.headers,
    )
    assert r.status_code == 200, r.text


OWNER_TAPE = {"dimension": "hose_external_diameter", "component": "hose", "value_text": "32", "unit": "mm"}


# ---------------------------------------------------------------------- live updates off (default)
async def test_live_updates_off_reads_only_the_published_brief(client, world, store):  # noqa: F811
    """Review finding (p2): ``live_updates`` was stored but never enforced — the contractor
    read the owner's later edits live although the preview promised the published brief."""
    await set_live_updates(world.assignment_id, False)
    photo = await make_asset(world.job, b"first photo")
    m1 = await measure(client, world.owner, world.job.id, **OWNER_TAPE, method="owner_tape")
    r = await client.post(
        f"{API}/service-jobs/{world.job.id}/evidence-requests",
        json={"category": "label", "prompt": "Photo of the pump label", "reason": "Model and size"},
        headers=world.owner.headers,
    )
    owner_request = r.json()["id"]

    # Nothing published yet: the header only, an explicit state, no job content.
    job = await get_job(client, world.tech, world.job.id)
    assert job["snapshot_state"] == "no_brief_published" and job["snapshot_brief_id"] is None
    assert job["title"] and job["status"] and job["version"]
    assert job["issue_description"] is None and job["vessel_context"] is None and job["evidence"] is None
    for suffix in ("/assets", "/observations", "/measurements", "/preparation-items"):
        assert await ids(client, world.tech, world.job.id, suffix) == set(), suffix
    r = await client.post(f"{API}/service-assets/{photo}/download-url", headers=world.tech.headers)
    assert r.status_code == 403 and r.json()["code"] == "live_updates_not_shared"
    r = await client.post(
        job_url(world.job.id, f"/measurements/{m1['id']}/confirm"),
        json={"method": "contractor_site"},
        headers=world.tech.headers,
    )
    assert r.status_code == 403 and r.json()["code"] == "live_updates_not_shared"
    # Collaboration channels are unaffected.
    assert owner_request in await ids(client, world.tech, world.job.id, "/evidence-requests")

    brief = await publish_brief(client, world)
    original = (await get_job(client, world.owner, world.job.id))["issue_description"]
    # The owner changes things after sharing.
    await edit_job(client, world, issue_description="LATER CHANGE after sharing")
    later_photo = await make_asset(world.job, b"later photo")
    m2 = await measure(client, world.owner, world.job.id, **{**OWNER_TAPE, "value_text": "33"}, method="owner_tape")

    job = await get_job(client, world.tech, world.job.id)
    assert job["snapshot_state"] == "brief" and job["snapshot_brief_id"] == brief["id"]
    assert job["snapshot_published_at"]
    assert job["issue_description"] == original != "LATER CHANGE after sharing"
    assert job["evidence"]["available_asset_count"] == 1
    assert job["evidence"]["outstanding"][0]["id"] == owner_request
    assert await ids(client, world.tech, world.job.id, "/assets") == {str(photo)}
    measurements = await ids(client, world.tech, world.job.id, "/measurements")
    assert str(m1["id"]) in measurements and str(m2["id"]) not in measurements
    r = await client.post(f"{API}/service-assets/{later_photo}/download-url", headers=world.tech.headers)
    assert r.status_code == 403 and r.json()["code"] == "live_updates_not_shared"
    assert (
        await client.post(f"{API}/service-assets/{photo}/download-url", headers=world.tech.headers)
    ).status_code == 200
    r = await client.post(
        job_url(world.job.id, f"/measurements/{m2['id']}/confirm"),
        json={"method": "contractor_site"},
        headers=world.tech.headers,
    )
    assert r.status_code == 403 and r.json()["code"] == "live_updates_not_shared"
    # What the contractor records themselves stays visible to them.
    own = await measure(
        client, world.tech, world.job.id, **{**OWNER_TAPE, "component": "far end"}, method="contractor_site"
    )
    assert str(own["id"]) in await ids(client, world.tech, world.job.id, "/measurements")
    # The owner still sees everything live.
    assert (await get_job(client, world.owner, world.job.id))["issue_description"] == "LATER CHANGE after sharing"
    assert (await get_job(client, world.owner, world.job.id))["snapshot_state"] == "live"

    # A new brief brings the contractor up to date.
    await publish_brief(client, world)
    job = await get_job(client, world.tech, world.job.id)
    assert job["issue_description"] == "LATER CHANGE after sharing"
    assert await ids(client, world.tech, world.job.id, "/assets") == {str(photo), str(later_photo)}


async def test_live_updates_on_reads_the_granted_sections_live(client, world, store):  # noqa: F811
    await set_live_updates(world.assignment_id, True)
    await edit_job(client, world, issue_description="Changed after sharing")
    photo = await make_asset(world.job, b"live photo")
    job = await get_job(client, world.tech, world.job.id)
    assert job["snapshot_state"] == "live" and job["issue_description"] == "Changed after sharing"
    assert await ids(client, world.tech, world.job.id, "/assets") == {str(photo)}
    assert (
        await client.post(f"{API}/service-assets/{photo}/download-url", headers=world.tech.headers)
    ).status_code == 200


async def test_sharing_preview_describes_what_each_setting_really_shows(client, world):  # noqa: F811
    url = f"{API}/service-jobs/{world.job.id}/assignments/preview"
    off = await client.post(
        url, json={"organization_id": str(world.org_b), "sections": DEFAULT_SECTIONS}, headers=world.owner.headers
    )
    on = await client.post(
        url,
        json={"organization_id": str(world.org_b), "sections": DEFAULT_SECTIONS, "live_updates": True},
        headers=world.owner.headers,
    )
    assert off.status_code == on.status_code == 200
    off_note, on_note = off.json()["live_updates_note"], on.json()["live_updates_note"]
    assert "as of the brief you publish" in off_note and "Until you publish a brief" in off_note
    assert "Evidence requests" in off_note and "stay up to date" in off_note
    assert "including changes you make later" in on_note


# ---------------------------------------------------------------------- organization boundary
async def test_reassigned_organization_does_not_see_the_previous_organizations_records(client, world, store):  # noqa: F811
    owner_photo = await make_asset(world.job, b"owner photo")
    a_photo = await contractor_asset(world.job, world.tech, world.org_a)
    r = await client.post(
        job_url(world.job.id, "/observations"),
        json={"text": "Org A private note: quote 4,200"},
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    a_note = r.json()["id"]
    r = await client.post(
        job_url(world.job.id, "/observations"), json={"text": "Owner note on the leak"}, headers=world.owner.headers
    )
    owner_note = r.json()["id"]
    r = await client.post(
        f"{API}/service-jobs/{world.job.id}/evidence-requests",
        json={"category": "route", "prompt": "Org A wants the hose route", "reason": "Org A routing"},
        headers=world.tech.headers,
    )
    a_request = r.json()["id"]
    a_measure = await measure(client, world.tech, world.job.id, **OWNER_TAPE, method="contractor_site", notes="Tama")
    owner_measure = await measure(
        client, world.owner, world.job.id, **{**OWNER_TAPE, "component": "pump end"}, method="owner_caliper"
    )
    r = await client.post(
        job_url(world.job.id, "/scopes"),
        json={
            "summary": "Org A scope",
            "estimate_lines": [{"description": "Replace hose", "kind": "parts", "amount_minor": 420000}],
            "currency": "NZD",
        },
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    a_scope = r.json()
    r = await client.post(
        job_url(world.job.id, f"/scopes/{a_scope['id']}/decision"),
        json={"decision": "accepted", "revision_digest": a_scope["content_digest"]},
        headers={**world.owner.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.text

    r = await client.post(
        f"{API}/service-jobs/{world.job.id}/assignments/{world.assignment_id}/reassign",
        json={"organization_id": str(world.org_b), "sections": DEFAULT_SECTIONS, "live_updates": True},
        headers={**world.owner.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"{API}/contractors/assignments/{r.json()['id']}/accept",
        json={"member_user_ids": [str(world.other_tech.id)]},
        headers=world.other_tech.headers,
    )
    assert r.status_code == 200, r.text
    b = world.other_tech

    # The owner's evidence stays; org A's own records do not.
    assert await ids(client, b, world.job.id, "/assets") == {str(owner_photo)}
    assert (await client.get(f"{API}/service-assets/{a_photo}", headers=b.headers)).status_code == 404
    assert await ids(client, b, world.job.id, "/observations") == {owner_note}
    assert a_request not in await ids(client, b, world.job.id, "/evidence-requests")
    r = await client.get(f"{API}/service-jobs/{world.job.id}/evidence-requests/{a_request}", headers=b.headers)
    assert r.status_code == 404
    r = await client.get(job_url(world.job.id, "/scopes"), headers=b.headers)
    assert r.status_code == 200 and r.json() == [] and "420000" not in r.text
    assert (await client.get(job_url(world.job.id, f"/scopes/{a_scope['id']}"), headers=b.headers)).status_code == 404
    # Measurements stay as evidence, without org A's member identities.
    r = await client.get(job_url(world.job.id, "/measurements"), headers=b.headers)
    by_id = {m["id"]: m for m in r.json()}
    assert set(by_id) == {a_measure["id"], owner_measure["id"]}
    foreign = by_id[a_measure["id"]]
    assert foreign["recorded_by"] is None and foreign["notes"] is None and foreign["recorded_by_other_organization"]
    assert foreign["provenance"]["recorded_by"] is None and foreign["provenance"]["other_organization"] is True
    assert foreign["confirmation"]["confirmed_by"] is None and foreign["state"] == "contractor_confirmed"
    assert str(world.tech.id) not in r.text
    assert by_id[owner_measure["id"]]["recorded_by"] == str(world.owner.id)
    # Org B proposes on its own chain (it never saw org A's revision).
    r = await client.post(
        job_url(world.job.id, "/scopes"),
        json={
            "summary": "Org B scope",
            "estimate_lines": [{"description": "Hose", "amount_minor": 30000}],
            "currency": "NZD",
        },
        headers=b.headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["supersedes_id"] is None and r.json()["is_change"] is False
    assert [s["summary"] for s in (await client.get(job_url(world.job.id, "/scopes"), headers=b.headers)).json()] == [
        "Org B scope"
    ]
    # The brief built for org B holds the same boundary.
    brief = await publish_brief(client, world)
    r = await client.get(job_url(world.job.id, f"/briefs/{brief['id']}"), headers=b.headers)
    assert r.status_code == 200
    content = r.json()["content"]
    assert {a["id"] for a in content["evidence"]["assets"]} == {str(owner_photo)}
    assert {o["id"] for o in content["evidence"]["observations"]} == {owner_note}
    assert a_request not in {q["id"] for q in content["evidence"]["requests"]}
    assert [s["summary"] for s in content["scope"]["history"]] == ["Org B scope"]
    assert "Org A" not in r.text and "4,200" not in r.text and str(world.tech.id) not in r.text
    # The owner still sees everything.
    assert len((await client.get(job_url(world.job.id, "/scopes"), headers=world.owner.headers)).json()) == 2
    assert a_note in await ids(client, world.owner, world.job.id, "/observations")


# ---------------------------------------------------------------------- invitation / inbox labels
async def test_invitation_and_inbox_show_the_title_only_with_the_summary_section(client, world):  # noqa: F811
    r = await client.post(
        f"{API}/service-jobs/{world.job.id}/assignments/{world.assignment_id}/reassign",
        json={"organization_id": str(world.org_b), "sections": ["measurements"]},
        headers={**world.owner.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.text
    assignment = r.json()["id"]
    r = await client.get(f"{API}/contractors/assignments/{assignment}", headers=world.other_tech.headers)
    assert r.status_code == 200
    invite = r.json()
    assert invite["job_title"] == "Service job" and invite["vessel_make"] is None and invite["vessel_model"] is None
    inbox = (await client.get(f"{API}/contractors/me/jobs", headers=world.other_tech.headers)).json()
    assert [i["job_title"] for i in inbox["invitations"]] == ["Service job"]
    assert world.job.title not in str(inbox)
    r = await client.post(
        f"{API}/contractors/assignments/{assignment}/accept",
        json={"member_user_ids": [str(world.other_tech.id)]},
        headers=world.other_tech.headers,
    )
    assert r.status_code == 200 and r.json()["job_title"] == "Service job"
    version = r.json()["version"]
    inbox = (await client.get(f"{API}/contractors/me/jobs", headers=world.other_tech.headers)).json()
    assert [i["title"] for i in inbox["assigned"]] == ["Service job"]
    inbox = (await client.get(f"{API}/contractors/me/jobs", headers=world.tech.headers)).json()
    assert inbox["assigned"] == []  # org A was revoked by the reassignment
    # With the summary section offered, the title is shown.
    r = await client.patch(
        f"{API}/service-jobs/{world.job.id}/assignments/{assignment}",
        json={"expected_version": version, "sections": ["summary", "measurements"]},
        headers=world.owner.headers,
    )
    assert r.status_code == 200, r.text
    inbox = (await client.get(f"{API}/contractors/me/jobs", headers=world.other_tech.headers)).json()
    assert [i["title"] for i in inbox["assigned"]] == [world.job.title]
