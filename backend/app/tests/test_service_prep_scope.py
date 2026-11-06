"""Scope revisions and explicit owner decisions (SJ-10, SJ-20, SJ-21)."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.database import async_session
from app.models.ops import AuditLog
from app.models.service_jobs import ScopeDecision
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_prep_support import analyse, job_url, make_asset, store, synthetic  # noqa: F401

SCOPE = {
    "summary": "Replace the pump outlet hose and both clamps",
    "tasks": [{"description": "Isolate the pump and drain the line"}, {"description": "Replace hose and clamps"}],
    "estimate_lines": [
        {"description": "Labour", "kind": "labour", "quantity": "1.5", "unit": "h", "unit_price_minor": 9500},
        {"description": "Hose 25 mm ID, 1 m", "kind": "parts", "amount_minor": 3200},
        {
            "description": "Clamps",
            "kind": "parts",
            "quantity": "2",
            "unit": "each",
            "unit_price_minor": 450,
            "amount_minor": 900,
        },
    ],
    "currency": "nzd",
    "exclusions": "Far-end fitting replacement if seized",
    "assumptions": "Hose is potable-water rated as marked",
}


async def _propose(client, w, body=None, expect=201):
    r = await client.post(job_url(w.job.id, "/scopes"), json=body or SCOPE, headers=w.tech.headers)
    assert r.status_code == expect, r.text
    return r.json()


async def _decide(client, actor, w, scope, decision="accepted", key="decision-key-1", digest=None):
    return await client.post(
        job_url(w.job.id, f"/scopes/{scope['id']}/decision"),
        json={"decision": decision, "revision_digest": digest or scope["content_digest"]},
        headers={**actor.headers, "Idempotency-Key": key},
    )


async def test_sj10_accepted_scope_and_later_change_need_separate_owner_decisions(client, world):  # noqa: F811
    first = await _propose(client, world)
    assert first["revision_number"] == 1 and first["is_change"] is False and first["status"] == "proposed"
    assert first["estimate_total_minor"] == 14250 + 3200 + 900 and first["currency"] == "NZD"
    assert first["estimate_lines"][0]["amount_minor"] == 14250
    # The owner (not the contractor) decides; the contractor's call is refused.
    r = await _decide(client, world.tech, world, first)
    assert r.status_code == 403 and r.json()["code"] == "owner_only"
    r = await _decide(client, world.owner, world, first, digest="f" * 64)
    assert r.status_code == 409 and r.json()["code"] == "digest_mismatch"
    r = await _decide(client, world.owner, world, first)
    assert r.status_code == 201, r.text
    decision = r.json()
    assert decision["decision"] == "accepted" and decision["revision_digest"] == first["content_digest"]
    again = await _decide(client, world.owner, world, first)  # same Idempotency-Key → same decision
    assert again.status_code == 200 and again.json()["id"] == decision["id"]
    r = await _decide(client, world.owner, world, first, decision="rejected", key="decision-key-2")
    assert r.status_code == 409 and r.json()["code"] == "scope_already_decided"
    r = await _decide(client, world.owner, world, first, decision="rejected")
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_reused"

    # A change must name the revision it supersedes.
    stale = await _propose(client, world, {**SCOPE, "summary": "Also replace the fitting"}, expect=409)
    assert stale["code"] == "scope_conflict"
    change = await _propose(
        client, world, {**SCOPE, "summary": "Also replace the fitting", "supersedes_id": first["id"]}
    )
    assert change["is_change"] is True and change["supersedes_id"] == first["id"] and change["status"] == "proposed"
    listed = (await client.get(job_url(world.job.id, "/scopes"), headers=world.owner.headers)).json()
    assert [s["status"] for s in listed] == ["accepted", "proposed"]  # the accepted decision stays on record
    assert [s["is_current"] for s in listed] == [False, True]
    assert listed[0]["decision"]["decision"] == "accepted" and listed[1]["decision"] is None
    r = await _decide(client, world.owner, world, change, decision="change_requested", key="decision-key-3")
    assert r.status_code == 201
    # A further change supersedes the undecided-then-change-requested revision.
    third = await _propose(client, world, {**SCOPE, "summary": "Revised change", "supersedes_id": change["id"]})
    r = await _decide(client, world.owner, world, change, key="decision-key-4")
    assert r.status_code == 409
    fourth = await _propose(client, world, {**SCOPE, "summary": "Revised again", "supersedes_id": third["id"]})
    r = await _decide(client, world.owner, world, third, key="decision-key-5")
    assert r.status_code == 409 and r.json()["code"] == "scope_superseded"
    r = await _decide(client, world.owner, world, fourth, key="decision-key-6")
    assert r.status_code == 201
    async with async_session() as s:
        actions = [a.action for a in (await s.execute(select(AuditLog).order_by(AuditLog.created_at))).scalars()]
        assert actions.count("service_scope.accepted") == 2 and "service_scope.change_requested" in actions


async def test_estimate_arithmetic_and_currency_are_deterministic(client, world):  # noqa: F811
    bad = {
        **SCOPE,
        "estimate_lines": [{"description": "x", "quantity": "2", "unit_price_minor": 100, "amount_minor": 250}],
    }
    assert (await _propose(client, world, bad, expect=422))["code"] == "line_arithmetic"
    no_currency = {**SCOPE, "currency": None}
    assert (await _propose(client, world, no_currency, expect=422))["code"] == "currency_required"
    no_amount = {**SCOPE, "estimate_lines": [{"description": "x"}]}
    assert (await _propose(client, world, no_amount, expect=422))["code"] == "amount_required"
    r = await client.post(job_url(world.job.id, "/scopes"), json=SCOPE, headers=world.owner.headers)
    assert r.status_code == 403 and r.json()["code"] == "contractor_only"
    tasks_only = await _propose(client, world, {"summary": "Inspect first", "tasks": [{"description": "Inspect"}]})
    assert tasks_only["estimate_total_minor"] is None and tasks_only["currency"] is None


async def test_sj21_concurrent_double_decisions_yield_exactly_one(client, world):  # noqa: F811
    scope = await _propose(client, world)
    results = await asyncio.gather(
        _decide(client, world.owner, world, scope, decision="accepted", key="race-key-accept"),
        _decide(client, world.owner, world, scope, decision="rejected", key="race-key-reject"),
        _decide(client, world.owner, world, scope, decision="accepted", key="race-key-accept-2"),
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409], [r.text for r in results]
    async with async_session() as s:
        assert (await s.execute(select(func.count()).select_from(ScopeDecision))).scalar_one() == 1


async def test_sj10_document_text_saying_approved_creates_no_decision(client, world, store):  # noqa: F811
    scope = await _propose(client, world)
    await make_asset(world.job, synthetic("injection-text"))
    await analyse(client, world.owner, world.job.id)
    await analyse(client, world.tech, world.job.id, key="analysis-key-tech")
    r = await client.get(job_url(world.job.id, f"/scopes/{scope['id']}"), headers=world.owner.headers)
    assert r.json()["status"] == "proposed" and r.json()["decision"] is None
    async with async_session() as s:
        assert (await s.execute(select(func.count()).select_from(ScopeDecision))).scalar_one() == 0
