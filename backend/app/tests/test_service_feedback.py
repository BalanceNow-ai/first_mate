"""Reciprocal feedback: parties, blind drafts/submission, reveal and clock boundaries (SJ-16, SJ-17).

Helpers here are reused by the other ``test_service_feedback_*`` modules.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.errors import AppError
from app.database import async_session, utcnow
from app.models.notifications import NotificationOutbox
from app.models.service_jobs import (
    FeedbackVersion,
    FeedbackWindow,
    JobAssignment,
    JobAssignmentMember,
    JobFeedback,
)
from app.services.service_jobs import access, feedback
from app.tests.conftest import create_actor
from app.tests.service_jobs_support import world  # noqa: F401

O2C = "owner_to_contractor"
C2O = "contractor_to_owner"
OWNER_RATINGS = {"communication_clarity": 4, "invoice_clarity_and_scope_relationship": "not_applicable"}
TECH_RATINGS = {"problem_description_accuracy": 2, "availability_for_decisions": 5}
OWNER_TEXT = "Arrived on time and explained the hose replacement clearly."
TECH_TEXT = "The photos matched what we found; the berth access note was out of date."


def key() -> str:
    return f"k-{uuid.uuid4().hex}"


async def visit(client, actor, job_id, kind, *, occurred_at=None, expect=201, **extra):
    body = {"kind": kind, "occurred_at": (occurred_at or utcnow()).isoformat(), **extra}
    r = await client.post(
        f"/api/v1/service-jobs/{job_id}/visits", json=body, headers={**actor.headers, "Idempotency-Key": key()}
    )
    assert r.status_code == expect, r.text
    return r.json()


async def open_window(client, w):
    """The assigned technician records attendance → the job's feedback window opens."""
    return await visit(client, w.tech, w.job.id, "attended")


async def draft(client, actor, job_id, direction, ratings=None, narrative=None, expected_version=None, expect=200):
    body = {"ratings": ratings or {}, "narrative": narrative}
    if expected_version is not None:
        body["expected_version"] = expected_version
    r = await client.put(f"/api/v1/service-jobs/{job_id}/feedback/{direction}", json=body, headers=actor.headers)
    assert r.status_code == expect, r.text
    return r.json()


async def submit(client, actor, job_id, direction, *, expect=201, idem=None):
    r = await client.post(
        f"/api/v1/service-jobs/{job_id}/feedback/{direction}/submit",
        headers={**actor.headers, "Idempotency-Key": idem or key()},
    )
    assert r.status_code == expect, r.text
    return r.json()


async def overview(client, actor, job_id, expect=200):
    r = await client.get(f"/api/v1/service-jobs/{job_id}/feedback", headers=actor.headers)
    assert r.status_code == expect, r.text
    return r.json()


async def both_revealed(client, w):
    await open_window(client, w)
    await draft(client, w.owner, w.job.id, O2C, OWNER_RATINGS, OWNER_TEXT)
    await draft(client, w.tech, w.job.id, C2O, TECH_RATINGS, TECH_TEXT)
    await submit(client, w.owner, w.job.id, O2C)
    out = await submit(client, w.tech, w.job.id, C2O)
    assert out["window"]["revealed"] is True
    return (await overview(client, w.owner, w.job.id))["mine"]["id"], out["mine"]["id"]


async def outbox(user_id=None, kind=None) -> list[NotificationOutbox]:
    async with async_session() as s:
        q = select(NotificationOutbox).where(NotificationOutbox.template == "service_job_update")
        if user_id is not None:
            q = q.where(NotificationOutbox.user_id == user_id)
        rows = list((await s.execute(q.order_by(NotificationOutbox.created_at))).scalars())
    return [r for r in rows if kind is None or r.payload.get("kind") == kind]


async def window_row(job_id) -> FeedbackWindow:
    async with async_session() as s:
        return (await s.execute(select(FeedbackWindow).where(FeedbackWindow.job_id == job_id))).scalar_one()


# SJ-16 -------------------------------------------------------------------------------------
async def test_two_parties_submit_one_review_each_absent_and_na_are_not_zero(client, world):  # noqa: F811
    await open_window(client, world)
    o = await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS, OWNER_TEXT)
    assert [d["key"] for d in o["dimensions"]] == [
        "communication_clarity",
        "arrival_access_coordination",
        "explanation_of_work_and_changes",
        "care_and_agreed_work_delivery",
        "invoice_clarity_and_scope_relationship",
    ]
    t = await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS, TECH_TEXT)
    assert [d["key"] for d in t["dimensions"]] == [
        "problem_description_accuracy",
        "access_arrival_accuracy",
        "equipment_site_prepared",
        "availability_for_decisions",
        "communication_and_scope_changes",
    ]
    await submit(client, world.owner, world.job.id, O2C)
    revealed = await submit(client, world.tech, world.job.id, C2O)
    assert revealed["mine"]["status"] == "revealed" and revealed["theirs"]["status"] == "revealed"
    owner_view = await overview(client, world.owner, world.job.id)
    # Exactly the answers given: absent answers stay absent, N/A stays N/A, nothing becomes 0.
    assert owner_view["mine"]["ratings"] == OWNER_RATINGS
    assert owner_view["theirs"]["ratings"] == TECH_RATINGS
    assert owner_view["theirs"]["narrative"] == TECH_TEXT
    assert owner_view["theirs"]["author"]["role"] == "contractor"
    assert owner_view["theirs"]["organization"]["name"] == "Harbour Marine Services"
    assert owner_view["theirs"]["visit_date"] is not None
    blob = json.dumps(owner_view)
    for word in ("average", "score", "rank", "mean", "total"):
        assert word not in blob
    async with async_session() as s:
        rows = list((await s.execute(select(JobFeedback).where(JobFeedback.job_id == world.job.id))).scalars())
    assert sorted(r.direction for r in rows) == [C2O, O2C]
    assert {r.author_id for r in rows} == {world.owner.id, world.tech.id}
    assert all(0 not in r.ratings.values() for r in rows)


async def test_ratings_are_integers_1_to_5_or_not_applicable(client, world):  # noqa: F811
    await open_window(client, world)
    for bad in ({"communication_clarity": 0}, {"communication_clarity": 6}, {"communication_clarity": "5"}):
        await draft(client, world.owner, world.job.id, O2C, bad, expect=422)
    await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": True}, expect=422)
    await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 3.5}, expect=422)
    r = await draft(client, world.owner, world.job.id, O2C, {"paid_on_time": 5}, expect=422)
    assert r["code"] == "unknown_dimension"
    # A contractor dimension cannot be answered on the owner's review.
    await draft(client, world.owner, world.job.id, O2C, {"problem_description_accuracy": 3}, expect=422)
    # Submitting an empty review is refused (no default rating).
    await draft(client, world.owner, world.job.id, O2C, {})
    r = await submit(client, world.owner, world.job.id, O2C, expect=422)
    assert r["code"] == "feedback_empty"


async def test_one_review_per_organization_and_only_actual_participants(client, world):  # noqa: F811
    await open_window(client, world)
    # Another assigned member of org A (a colleague of the author).
    colleague = await create_actor("customer", full_name="Hemi Colleague")
    async with async_session() as s:
        from app.models.service_jobs import ContractorMembership

        s.add(ContractorMembership(organization_id=world.org_a, user_id=colleague.id, role="member", status="active"))
        s.add(JobAssignmentMember(assignment_id=world.assignment_id, user_id=colleague.id, added_by=world.owner.id))
        await s.commit()
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS, TECH_TEXT)
    r = await draft(client, colleague, world.job.id, C2O, {"problem_description_accuracy": 1}, expect=403)
    assert r["code"] == "feedback_authored_by_colleague"
    r = await submit(client, colleague, world.job.id, C2O, expect=403)
    # The colleague sees the organization's (own side's) review, not a second vote.
    seen = await overview(client, colleague, world.job.id)
    assert seen["mine"]["author"]["id"] == str(world.tech.id) and seen["can_edit"] is False
    # Self-review / wrong side.
    r = await draft(client, world.owner, world.job.id, C2O, {"problem_description_accuracy": 5}, expect=403)
    assert r["code"] == "wrong_feedback_direction"
    await draft(client, world.tech, world.job.id, O2C, {"communication_clarity": 5}, expect=403)
    await draft(client, world.owner, world.job.id, "anything", {}, expect=404)


async def test_third_parties_get_nothing(client, world):  # noqa: F811
    moderator = await create_actor("moderator", full_name="Mo Moderator")
    platform_admin = await create_actor("admin", full_name="Pat PlatformAdmin")
    owner_fb, tech_fb = await both_revealed(client, world)
    outsiders = (world.tech2, world.org_admin, world.other_tech, world.other_owner, platform_admin, moderator)
    for who in outsiders:
        await overview(client, who, world.job.id, expect=404)
        await draft(client, who, world.job.id, O2C, {"communication_clarity": 1}, expect=404)
        await draft(client, who, world.job.id, C2O, {"problem_description_accuracy": 1}, expect=404)
        await submit(client, who, world.job.id, C2O, expect=404)
        r = await client.get(f"/api/v1/service-jobs/{world.job.id}/visits", headers=who.headers)
        assert r.status_code == 404, who
        for fid in (owner_fb, tech_fb):
            r = await client.get(f"/api/v1/service-feedback/{fid}", headers=who.headers)
            assert r.status_code == 404
            r = await client.post(
                f"/api/v1/service-feedback/{fid}/responses",
                json={"kind": "response", "text": "x"},
                headers=who.headers,
            )
            assert r.status_code == 404
            r = await client.post(
                f"/api/v1/service-feedback/{fid}/reports",
                json={"category": "opinion", "reason": "not mine"},
                headers=who.headers,
            )
            assert r.status_code == 404
    # The other owner's job is invisible to this job's parties too.
    await overview(client, world.owner, world.other_job.id, expect=404)
    await overview(client, world.tech, world.other_job.id, expect=404)


# SJ-17 -------------------------------------------------------------------------------------
async def test_blind_until_both_submit_no_side_channel(client, world):  # noqa: F811
    await open_window(client, world)
    before = await overview(client, world.tech, world.job.id)
    tech_mail_before = len(await outbox(world.tech.id))
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS, OWNER_TEXT)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS, OWNER_TEXT + " Edited.", expected_version=1)
    await submit(client, world.owner, world.job.id, O2C)
    after = await overview(client, world.tech, world.job.id)
    # The other side's view is byte-for-byte unchanged by the owner drafting/submitting.
    assert after == before
    assert after["theirs"] is None and after["window"]["revealed"] is False
    assert "reveal" in after["reveal_rule"] and after["window"]["closes_at"] in after["reveal_rule"]
    assert len(await outbox(world.tech.id)) == tech_mail_before  # no "the other side submitted"
    # The owner sees only their own review.
    mine = await overview(client, world.owner, world.job.id)
    assert mine["mine"]["status"] == "submitted" and mine["theirs"] is None
    # The owner's review id is not reachable by the other side before reveal.
    r = await client.get(f"/api/v1/service-feedback/{mine['mine']['id']}", headers=world.tech.headers)
    assert r.status_code == 404
    r = await client.post(
        f"/api/v1/service-feedback/{mine['mine']['id']}/responses",
        json={"kind": "response", "text": "early"},
        headers=world.tech.headers,
    )
    assert r.status_code == 404
    # Contractor drafts: still blind both ways.
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS, TECH_TEXT)
    owner_view = await overview(client, world.owner, world.job.id)
    assert owner_view["theirs"] is None
    assert TECH_TEXT not in json.dumps(owner_view)
    # Every notification payload is content-free.
    for row in await outbox():
        assert set(row.payload) == {"kind", "job_id"}
        assert row.payload["kind"] in {"visit_recorded", "feedback_open", "feedback_revealed"}
    await submit(client, world.tech, world.job.id, C2O)
    revealed = await outbox(kind="feedback_revealed")
    assert {r.user_id for r in revealed} == {world.owner.id, world.tech.id}
    assert all(OWNER_TEXT not in json.dumps(r.payload) for r in revealed)


async def test_drafts_are_versioned_and_frozen_at_reveal(client, world):  # noqa: F811
    await open_window(client, world)
    v1 = await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 2}, "First draft")
    assert v1["mine"]["version"] == 1 and v1["mine"]["status"] == "draft"
    r = await draft(
        client, world.owner, world.job.id, O2C, {"communication_clarity": 3}, expected_version=7, expect=409
    )
    assert r["code"] == "version_conflict"
    await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 3}, "Second", expected_version=1)
    await submit(client, world.owner, world.job.id, O2C)
    # Edits after submission but before reveal are still versioned and stay submitted.
    v3 = await draft(client, world.owner, world.job.id, O2C, {"communication_clarity": 4}, "Third", expected_version=2)
    assert v3["mine"]["version"] == 3 and v3["mine"]["status"] == "submitted"
    async with async_session() as s:
        versions = list(
            (
                await s.execute(
                    select(FeedbackVersion)
                    .join(JobFeedback, JobFeedback.id == FeedbackVersion.feedback_id)
                    .where(JobFeedback.job_id == world.job.id)
                    .order_by(FeedbackVersion.version)
                )
            ).scalars()
        )
    assert [(v.version, v.narrative) for v in versions] == [(1, "First draft"), (2, "Second"), (3, "Third")]
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS)
    await submit(client, world.tech, world.job.id, C2O)
    r = await draft(
        client, world.owner, world.job.id, O2C, {"communication_clarity": 1}, expected_version=3, expect=409
    )
    assert r["code"] == "feedback_revealed"


async def test_double_submit_yields_one(client, world):  # noqa: F811
    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS)
    idem = key()
    first = await submit(client, world.owner, world.job.id, O2C, idem=idem)
    again = await submit(client, world.owner, world.job.id, O2C, idem=idem, expect=200)
    other_key = await submit(client, world.owner, world.job.id, O2C, expect=200)
    assert first["mine"]["submitted_at"] == again["mine"]["submitted_at"] == other_key["mine"]["submitted_at"]
    r = await client.post(f"/api/v1/service-jobs/{world.job.id}/feedback/{O2C}/submit", headers=world.owner.headers)
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    async with async_session() as s:
        rows = list((await s.execute(select(JobFeedback).where(JobFeedback.job_id == world.job.id))).scalars())
    assert len(rows) == 1 and rows[0].status == "submitted" and rows[0].version == 1


async def test_submission_closes_exactly_at_closes_at(client, world):  # noqa: F811
    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS)
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS)
    window = await window_row(world.job.id)
    assert window.closes_at - window.opens_at == timedelta(days=14)
    async with async_session() as s:
        with pytest.raises(AppError) as e:
            await feedback.submit(s, world.owner.id, world.job.id, O2C, now=window.closes_at)
        assert e.value.code == "feedback_window_closed"
        with pytest.raises(AppError) as e:
            await feedback.save_draft(
                s, world.owner.id, world.job.id, O2C, ratings={}, narrative=None, expected_version=None,
                now=window.closes_at,
            )  # fmt: skip
        assert e.value.code == "feedback_window_closed"
        await s.rollback()
    async with async_session() as s:
        view, created = await feedback.submit(
            s, world.owner.id, world.job.id, O2C, now=window.closes_at - timedelta(microseconds=1)
        )
        await s.commit()
    assert created and view["mine"]["status"] == "submitted" and view["window"]["revealed"] is False


async def test_sweep_reveals_one_sided_once_and_drafts_stay_private(client, world):  # noqa: F811
    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS, OWNER_TEXT)
    await submit(client, world.owner, world.job.id, O2C)
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS, TECH_TEXT)  # never submitted
    window = await window_row(world.job.id)
    async with async_session() as s:
        assert await feedback.reveal_due(s, now=window.closes_at - timedelta(seconds=1)) == {
            "windows_revealed": 0,
            "reviews_revealed": 0,
        }
    async with async_session() as s:
        assert await feedback.reveal_due(s, now=window.closes_at) == {"windows_revealed": 1, "reviews_revealed": 1}
    async with async_session() as s:
        assert await feedback.reveal_due(s, now=window.closes_at + timedelta(days=1)) == {
            "windows_revealed": 0,
            "reviews_revealed": 0,
        }
    tech_view = await overview(client, world.tech, world.job.id)
    assert tech_view["theirs"]["narrative"] == OWNER_TEXT and tech_view["window"]["revealed"] is True
    assert tech_view["mine"]["status"] == "draft"  # the author still sees their own unsent draft
    owner_view = await overview(client, world.owner, world.job.id)
    assert owner_view["theirs"] is None and TECH_TEXT not in json.dumps(owner_view)
    assert len(await outbox(world.owner.id, "feedback_revealed")) == 1
    # Nothing can be submitted after the sweep.
    async with async_session() as s:
        with pytest.raises(AppError) as e:
            await feedback.submit(s, world.tech.id, world.job.id, C2O, now=window.closes_at - timedelta(seconds=1))
        assert e.value.code == "feedback_revealed"


async def test_sweep_task_runs_through_celery_wrapper(world, client):  # noqa: F811
    from app.tasks.service_feedback import reveal_due_feedback

    await open_window(client, world)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS)
    await submit(client, world.owner, world.job.id, O2C)
    async with async_session() as s:
        await s.execute(
            update(FeedbackWindow)
            .where(FeedbackWindow.job_id == world.job.id)
            .values(opens_at=utcnow() - timedelta(days=15), closes_at=utcnow() - timedelta(days=1))
        )
        await s.commit()
    import asyncio

    result = await asyncio.to_thread(reveal_due_feedback.run)
    assert result == {"windows_revealed": 1, "reviews_revealed": 1}
    from app.celery_app import celery

    entry = celery.conf.beat_schedule["reveal-due-service-feedback"]
    assert entry["task"] == "app.tasks.service_feedback.reveal_due_feedback"


async def test_revoked_assignment_keeps_eligibility_but_no_job_media(client, world):  # noqa: F811
    await open_window(client, world)
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(status="revoked"))
        await s.commit()
    # Working access is gone (no job, media or access details) ...
    async with async_session() as s:
        with pytest.raises(AppError) as e:
            await access.job_for(s, world.tech.id, world.job.id)
        assert e.value.status_code == 404
    # ... but the participation record for feedback remains.
    await draft(client, world.tech, world.job.id, C2O, TECH_RATINGS, TECH_TEXT)
    await draft(client, world.owner, world.job.id, O2C, OWNER_RATINGS, OWNER_TEXT)
    await submit(client, world.owner, world.job.id, O2C)
    view = await submit(client, world.tech, world.job.id, C2O)
    assert view["theirs"]["narrative"] == OWNER_TEXT
    visits = await client.get(f"/api/v1/service-jobs/{world.job.id}/visits", headers=world.tech.headers)
    assert visits.status_code == 200
    blob = json.dumps(view) + visits.text
    for secret in ("4512#", "gate_code", "+64 21 000 0000", "F-27", "storage_key", "assets"):
        assert secret not in blob
    tech_fb = view["mine"]["id"]
    r = await client.post(
        f"/api/v1/service-feedback/{view['theirs']['id']}/responses",
        json={"kind": "response", "text": "Thanks for the feedback."},
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    assert tech_fb
    # Removing the technician from the organization ends participation (next request, D23).
    async with async_session() as s:
        from app.models.service_jobs import ContractorMembership

        await s.execute(
            update(ContractorMembership).where(ContractorMembership.user_id == world.tech.id).values(status="removed")
        )
        await s.commit()
    await overview(client, world.tech, world.job.id, expect=404)
