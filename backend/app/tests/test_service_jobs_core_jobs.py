"""A2 jobs: create from a vessel, resume, filtered representation, edits, transitions,
access details (general/restricted, masking + audit), delete/archive, concurrency (SJ-01, SJ-06, SJ-21)."""

from __future__ import annotations

import asyncio
import json

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.database import async_session
from app.main import app
from app.models.ops import AuditLog
from app.models.service_jobs import JobAssignment, JobAssignmentMember, ServiceJob
from app.tests.conftest import create_actor, create_vessel
from app.tests.service_jobs_support import world  # noqa: F401

API = "/api/v1/service-jobs"
RESTRICTED_VALUES = ("4512#", "+64 21 000 0000", "F-27")


def _no_restricted(payload) -> None:
    text = json.dumps(payload)
    for v in RESTRICTED_VALUES:
        assert v not in text, v
    assert "gate_code" not in text


async def _create(client, owner, vessel_id, **extra):
    body = {
        "vessel_id": str(vessel_id),
        "entry_point": "vessel",
        "title": "Leak under the galley sink",
        "issue_description": "Water under the sink when the pump runs.",
        "affected_system": "plumbing",
        "affected_equipment": "freshwater pump",
        **extra,
    }
    r = await client.post(f"{API}/", json=body, headers=owner.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_owner_creates_job_from_vessel_with_snapshot_and_corrects_it(client, world):  # noqa: F811
    job = await _create(client, world.owner, world.vessel_id, occurs_when="Whenever the pump runs")
    assert job["status"] == "draft" and job["version"] == 1 and job["evidence_revision"] == 0
    ctx = job["vessel_context"]
    assert ctx["vessel"]["make"] == "Stabicraft" and ctx["engine"] == {"make": "Yamaha", "model": "F150", "year": 2022}
    assert ctx["owner_confirmed"] is False and "hin" not in json.dumps(ctx)
    assert job["viewer"]["role"] == "owner" and job["evidence"]["outstanding"] == [] and job["gaps"] == []

    # Someone else's vessel or an unknown vessel: 404.
    r = await client.post(
        f"{API}/", json={"vessel_id": str(world.vessel_id), "title": "x"}, headers=world.other_owner.headers
    )
    assert r.status_code == 404
    # Unknown fields are rejected (no smuggled owner/status).
    r = await client.post(
        f"{API}/",
        json={"vessel_id": str(world.vessel_id), "title": "x", "status": "scheduled"},
        headers=world.owner.headers,
    )
    assert r.status_code == 422

    r = await client.put(
        f"{API}/{job['id']}/vessel-context",
        json={"expected_version": 1, "engine": {"model": "F150XB"}, "note": "Engine was replaced in 2024"},
        headers=world.owner.headers,
    )
    assert r.status_code == 200, r.text
    corrected = r.json()
    assert corrected["vessel_context"]["engine"]["model"] == "F150XB"
    assert corrected["vessel_context"]["engine"]["make"] == "Yamaha"
    assert corrected["vessel_context"]["owner_confirmed"] is True
    assert corrected["vessel_context"]["corrections"][-1]["fields"] == ["engine.model"]
    assert corrected["version"] == 2 and corrected["evidence_revision"] == 1
    # The vessel record itself is untouched.
    v = (await client.get(f"/api/v1/vessels/{world.vessel_id}", headers=world.owner.headers)).json()
    assert v["engine_model"] == "F150"


async def test_list_own_jobs_only(client, world):  # noqa: F811
    await _create(client, world.owner, world.vessel_id)
    mine = (await client.get(f"{API}/", headers=world.owner.headers)).json()
    assert {j["id"] for j in mine} >= {str(world.job.id)} and len(mine) == 2
    assert all(j["title"] != "Other owner's job" for j in mine)
    live = next(j for j in mine if j["id"] == str(world.job.id))
    assert live["assignment_status"] == "accepted"
    # Contractors have no owner job list.
    assert (await client.get(f"{API}/", headers=world.tech.headers)).json() == []
    page = (await client.get(f"{API}/?limit=1&offset=1", headers=world.owner.headers)).json()
    assert len(page) == 1


async def test_get_job_is_filtered_per_actor(client, world):  # noqa: F811
    url = f"{API}/{world.job.id}"
    owner = (await client.get(url, headers=world.owner.headers)).json()
    assert owner["viewer"]["role"] == "owner" and owner["issue_description"]
    assert owner["assignment"]["organization"]["name"] == "Harbour Marine Services"
    _no_restricted(owner)

    tech = (await client.get(url, headers=world.tech.headers)).json()
    assert tech["viewer"]["role"] == "contractor"
    assert "access_restricted" not in tech["viewer"]["sections"] and tech["viewer"]["restricted_access"] is False
    assert tech["issue_description"] and tech["evidence"] is not None
    _no_restricted(tech)

    # Only "summary" shared → no evidence block.
    async with async_session() as s:
        await s.execute(
            update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(sections=["summary"])
        )
        await s.commit()
    tech = (await client.get(url, headers=world.tech.headers)).json()
    assert tech["evidence"] is None and tech["gaps"] is None
    # Not even summary → identity only.
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(sections=["scope"]))
        await s.commit()
    tech = (await client.get(url, headers=world.tech.headers)).json()
    assert tech["issue_description"] is None and tech["vessel_context"] is None and tech["title"]

    # IDOR: unassigned colleague, org admin, other org, other owner, platform admin → 404.
    platform_admin = await create_actor("admin")
    for outsider in (world.tech2, world.org_admin, world.other_tech, world.other_owner, platform_admin):
        assert (await client.get(url, headers=outsider.headers)).status_code == 404
    assert (await client.get(f"{API}/{world.other_job.id}", headers=world.owner.headers)).status_code == 404


async def test_patch_needs_owner_and_current_version(client, world):  # noqa: F811
    url = f"{API}/{world.job.id}"
    r = await client.patch(url, json={"expected_version": 1, "title": "Pump leak"}, headers=world.tech.headers)
    assert r.status_code == 404  # contractors cannot edit (owner-only resolves as not found)
    r = await client.patch(url, json={"expected_version": 1, "title": "Pump leak"}, headers=world.other_owner.headers)
    assert r.status_code == 404
    r = await client.patch(url, json={"title": "Pump leak"}, headers=world.owner.headers)
    assert r.status_code == 422  # expected_version required
    r = await client.patch(url, json={"expected_version": 1, "urgency": "soon"}, headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["evidence_revision"] == 0
    r = await client.patch(url, json={"expected_version": 1, "title": "Stale"}, headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict" and r.json()["current_version"] == 2
    r = await client.patch(
        url, json={"expected_version": 2, "affected_equipment": "pressure pump"}, headers=world.owner.headers
    )
    assert r.json()["evidence_revision"] == 1  # equipment context changed


async def test_competing_edits_one_wins(world):  # noqa: F811
    """SJ-21: two clients edit the same version concurrently → one 200, one 409."""
    url = f"{API}/{world.job.id}"
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as a,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as b,
    ):
        results = await asyncio.gather(
            a.patch(url, json={"expected_version": 1, "title": "A"}, headers=world.owner.headers),
            b.patch(url, json={"expected_version": 1, "title": "B"}, headers=world.owner.headers),
        )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        assert job.version == 2 and job.title in ("A", "B")


async def test_transitions_owner_and_contractor(client, world):  # noqa: F811
    vessel = await create_vessel(world.owner.id, nickname="Second")
    job = await _create(client, world.owner, vessel.id)
    url = f"{API}/{job['id']}/transition"

    async def go(actor, to, version):
        return await client.post(url, json={"expected_version": version, "to": to}, headers=actor.headers)

    assert (await go(world.owner, "preparation_ready", 1)).status_code == 409  # not from draft
    r = await go(world.owner, "evidence_collection", 1)
    assert r.status_code == 200 and r.json()["status"] == "evidence_collection"
    r = await go(world.owner, "contractor_review", 2)
    assert r.json()["status"] == "contractor_review"
    assert (await go(world.owner, "contractor_review", 2)).status_code == 409  # stale version
    r = await go(world.owner, "preparation_ready", 3)
    assert r.json()["status"] == "preparation_ready"
    r = await go(world.owner, "scheduled", 4)
    assert r.status_code == 409 and r.json()["code"] == "no_accepted_assignment"
    r = await client.post(url, json={"expected_version": 4, "to": "attended"}, headers=world.owner.headers)
    assert r.status_code == 422  # recorded by visits, not here

    # The assigned contractor moves the shared job through review/preparation/scheduling.
    jurl = f"{API}/{world.job.id}/transition"
    r = await client.post(jurl, json={"expected_version": 1, "to": "contractor_review"}, headers=world.tech.headers)
    assert r.status_code == 403  # evidence_collection → contractor_review is the owner's
    r = await client.post(jurl, json={"expected_version": 1, "to": "contractor_review"}, headers=world.owner.headers)
    assert r.status_code == 200
    r = await client.post(jurl, json={"expected_version": 2, "to": "preparation_ready"}, headers=world.tech.headers)
    assert r.status_code == 200 and r.json()["status"] == "preparation_ready"
    r = await client.post(jurl, json={"expected_version": 3, "to": "scheduled"}, headers=world.tech.headers)
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    r = await client.post(jurl, json={"expected_version": 4, "to": "cancelled"}, headers=world.tech.headers)
    assert r.status_code == 403
    for outsider in (world.tech2, world.other_tech, world.org_admin):
        r = await client.post(jurl, json={"expected_version": 4, "to": "cancelled"}, headers=outsider.headers)
        assert r.status_code == 404
    r = await client.post(jurl, json={"expected_version": 4, "to": "cancelled"}, headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    # Closed: no more edits.
    r = await client.patch(
        f"{API}/{world.job.id}", json={"expected_version": 5, "title": "x"}, headers=world.owner.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "job_closed"


async def test_cancel_withdraws_a_pending_invitation(client, world):  # noqa: F811
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(status="invited"))
        await s.commit()
    r = await client.post(
        f"{API}/{world.job.id}/transition", json={"expected_version": 1, "to": "cancelled"}, headers=world.owner.headers
    )
    assert r.status_code == 200
    async with async_session() as s:
        assert (await s.get(JobAssignment, world.assignment_id)).status == "revoked"


async def test_delete_unshared_draft_and_archive_shared(client, world):  # noqa: F811
    job = await _create(client, world.owner, world.vessel_id)
    assert (await client.delete(f"{API}/{job['id']}", headers=world.tech.headers)).status_code == 404
    assert (await client.delete(f"{API}/{job['id']}", headers=world.owner.headers)).status_code == 204
    assert (await client.get(f"{API}/{job['id']}", headers=world.owner.headers)).status_code == 404
    assert all(j["id"] != job["id"] for j in (await client.get(f"{API}/", headers=world.owner.headers)).json())

    # A shared job cannot be deleted, and cannot be archived while the assignment is live.
    r = await client.delete(f"{API}/{world.job.id}", headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "job_shared"
    r = await client.post(f"{API}/{world.job.id}/archive", json={"expected_version": 1}, headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "job_active"
    await client.post(
        f"{API}/{world.job.id}/assignments/{world.assignment_id}/revoke", json={}, headers=world.owner.headers
    )
    r = await client.post(f"{API}/{world.job.id}/archive", json={"expected_version": 1}, headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["status"] == "archived" and r.json()["archived_at"]
    listed = (await client.get(f"{API}/?include_archived=true", headers=world.owner.headers)).json()
    assert str(world.job.id) in {j["id"] for j in listed}
    assert str(world.job.id) not in {j["id"] for j in (await client.get(f"{API}/", headers=world.owner.headers)).json()}


async def test_access_details_general_and_restricted(client, world):  # noqa: F811
    base = f"{API}/{world.job.id}/access"
    g = await client.get(f"{base}/general", headers=world.tech.headers)
    assert g.status_code == 200 and g.json()["general"]["marina"].startswith("Westhaven")
    _no_restricted(g.json())
    # Restricted section not granted → 403 for the assigned tech; outsiders 404.
    assert (await client.get(f"{base}/restricted", headers=world.tech.headers)).status_code == 403
    for outsider in (world.tech2, world.other_tech, world.other_owner, world.org_admin):
        assert (await client.get(f"{base}/restricted", headers=outsider.headers)).status_code == 404
        assert (await client.get(f"{base}/general", headers=outsider.headers)).status_code == 404

    # Owner reads and updates each part separately with expected_version.
    r = await client.get(f"{base}/restricted", headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["restricted"]["gate_code"] == "4512#"
    version = r.json()["version"]
    r = await client.put(
        f"{base}/restricted",
        json={"expected_version": version, "restricted": {"gate_code": "9999*", "key_handover": "Office"}},
        headers=world.owner.headers,
    )
    assert r.status_code == 200 and r.json()["restricted"] == {"gate_code": "9999*", "key_handover": "Office"}
    r = await client.put(
        f"{base}/general",
        json={"expected_version": version, "general": {"marina": "Bayswater"}},
        headers=world.owner.headers,
    )
    assert r.status_code == 409  # stale (the restricted update bumped the row version)
    r = await client.put(
        f"{base}/general",
        json={"expected_version": version + 1, "general": {"marina": "Bayswater", "power_availability": "15A"}},
        headers=world.owner.headers,
    )
    assert r.status_code == 200
    r = await client.put(
        f"{base}/general", json={"expected_version": version + 2, "general": {"x": 1}}, headers=world.owner.headers
    )
    assert r.status_code == 422
    r = await client.put(
        f"{base}/general",
        json={"expected_version": version + 2, "general": {"marina": "x"}},
        headers=world.tech.headers,
    )
    assert r.status_code == 404

    # Owner grants the section AND authorises the tech (fixture flag) → readable; audited every time.
    async with async_session() as s:
        await s.execute(
            update(JobAssignment)
            .where(JobAssignment.id == world.assignment_id)
            .values(sections=["summary", "access_general", "access_restricted"])
        )
        await s.commit()
    r = await client.get(f"{base}/restricted", headers=world.tech.headers)
    assert r.status_code == 200 and r.json()["restricted"]["gate_code"] == "9999*"
    # …and still never in the job response.
    _job = (await client.get(f"{API}/{world.job.id}", headers=world.tech.headers)).json()
    assert _job["viewer"]["restricted_access"] is True and "9999*" not in json.dumps(_job)
    # tech2 joins the assignment without the owner's per-member authorisation → 403.
    async with async_session() as s:
        s.add(
            JobAssignmentMember(
                assignment_id=world.assignment_id,
                user_id=world.tech2.id,
                restricted_access=False,
                added_by=world.owner.id,
            )
        )
        await s.commit()
    assert (await client.get(f"{base}/restricted", headers=world.tech2.headers)).status_code == 403
    assert (await client.get(f"{base}/general", headers=world.tech2.headers)).status_code == 200

    async with async_session() as s:
        reads = list(
            (await s.execute(select(AuditLog).where(AuditLog.action == "service_job_access_restricted_read"))).scalars()
        )
    assert len(reads) == 2  # owner read + tech read (denied attempts commit nothing)
    assert {r.detail["role"] for r in reads} == {"owner", "contractor"}
    for r in reads:
        assert "9999*" not in json.dumps(r.detail) and "4512#" not in json.dumps(r.detail)


async def test_resume_after_interruption_keeps_requests(world):  # noqa: F811
    """SJ-01: a fresh client session (new token) resumes with every request and gap intact."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as first:
        nxt = (await first.post(f"{API}/{world.job.id}/evidence-requests/next", headers=world.owner.headers)).json()
        rid = nxt["request"]["id"]
        await first.post(
            f"{API}/{world.job.id}/evidence-requests/{rid}/answer",
            json={"note": "Photo later; the pump is under the forward berth."},
            headers=world.owner.headers,
        )
        nxt = (await first.post(f"{API}/{world.job.id}/evidence-requests/next", headers=world.owner.headers)).json()
        await first.post(
            f"{API}/{world.job.id}/evidence-requests/{nxt['request']['id']}/unavailable",
            json={"reason": "cannot_safely_access", "note": "Behind the engine"},
            headers=world.owner.headers,
        )
        await first.post(f"{API}/{world.job.id}/evidence-requests/next", headers=world.owner.headers)
    # "Interrupted": a new client and a newly issued token.
    from app.tests.conftest import auth_headers

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as second:
        job = (
            await second.get(f"{API}/{world.job.id}", headers=auth_headers(world.owner.id, world.owner.email))
        ).json()
    ev = job["evidence"]
    assert len(ev["answered"]) == 1 and len(ev["unavailable"]) == 1 and len(ev["outstanding"]) == 1
    assert ev["answered"][0]["answer_note"].startswith("Photo later")
    assert job["gaps"][0]["reason"] == "cannot_safely_access" and job["technician_inspection_required"] is True
    assert ev["outstanding"][0]["options"] == ["take_photo", "upload_file", "answer_with_note", "cannot_safely_get"]
