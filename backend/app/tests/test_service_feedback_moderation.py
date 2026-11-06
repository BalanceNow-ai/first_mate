"""Responses, reports and case-scoped moderation (SJ-18)."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.database import async_session
from app.main import app
from app.models.ops import AuditLog
from app.models.service_jobs import FeedbackVersion, FeedbackWindow, ModerationAction, ModerationCase, ServiceJob
from app.tests.conftest import create_actor
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_feedback import (
    C2O,
    O2C,
    OWNER_TEXT,
    TECH_TEXT,
    both_revealed,
    draft,
    key,
    open_window,
    outbox,
    overview,
    submit,
    visit,
)


async def _respond(client, actor, fid, kind, text="We replaced the hose as quoted.", expect=201):
    r = await client.post(
        f"/api/v1/service-feedback/{fid}/responses", json={"kind": kind, "text": text}, headers=actor.headers
    )
    assert r.status_code == expect, r.text
    return r.json()


async def _report(client, actor, fid, category="opinion", restrict=False, expect=201):
    r = await client.post(
        f"/api/v1/service-feedback/{fid}/reports",
        json={"category": category, "reason": "Please review this text.", "restrict_content": restrict},
        headers=actor.headers,
    )
    assert r.status_code == expect, r.text
    return r.json()


async def _act(client, actor, case_id, action, expect=200, **extra):
    r = await client.post(
        f"/api/v1/moderation/cases/{case_id}/actions",
        json={"action": action, "reason": f"Moderator {action}", **extra},
        headers=actor.headers,
    )
    assert r.status_code == expect, r.text
    return r.json()


async def test_subject_responds_requests_correction_and_author_adds_addendum(client, world):  # noqa: F811
    owner_fb, tech_fb = await both_revealed(client, world)
    # The organization (subject of the owner's review) responds once; responses are append-only.
    out = await _respond(client, world.tech, owner_fb, "response")
    assert [r["kind"] for r in out["responses"]] == ["response"]
    assert out["responses"][0]["author"]["role"] == "contractor"
    r = await _respond(client, world.tech, owner_fb, "response", "Second go", expect=409)
    assert r["code"] == "already_responded"
    await _respond(client, world.tech, owner_fb, "correction_request", "The call-out was agreed by phone.")
    # The author cannot respond to (or request correction of) their own review; the subject cannot add addenda.
    await _respond(client, world.owner, owner_fb, "response", expect=403)
    await _respond(client, world.owner, owner_fb, "correction_request", expect=403)
    await _respond(client, world.tech, owner_fb, "addendum", expect=403)
    out = await _respond(client, world.owner, owner_fb, "addendum", "Update: the leak has not returned.")
    assert [r["kind"] for r in out["responses"]] == ["response", "correction_request", "addendum"]
    # The revealed review itself is frozen.
    seen = await overview(client, world.owner, world.job.id)
    assert seen["mine"]["narrative"] == OWNER_TEXT and seen["mine"]["status"] == "revealed"
    # Both parties see the same response history; notifications carry no content.
    assert (await overview(client, world.tech, world.job.id))["theirs"]["responses"] == seen["mine"]["responses"]
    notes = await outbox(kind="feedback_response")
    assert {n.user_id for n in notes} == {world.owner.id, world.tech.id}
    assert all(set(n.payload) == {"kind", "job_id"} for n in notes)
    # The owner, as subject of the contractor's review, can respond too.
    await _respond(client, world.owner, tech_fb, "response", "The access note was updated on the 3rd.")


async def test_responses_only_after_reveal(client, world):  # noqa: F811
    await open_window(client, world)
    o = await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 3}, OWNER_TEXT)
    await submit(client, world.owner, world.job.id, O2C)
    fid = o["mine"]["id"]
    await _respond(client, world.tech, fid, "response", expect=404)  # not even its existence
    await _report(client, world.tech, fid, expect=404)
    r = await _respond(client, world.owner, fid, "addendum", expect=409)
    assert r["code"] == "feedback_not_revealed"


async def test_report_does_not_suppress_a_negative_review(client, world):  # noqa: F811
    owner_fb, _ = await both_revealed(client, world)
    case = await _report(client, world.tech, owner_fb, "opinion")
    assert case["status"] == "open" and case["restrict_content"] is False
    again = await _report(client, world.tech, owner_fb, "opinion", expect=200)
    assert again["id"] == case["id"]
    for who in (world.owner, world.tech):
        v = await overview(client, who, world.job.id)
        review = v["mine"] if who is world.owner else v["theirs"]
        assert review["narrative"] == OWNER_TEXT and review["content_state"] == "visible"
    r = await _report(client, world.tech, owner_fb, "harassment", restrict=True, expect=422)
    assert r["code"] == "restriction_not_available"
    # The author cannot report their own review.
    await _report(client, world.owner, owner_fb, "other", expect=403)
    async with async_session() as s:
        c = await s.get(ModerationCase, case["id"])
    assert c.content_version == 1 and c.retention_hold is True and c.reporter_id == world.tech.id


async def test_personal_information_report_shows_neutral_under_review_state(client, world):  # noqa: F811
    moderator = await create_actor("moderator", full_name="Mo Moderator")
    _, tech_fb = await both_revealed(client, world)
    case = await _report(client, world.owner, tech_fb, "personal_or_security_information", restrict=True)
    for who in (world.owner, world.tech):
        v = await overview(client, who, world.job.id)
        review = v["theirs"] if who is world.owner else v["mine"]
        assert review["narrative"] is None and review["content_state"] == "under_review"
        assert review["ratings"]  # the ratings themselves are not suppressed
        assert TECH_TEXT not in json.dumps(v)
    detail = (await client.get(f"/api/v1/moderation/cases/{case['id']}", headers=moderator.headers)).json()
    assert detail["feedback"]["narrative"] == TECH_TEXT  # the case moderator sees the reported content
    assert detail["reported_content"] == {
        "version": 1,
        "ratings": detail["feedback"]["ratings"],
        "narrative": TECH_TEXT,
    }
    # Resolution removing personal information purges the narrative from every stored version.
    resolved = await _act(
        client, moderator, case["id"], "resolve", disposition="content_removed_for_personal_information"
    )
    assert resolved["status"] == "resolved" and resolved["retention_hold"] is False
    assert resolved["feedback"]["narrative"] is None and resolved["feedback"]["content_state"] == "removed"
    async with async_session() as s:
        versions = list(
            (await s.execute(select(FeedbackVersion).where(FeedbackVersion.feedback_id == tech_fb))).scalars()
        )
    assert versions and all(v.narrative is None for v in versions)
    v = await overview(client, world.owner, world.job.id)
    assert v["theirs"]["content_state"] == "removed" and v["theirs"]["narrative"] is None
    notes = await outbox(kind="moderation_update")
    assert {n.user_id for n in notes} == {world.owner.id, world.tech.id}
    assert all(set(n.payload) == {"kind", "job_id"} for n in notes)


async def test_moderation_is_role_and_case_scoped(client, world):  # noqa: F811
    moderator = await create_actor("moderator")
    platform_admin = await create_actor("admin")
    owner_fb, _ = await both_revealed(client, world)
    case = await _report(client, world.tech, owner_fb, "factual_dispute")
    for who in (world.owner, world.tech, world.tech2, world.other_owner, world.org_admin):
        assert (await client.get("/api/v1/moderation/cases", headers=who.headers)).status_code == 403
        r = await client.get(f"/api/v1/moderation/cases/{case['id']}", headers=who.headers)
        assert r.status_code == 403
        r = await client.post(
            f"/api/v1/moderation/cases/{case['id']}/actions",
            json={"action": "resolve", "reason": "self-serve", "disposition": "no_action"},
            headers=who.headers,
        )
        assert r.status_code == 403
    for who in (moderator, platform_admin):
        listed = (await client.get("/api/v1/moderation/cases", headers=who.headers)).json()
        assert [c["id"] for c in listed] == [case["id"]]
    detail = await client.get(f"/api/v1/moderation/cases/{case['id']}", headers=moderator.headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["job"].keys() == {"id", "title", "status", "disputed", "organization_name"}
    for secret in ("4512#", "gate_code", "+64 21 000 0000", "F-27", "storage_key", "Westhaven"):
        assert secret not in detail.text
    # Case moderators still have no job access outside the case.
    r = await client.get(f"/api/v1/service-jobs/{world.job.id}/feedback", headers=moderator.headers)
    assert r.status_code == 404
    async with async_session() as s:
        viewed = list((await s.execute(select(AuditLog).where(AuditLog.action == "moderation.case_viewed"))).scalars())
    assert [(a.actor_id, a.entity_id) for a in viewed] == [(moderator.id, case["id"])]
    assert (await client.get("/api/v1/moderation/cases?status=resolved", headers=moderator.headers)).json() == []
    missing = await client.get(f"/api/v1/moderation/cases/{world.job.id}", headers=moderator.headers)
    assert missing.status_code == 404


async def test_moderation_actions_leave_an_attributed_audit_trail(client, world):  # noqa: F811
    moderator = await create_actor("moderator", full_name="Mo Moderator")
    owner_fb, _ = await both_revealed(client, world)
    case = await _report(client, world.tech, owner_fb, "harassment")
    r = await _act(client, moderator, case["id"], "assign", expect=422, assignee_id=str(world.owner.id))
    assert r["code"] == "not_a_moderator"
    out = await _act(client, moderator, case["id"], "assign")
    assert out["status"] == "under_review" and out["assigned_moderator_id"] == str(moderator.id)
    out = await _act(client, moderator, case["id"], "restrict")
    assert out["restrict_content"] is True and out["feedback"]["content_state"] == "under_review"
    v = await overview(client, world.tech, world.job.id)
    assert v["theirs"]["narrative"] is None
    out = await _act(client, moderator, case["id"], "unrestrict")
    assert out["feedback"]["content_state"] == "visible"
    r = await _act(client, moderator, case["id"], "resolve", expect=422)
    assert r["code"] == "disposition_required"
    out = await _act(client, moderator, case["id"], "resolve", disposition="no_action")
    assert out["disposition"] == "no_action" and out["retention_hold"] is False
    assert [a["action"] for a in out["actions"]] == [
        "reported",
        "assign",
        "restrict",
        "unrestrict",
        "resolve:no_action",
    ]
    assert all(a["reason"] and a["content_version"] == 1 for a in out["actions"])
    assert out["actions"][0]["actor_id"] == str(world.tech.id)
    assert {a["actor_id"] for a in out["actions"][1:]} == {str(moderator.id)}
    r = await _act(client, moderator, case["id"], "assign", expect=409)
    assert r["code"] == "case_resolved"
    async with async_session() as s:
        audited = [
            a.action
            for a in (
                await s.execute(
                    select(AuditLog).where(AuditLog.entity_id == case["id"]).order_by(AuditLog.created_at, AuditLog.id)
                )
            ).scalars()
        ]
        actions = list(
            (await s.execute(select(ModerationAction).where(ModerationAction.case_id == case["id"]))).scalars()
        )
    assert audited == [
        "moderation.case_opened",
        "moderation.assign",
        "moderation.restrict",
        "moderation.unrestrict",
        "moderation.resolve",
    ]
    assert len(actions) == 5
    # The review stays visible after a no-action resolution.
    assert (await overview(client, world.tech, world.job.id))["theirs"]["narrative"] == OWNER_TEXT


async def test_contested_completion_resolved_as_eligibility_corrected(client, world):  # noqa: F811
    moderator = await create_actor("moderator")
    done = await visit(client, world.tech, world.job.id, "completed")
    await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 1}, "They never came")
    r = await client.post(
        f"/api/v1/service-jobs/{world.job.id}/visits/{done['event']['id']}/contest",
        json={"reason": "Nobody attended the boat on that day."},
        headers={**world.owner.headers, "Idempotency-Key": key()},
    )
    case_id = r.json()["case_id"]
    detail = (await client.get(f"/api/v1/moderation/cases/{case_id}", headers=moderator.headers)).json()
    assert detail["category"] == "completion_contested" and detail["visit_event"]["kind"] == "completed"
    assert detail["contest_event"]["note"] == "Nobody attended the boat on that day."
    assert detail["feedback"] is None and detail["job"]["disputed"] is True
    out = await _act(client, moderator, case_id, "resolve", disposition="eligibility_corrected")
    assert out["job"]["disputed"] is False
    v = await overview(client, world.owner, world.job.id)
    assert v["mine"]["status"] == "withdrawn" and v["can_edit"] is False and v["theirs"] is None
    r = await draft(client, world.tech, world.job.id, C2O, {"problem_description_accuracy": 1}, expect=409)
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        window = await s.get(FeedbackWindow, world.job.id)
    assert job.disputed is False and window.revealed_at is not None


def test_no_public_scores_rankings_or_listings():
    paths = set(app.openapi()["paths"])
    feedbackish = sorted(p for p in paths if "feedback" in p or "moderation" in p or "visits" in p)
    assert feedbackish == [
        "/api/v1/moderation/cases",
        "/api/v1/moderation/cases/{case_id}",
        "/api/v1/moderation/cases/{case_id}/actions",
        "/api/v1/service-feedback/{feedback_id}",
        "/api/v1/service-feedback/{feedback_id}/reports",
        "/api/v1/service-feedback/{feedback_id}/responses",
        "/api/v1/service-jobs/{job_id}/feedback",
        "/api/v1/service-jobs/{job_id}/feedback/{direction}",
        "/api/v1/service-jobs/{job_id}/feedback/{direction}/submit",
        "/api/v1/service-jobs/{job_id}/visits",
        "/api/v1/service-jobs/{job_id}/visits/{event_id}/contest",
    ]
    for p in paths:
        assert not any(word in p for word in ("score", "rating", "rank", "reputation", "blacklist"))
