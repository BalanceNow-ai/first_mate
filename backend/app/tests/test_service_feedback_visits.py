"""Visits and feedback eligibility (SJ-16): attendance opens the window, cancellation before it never does."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.database import async_session, utcnow
from app.models.service_jobs import ModerationCase, ServiceJob, VisitEvent
from app.tests.conftest import create_actor
from app.tests.service_jobs_support import create_job, world  # noqa: F401
from app.tests.test_service_feedback import (
    C2O,
    O2C,
    draft,
    key,
    outbox,
    overview,
    visit,
    window_row,
)


async def _job(job_id) -> ServiceJob:
    async with async_session() as s:
        return await s.get(ServiceJob, job_id)


async def test_cancelled_before_attendance_has_no_service_rating(client, world):  # noqa: F811
    v = await visit(client, world.owner, world.job.id, "scheduled", occurred_at=utcnow() + timedelta(days=2))
    assert v["job_status"] == "scheduled" and v["job_version"] == 2 and not v["feedback_window_opened"]
    v = await visit(client, world.tech, world.job.id, "cancelled", expected_version=2)
    assert v["job_status"] == "cancelled" and not v["feedback_window_opened"]
    for who in (world.owner, world.tech):
        o = await overview(client, who, world.job.id)
        assert o["eligible"] is False and o["window"] is None
        assert o["ineligible_reason"] == "cancelled_before_attendance"
    r = await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 3}, expect=409)
    assert r["code"] == "feedback_not_eligible"
    r = await visit(client, world.tech, world.job.id, "attended", expect=409)
    assert r["code"] == "invalid_visit_transition"
    assert await outbox(kind="feedback_open") == []


async def test_first_attendance_opens_window_at_server_time(client, world):  # noqa: F811
    started = utcnow()
    two_days_ago = started - timedelta(days=2)
    v = await visit(client, world.tech, world.job.id, "attended", occurred_at=two_days_ago, note="On site 9am")
    assert v["feedback_window_opened"] and v["job_status"] == "attended"
    assert v["event"]["actor_role"] == "contractor" and v["event"]["assignment_id"] == str(world.assignment_id)
    window = await window_row(world.job.id)
    # Timed from the server-recorded eligibility event, not the declared occurred_at.
    assert started <= window.opens_at <= utcnow()
    assert window.closes_at == window.opens_at + timedelta(days=14)
    assert window.basis == "attended" and window.eligibility_event_id.hex == v["event"]["id"].replace("-", "")
    opened = await outbox(kind="feedback_open")
    assert {r.user_id for r in opened} == {world.owner.id, world.tech.id}
    assert all(set(r.payload) == {"kind", "job_id"} for r in opened)
    assert {r.user_id for r in await outbox(kind="visit_recorded")} == {world.owner.id}
    # A second attendance and a completion do not move the window.
    await visit(client, world.owner, world.job.id, "attended")
    done = await visit(client, world.owner, world.job.id, "completed")
    assert done["job_status"] == "completed" and not done["feedback_window_opened"]
    again = await window_row(world.job.id)
    assert (again.opens_at, again.closes_at, again.eligibility_event_id) == (
        window.opens_at,
        window.closes_at,
        window.eligibility_event_id,
    )
    assert again.basis == "completed"
    r = await visit(client, world.owner, world.job.id, "cancelled", expect=409)
    assert r["code"] == "invalid_visit_transition"
    listed = await client.get(f"/api/v1/service-jobs/{world.job.id}/visits", headers=world.tech.headers)
    assert [e["kind"] for e in listed.json()] == ["attended", "attended", "completed"]


async def test_completion_alone_opens_the_window(client, world):  # noqa: F811
    v = await visit(client, world.owner, world.job.id, "completed")
    assert v["feedback_window_opened"] and (await window_row(world.job.id)).basis == "completed"


async def test_attended_then_cancelled_offers_only_applicable_dimensions(client, world):  # noqa: F811
    await visit(client, world.tech, world.job.id, "attended")
    await visit(client, world.owner, world.job.id, "cancelled", note="Owner postponed the work")
    window = await window_row(world.job.id)
    assert window.basis == "attended_then_cancelled"
    o = await overview(client, world.owner, world.job.id)
    assert o["eligible"] and o["window"]["basis"] == "attended_then_cancelled"
    keys = [d["key"] for d in o["dimensions"]]
    assert "care_and_agreed_work_delivery" not in keys and len(keys) == 4
    r = await draft(client, world.owner, world.job.id, O2C, {"care_and_agreed_work_delivery": 2}, expect=422)
    assert r["code"] == "dimension_not_applicable"
    ok = await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 4})
    assert ok["mine"]["basis"] == "attended_then_cancelled"
    t = await overview(client, world.tech, world.job.id)
    assert len(t["dimensions"]) == 5
    await draft(client, world.tech, world.job.id, C2O, {"equipment_site_prepared": 3})


async def test_status_without_a_recorded_visit_creates_no_eligibility(client, world):  # noqa: F811
    # A job marked completed by any other path (e.g. created from an invoice) is not eligible.
    job = await create_job(world.owner, world.vessel_id, status="completed", entry_point="invoice")
    o = await overview(client, world.owner, job.id)
    assert o["eligible"] is False and o["ineligible_reason"] == "no_attended_visit"


async def test_visit_needs_accepted_assignment_and_current_version(client, world):  # noqa: F811
    lone = await create_job(world.owner, world.vessel_id)
    r = await visit(client, world.owner, lone.id, "attended", expect=409)
    assert r["code"] == "no_accepted_assignment"
    r = await visit(client, world.owner, lone.id, "cancelled")
    assert r["event"]["assignment_id"] is None and r["job_status"] == "cancelled"
    r = await visit(client, world.owner, world.job.id, "attended", expected_version=9, expect=409)
    assert r["code"] == "version_conflict"
    r = await visit(
        client, world.owner, world.job.id, "attended", occurred_at=utcnow() + timedelta(hours=3), expect=422
    )
    assert r["code"] == "occurred_in_future"
    r = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/visits",
        json={"kind": "attended", "occurred_at": utcnow().isoformat()},
        headers=world.owner.headers,
    )
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/visits",
        json={"kind": "completion_contested", "occurred_at": utcnow().isoformat()},
        headers={**world.owner.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 422


async def test_visit_idempotency_key_replays_one_event(client, world):  # noqa: F811
    idem = key()
    body = {"kind": "attended", "occurred_at": utcnow().isoformat()}
    headers = {**world.tech.headers, "Idempotency-Key": idem}
    first = await client.post(f"/api/v1/service-jobs/{world.job.id}/visits", json=body, headers=headers)
    second = await client.post(f"/api/v1/service-jobs/{world.job.id}/visits", json=body, headers=headers)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["event"]["id"] == second.json()["event"]["id"]
    assert second.json()["feedback_window_opened"] is False
    other = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/visits", json={**body, "kind": "completed"}, headers=headers
    )
    assert other.status_code == 409 and other.json()["code"] == "idempotency_key_reused"
    async with async_session() as s:
        n = len(list((await s.execute(select(VisitEvent).where(VisitEvent.job_id == world.job.id))).scalars()))
    assert n == 1


async def test_visits_are_participants_only(client, world):  # noqa: F811
    platform_admin = await create_actor("admin")
    moderator = await create_actor("moderator")
    for who in (world.tech2, world.org_admin, world.other_tech, world.other_owner, platform_admin, moderator):
        await visit(client, who, world.job.id, "attended", expect=404)
        r = await client.get(f"/api/v1/service-jobs/{world.job.id}/visits", headers=who.headers)
        assert r.status_code == 404
    assert await outbox() == []


async def test_other_participant_contests_completion_without_rewriting_it(client, world):  # noqa: F811
    done = await visit(client, world.tech, world.job.id, "completed")
    event_id = done["event"]["id"]
    url = f"/api/v1/service-jobs/{world.job.id}/visits/{event_id}/contest"
    body = {"reason": "The pump still leaks; the work was not finished."}
    # The recorder cannot contest their own record.
    r = await client.post(url, json=body, headers={**world.tech.headers, "Idempotency-Key": key()})
    assert r.status_code == 403 and r.json()["code"] == "cannot_contest_own_record"
    for who in (world.tech2, world.other_owner, world.other_tech):
        r = await client.post(url, json=body, headers={**who.headers, "Idempotency-Key": key()})
        assert r.status_code == 404
    idem = key()
    r = await client.post(url, json=body, headers={**world.owner.headers, "Idempotency-Key": idem})
    assert r.status_code == 201, r.text
    contested = r.json()
    assert contested["job_disputed"] is True and contested["job_status"] == "completed"
    assert contested["event"]["kind"] == "completion_contested" and contested["event"]["contests_event_id"] == event_id
    again = await client.post(url, json=body, headers={**world.owner.headers, "Idempotency-Key": idem})
    assert again.status_code == 200 and again.json()["case_id"] == contested["case_id"]
    again = await client.post(url, json=body, headers={**world.owner.headers, "Idempotency-Key": key()})
    assert again.status_code == 200 and again.json()["case_id"] == contested["case_id"]
    async with async_session() as s:
        cases = list((await s.execute(select(ModerationCase).where(ModerationCase.job_id == world.job.id))).scalars())
        original = await s.get(VisitEvent, done["event"]["id"])
    assert len(cases) == 1 and cases[0].category == "completion_contested" and cases[0].retention_hold
    assert original.kind == "completed"  # the contested fact is kept, not rewritten
    assert (await _job(world.job.id)).disputed is True
    listed = (await client.get(f"/api/v1/service-jobs/{world.job.id}/visits", headers=world.owner.headers)).json()
    assert [(e["kind"], e["contested"]) for e in listed] == [("completed", True), ("completion_contested", False)]
    # Eligibility stays as recorded until moderation decides.
    assert (await overview(client, world.owner, world.job.id))["eligible"] is True
    # Another job's event cannot be contested through this job.
    sched = await visit(client, world.other_owner, world.other_job.id, "cancelled")
    r = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/visits/{sched['event']['id']}/contest",
        json=body,
        headers={**world.tech.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 404  # another job's event


async def test_contest_needs_attendance_or_completion(client, world):  # noqa: F811
    sched = await visit(client, world.owner, world.job.id, "scheduled", occurred_at=utcnow() + timedelta(days=1))
    r = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/visits/{sched['event']['id']}/contest",
        json={"reason": "Never agreed this date"},
        headers={**world.tech.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 409 and r.json()["code"] == "not_contestable"


async def test_former_participant_keeps_only_their_own_minimal_visit_record(client, world):  # noqa: F811
    """Review finding: a contractor revoked by reassignment read the next organization's
    visit notes and contested the owner's record of the new assignment (job → disputed)."""
    mine = await visit(client, world.tech, world.job.id, "attended", note="Org A: swapped the hose clamp")
    owner_on_a = await visit(client, world.owner, world.job.id, "attended", note="Owner note to org A")
    r = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/assignments/{world.assignment_id}/reassign",
        json={"organization_id": str(world.org_b), "sections": ["summary"], "live_updates": False},
        headers={**world.owner.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/contractors/assignments/{r.json()['id']}/accept",
        json={"member_user_ids": [str(world.other_tech.id)]},
        headers=world.other_tech.headers,
    )
    assert r.status_code == 200, r.text
    b_event = await visit(client, world.other_tech, world.job.id, "attended", note="Org B: impeller, invoice to follow")
    owner_on_b = await visit(client, world.owner, world.job.id, "completed", note="Owner confirms org B's work")
    url = f"/api/v1/service-jobs/{world.job.id}/visits"

    # Former participant (org A): only org A's assignment, minimal — no names/notes but their own.
    r = await client.get(url, headers=world.tech.headers)
    assert r.status_code == 200, r.text
    seen = {e["id"]: e for e in r.json()}
    assert set(seen) == {mine["event"]["id"], owner_on_a["event"]["id"]}
    assert seen[mine["event"]["id"]]["note"] == "Org A: swapped the hose clamp"  # their own record
    other = seen[owner_on_a["event"]["id"]]
    assert other["kind"] == "attended" and other["actor_role"] == "owner" and other["occurred_at"]
    assert other["note"] is None and other["actor_name"] is None and other["actor_id"] is None
    assert "Org B" not in r.text and "Nikau" not in r.text and "org B's work" not in r.text

    # ...and may contest only records of their own assignment.
    r = await client.post(
        f"{url}/{owner_on_b['event']['id']}/contest",
        json={"reason": "I was revoked but I can still dispute this"},
        headers={**world.tech.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 404, r.text
    assert (await _job(world.job.id)).disputed is False
    r = await client.post(
        f"{url}/{owner_on_a['event']['id']}/contest",
        json={"reason": "We did not attend with the owner that day"},
        headers={**world.tech.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 201, r.text

    # Current participant (org B): the current assignment's events only.
    r = await client.get(url, headers=world.other_tech.headers)
    assert r.status_code == 200, r.text
    assert {e["id"] for e in r.json()} == {b_event["event"]["id"], owner_on_b["event"]["id"]}
    assert "Org A" not in r.text and "Owner note to org A" not in r.text
    r = await client.post(
        f"{url}/{owner_on_a['event']['id']}/contest",
        json={"reason": "Not ours to contest"},
        headers={**world.other_tech.headers, "Idempotency-Key": key()},
    )
    assert r.status_code == 404
    # Nobody else: an unassigned member of org A, an unrelated owner.
    for outsider in (world.tech2, world.other_owner):
        assert (await client.get(url, headers=outsider.headers)).status_code == 404
