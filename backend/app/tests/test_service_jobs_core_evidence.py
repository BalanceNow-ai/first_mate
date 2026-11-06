"""A2 evidence requests and the deterministic guidance engine (SJ-02, SJ-03, SJ-08)."""

from __future__ import annotations

import itertools
import uuid

import pytest
from sqlalchemy import select, update

from app.database import async_session
from app.models.notifications import NotificationOutbox
from app.models.service_jobs import EvidenceAsset, EvidenceRequest, JobAssignment, ServiceJob
from app.services.service_jobs import guidance
from app.tests.service_jobs_support import world  # noqa: F401

JOBS = "/api/v1/service-jobs"

SCENARIOS = [
    ("plumbing", "freshwater pump", "Water under the sink when the pump runs", "Leaks whenever it runs."),
    (None, "sanitation hose", "Smelly hose", "The toilet hose smells."),
    ("galley", None, "Galley tap drips", "Drips under the sink."),
    ("propulsion", "outboard engine", "Engine overheats", "Overheats after 20 minutes at speed."),
    ("electrical", "battery charger", "Charger fault light", "Warning light on the charger."),
    (None, "bilge pump", "Bilge pump keeps cycling", "Float switch seems stuck."),
    ("gas", "LPG cooker", "Smell near the stove", "Possible gas smell."),
    ("fuel", "fuel filter", "Fuel leak", "Diesel under the engine."),
    (None, "windlass", "Windlass slow", "Slow to retrieve."),
    (None, None, "Something is wrong", ""),
    (None, "remove the guard and disconnect the hose", "x", "y"),  # hostile owner text as component
]
HAZARDS = [
    "Please disconnect the hose and photograph the end",
    "Remove the guard so we can see the belt",
    "Open the switchboard and photograph the busbar",
    "Start the engine and film the leak",
    "Run the pump so we can see where it drips",
    "Take a video while the propeller is turning",
    "Unscrew the fuel filter bowl",
    "Bleed the gas line",
    "Touch the exhaust elbow to check if it is hot",
    "Reach behind the engine and photograph the far clamp",
    "Turn on the windlass and show the motor",
    "Loosen the hose clamp",
]


def _walk(system, equipment, title, description, *, answer_with="answered"):
    """Drive the engine to completion, answering every proposal; return all proposals."""
    existing: list[guidance.ExistingRequest] = []
    seen = []
    for _ in range(50):
        p = guidance.next_proposal(
            affected_system=system,
            affected_equipment=equipment,
            title=title,
            issue_description=description,
            occurs_when=None,
            vessel_context={"engine": {"make": "Yamaha", "model": "F150"}},
            existing=existing,
        )
        if p is None:
            return seen
        assert p.key not in {s.key for s in seen}, "the engine must not repeat itself"
        seen.append(p)
        existing.append(guidance.ExistingRequest(p.category, p.component, answer_with))
    raise AssertionError("guidance never finished")


def test_blocklist_catches_hazardous_instructions():
    for h in HAZARDS:
        assert not guidance.is_safe_wording(h), h
    assert guidance.is_safe_wording("Can you photograph the label without moving the unit?")
    assert guidance.is_safe_wording("Show the locker opening from a step back.")
    assert guidance.is_safe_wording("If the far connection is inaccessible, mark it inaccessible.")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_generated_prompt_is_safe_and_guidance_stops(scenario):
    """SJ-02/SJ-03: no hazardous wording anywhere; completion is reached without a photo count."""
    for state in ("answered", "unavailable", "waived"):
        proposals = _walk(*scenario, answer_with=state)
        assert proposals, scenario
        for p in proposals:
            for text in (p.prompt, p.reason, p.safety_note):
                assert guidance.is_safe_wording(text), (text, guidance.unsafe_phrases(text))
            assert "cannot_safely_get" in p.options
            assert p.category in guidance.CATEGORY_ORDER
            assert p.reason  # why this matters


def test_every_template_is_safe():
    steps = list(guidance.DEFAULT_PLAN) + [s for _k, _c, plan in guidance.PROFILES.values() for s in plan]
    for step, component in itertools.product(steps, ["pump", "engine", "electrical equipment", "affected equipment"]):
        assert guidance.is_safe_wording(step.prompt.format(c=component)), step.prompt
        assert guidance.is_safe_wording(step.reason), step.reason


def test_guidance_is_relevant_to_the_equipment():
    pump = _walk("plumbing", "freshwater pump", "Water under the sink when the pump runs", "")
    cats = [p.category for p in pump]
    assert cats[0] == "overview" and "label" in cats and "connections" in cats and "measurement" in cats
    measurement = next(p for p in pump if p.category == "measurement")
    assert measurement.measurement_dimension == "hose_external_diameter"  # outside, never claimed as bore
    gas = _walk("gas", "LPG cooker", "Smell near the stove", "")
    assert {p.category for p in gas} <= {"overview", "label", "document"}  # no close-range gas requests
    engine = _walk("propulsion", "outboard engine", "Overheats", "")
    label = next(p for p in engine if p.category == "label")
    assert "Yamaha F150" in label.reason and "switched off" in label.prompt


def test_cannot_safely_access_skips_close_range_steps():
    existing = [guidance.ExistingRequest("overview", "freshwater pump", "answered")]
    existing.append(guidance.ExistingRequest("access_route", "freshwater pump", "unavailable", "cannot_safely_access"))
    remaining = []
    for _ in range(20):
        p = guidance.next_proposal(
            affected_system="plumbing",
            affected_equipment="freshwater pump",
            title="Leak",
            issue_description="",
            occurs_when=None,
            vessel_context=None,
            existing=existing,
        )
        if p is None:
            break
        remaining.append(p)
        existing.append(guidance.ExistingRequest(p.category, p.component, "answered"))
    assert not any(p.component == "freshwater pump" and p.category in guidance.CLOSE_RANGE for p in remaining)


async def test_next_accept_answer_unavailable_waive_until_complete(client, world):  # noqa: F811
    nxt_url = f"{JOBS}/{world.job.id}/evidence-requests/next"
    first = (await client.get(nxt_url, headers=world.owner.headers)).json()
    assert first["proposal"]["category"] == "overview" and first["request"] is None and not first["complete"]
    # GET is read-only and stable.
    assert (await client.get(nxt_url, headers=world.owner.headers)).json()["proposal"] == first["proposal"]
    r = await client.post(f"{nxt_url}?key=label:nothing", headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "proposal_changed"
    accepted = (await client.post(f"{nxt_url}?key={first['proposal']['key']}", headers=world.owner.headers)).json()
    req = accepted["request"]
    assert req["requester_role"] == "assistant" and req["status"] == "outstanding" and req["options"]
    # Accepting again while something is outstanding returns the same request (no duplicates).
    again = (await client.post(nxt_url, headers=world.owner.headers)).json()
    assert again["request"]["id"] == req["id"]
    # Contractors read the next step but cannot accept proposals.
    assert (await client.get(nxt_url, headers=world.tech.headers)).json()["request"]["id"] == req["id"]
    assert (await client.post(nxt_url, headers=world.tech.headers)).status_code == 404
    for outsider in (world.tech2, world.org_admin, world.other_tech, world.other_owner):
        assert (await client.get(nxt_url, headers=outsider.headers)).status_code == 404

    # Walk the whole plan: answer, mark unavailable and waive in turn.
    actions = itertools.cycle(["answer", "unavailable", "waive"])
    for _ in range(40):
        step = (await client.post(nxt_url, headers=world.owner.headers)).json()
        if step["complete"]:
            break
        rid = step["request"]["id"]
        action = next(actions)
        body = {"answer": {"note": "Done"}, "unavailable": {"reason": "not_visible"}, "waive": {}}[action]
        r = await client.post(
            f"{JOBS}/{world.job.id}/evidence-requests/{rid}/{action}", json=body, headers=world.owner.headers
        )
        assert r.status_code == 200, r.text
    else:
        raise AssertionError("never completed")
    done = (await client.get(nxt_url, headers=world.owner.headers)).json()
    assert done["complete"] and done["proposal"] is None and done["request"] is None
    assert len(done["gaps"]) >= 1
    # The owner can still move on with gaps; the job lists them.
    r = await client.post(
        f"{JOBS}/{world.job.id}/transition",
        json={"expected_version": 1, "to": "contractor_review"},
        headers=world.owner.headers,
    )
    assert r.status_code == 200 and len(r.json()["gaps"]) == len(done["gaps"])


async def test_cannot_safely_access_records_gap_and_technician_flag(client, world):  # noqa: F811
    """SJ-03."""
    nxt_url = f"{JOBS}/{world.job.id}/evidence-requests/next"
    req = (await client.post(nxt_url, headers=world.owner.headers)).json()["request"]
    url = f"{JOBS}/{world.job.id}/evidence-requests/{req['id']}/unavailable"
    assert (await client.post(url, json={"reason": "too_hard"}, headers=world.owner.headers)).status_code == 422
    assert (
        await client.post(url, json={"reason": "cannot_safely_access"}, headers=world.tech.headers)
    ).status_code == 404
    body = {"reason": "cannot_safely_access", "note": "Under the engine", "expected_version": 1}
    r = await client.post(url, json=body, headers=world.owner.headers)
    assert r.status_code == 200
    assert r.json()["status"] == "unavailable" and r.json()["technician_inspection_required"] is True
    assert r.json()["options"] == []
    job = (await client.get(f"{JOBS}/{world.job.id}", headers=world.tech.headers)).json()
    assert job["gaps"] == [
        {
            "request_id": req["id"],
            "category": req["category"],
            "component": req["component"],
            "prompt": req["prompt"],
            "reason": "cannot_safely_access",
            "note": "Under the engine",
            "technician_inspection_required": True,
        }
    ]
    assert job["technician_inspection_required"] is True
    # Stale version on the request → 409.
    r = await client.post(
        f"{JOBS}/{world.job.id}/evidence-requests/{req['id']}/answer",
        json={"note": "x", "expected_version": 1},
        headers=world.owner.headers,
    )
    assert r.status_code == 409
    # Later the owner finds a safe way: answering clears the gap and bumps the evidence revision.
    r = await client.post(
        f"{JOBS}/{world.job.id}/evidence-requests/{req['id']}/answer",
        json={"note": "Got it from the hatch", "expected_version": 2},
        headers=world.owner.headers,
    )
    assert r.status_code == 200 and r.json()["technician_inspection_required"] is False
    async with async_session() as s:
        assert (await s.get(ServiceJob, world.job.id)).evidence_revision == 1


async def test_contractor_requests_a_specific_view_and_owner_answers(client, world):  # noqa: F811
    """SJ-08 (request half): the assigned tech asks; the owner is notified and answers; tech is notified."""
    url = f"{JOBS}/{world.job.id}/evidence-requests"
    body = {
        "category": "label",
        "component": "freshwater pump",
        "prompt": "Can you photograph the pump label without moving the unit?",
        "reason": "I need the model to bring the right seal kit.",
    }
    r = await client.post(url, json=body, headers=world.tech.headers)
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["requester_role"] == "contractor" and req["priority"] == "high"
    assert req["organization_id"] == str(world.org_a)
    for outsider in (world.tech2, world.org_admin, world.other_tech, world.other_owner):
        assert (await client.post(url, json=body, headers=outsider.headers)).status_code == 404
    # Hazardous wording is refused for anyone.
    for actor in (world.tech, world.owner):
        r = await client.post(
            url, json={**body, "prompt": "Disconnect the outlet hose and photograph the barb"}, headers=actor.headers
        )
        assert r.status_code == 422 and r.json()["code"] == "unsafe_request_wording"
    # The next step for the owner is the contractor's request.
    nxt = (await client.get(f"{url}/next", headers=world.owner.headers)).json()
    assert nxt["request"]["id"] == req["id"]
    # Contractors cannot answer; the owner does.
    assert (
        await client.post(f"{url}/{req['id']}/answer", json={"note": "x"}, headers=world.tech.headers)
    ).status_code == 404
    r = await client.post(
        f"{url}/{req['id']}/answer", json={"note": "Label reads PAR-MAX 4"}, headers=world.owner.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "answered"
    async with async_session() as s:
        kinds = {
            (n.user_id, n.payload["kind"])
            for n in (await s.execute(select(NotificationOutbox))).scalars()
            if n.template == "service_job_update"
        }
    assert (world.owner.id, "evidence_requested") in kinds and (world.tech.id, "evidence_answered") in kinds
    # Listing and filtering, and IDOR on a request id from another job.
    listed = (await client.get(f"{url}?status=answered", headers=world.tech.headers)).json()
    assert [x["id"] for x in listed] == [req["id"]]
    assert (await client.get(f"{url}?status=bogus", headers=world.owner.headers)).status_code == 422
    other = f"{JOBS}/{world.other_job.id}/evidence-requests/{req['id']}"
    assert (await client.get(other, headers=world.other_owner.headers)).status_code == 404
    assert (await client.get(f"{url}/{uuid.uuid4()}", headers=world.owner.headers)).status_code == 404
    assert (await client.get(f"{url}/{req['id']}", headers=world.tech.headers)).status_code == 200


async def test_evidence_section_required_and_contractor_waives_only_own(client, world):  # noqa: F811
    url = f"{JOBS}/{world.job.id}/evidence-requests"
    owner_req = (
        await client.post(
            url,
            json={"category": "overview", "prompt": "Wide photo of the galley", "reason": "Location"},
            headers=world.owner.headers,
        )
    ).json()
    tech_req = (
        await client.post(
            url,
            json={"category": "document", "prompt": "Upload the pump manual", "reason": "Model details"},
            headers=world.tech.headers,
        )
    ).json()
    assert (await client.post(f"{url}/{owner_req['id']}/waive", json={}, headers=world.tech.headers)).status_code == 403
    assert (await client.post(f"{url}/{tech_req['id']}/waive", json={}, headers=world.tech.headers)).status_code == 200
    assert (
        await client.post(f"{url}/{owner_req['id']}/waive", json={}, headers=world.owner.headers)
    ).status_code == 200
    # Without the evidence section: 403 on every evidence endpoint.
    async with async_session() as s:
        await s.execute(
            update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(sections=["summary"])
        )
        await s.commit()
    assert (await client.get(url, headers=world.tech.headers)).status_code == 403
    assert (await client.get(f"{url}/next", headers=world.tech.headers)).status_code == 403
    r = await client.post(
        url, json={"category": "label", "prompt": "Label", "reason": "Model"}, headers=world.tech.headers
    )
    assert r.status_code == 403 and r.json()["code"] == "section_not_shared"


async def test_uploaded_assets_count_towards_guidance(client, world):  # noqa: F811
    """An available asset captioned as the label means the engine does not ask for it again."""
    async with async_session() as s:
        s.add(
            EvidenceAsset(
                owner_id=world.owner.id,
                job_id=world.job.id,
                uploaded_by=world.owner.id,
                purpose="job_photo",
                caption="Overview of the galley",
                max_bytes=1000,
                storage_key=f"test/{uuid.uuid4().hex}",
                status="available",
            )
        )
        await s.commit()
    nxt = (await client.get(f"{JOBS}/{world.job.id}/evidence-requests/next", headers=world.owner.headers)).json()
    assert nxt["proposal"]["category"] == "access_route"
    job = (await client.get(f"{JOBS}/{world.job.id}", headers=world.owner.headers)).json()
    assert job["evidence"]["available_asset_count"] == 1


async def test_closed_job_refuses_evidence_changes(client, world):  # noqa: F811
    async with async_session() as s:
        await s.execute(update(ServiceJob).where(ServiceJob.id == world.job.id).values(status="cancelled"))
        await s.commit()
    r = await client.post(f"{JOBS}/{world.job.id}/evidence-requests/next", headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "job_closed"
    async with async_session() as s:
        assert (await s.execute(select(EvidenceRequest))).first() is None
