"""Authorization for every workstream-B endpoint (SJ-06, SJ-07; decision SJ-D3).

Other owner, unassigned member of the same organization, its admin, another organization,
and a revoked assignment: 404 (no existence leak). An assigned member without the
section: 403. Owner-only operations: 404 for everyone else. Ids from another job: 404."""

from __future__ import annotations

from sqlalchemy import func, select

from app.database import async_session
from app.models.service_jobs import (
    AnalysisRun,
    BriefAcknowledgement,
    Measurement,
    Observation,
    PreparationBrief,
    PreparationItem,
    ScopeDecision,
    ScopeRevision,
)
from app.tests.conftest import create_product
from app.tests.service_jobs_support import assign, world  # noqa: F401
from app.tests.test_service_prep_support import job_url, make_asset, revoke, set_sections, store  # noqa: F401

MEASURE = {"dimension": "route_length", "component": "run", "value_text": "1", "unit": "m", "method": "owner_tape"}
TECH_MEASURE = {**MEASURE, "method": "contractor_site"}
ITEM = {"category": "tool", "name": "Torch", "purpose": "See into the locker"}
SCOPE = {"summary": "Replace hose"}
ASK = {"category": "label", "prompt": "Label photo", "reason": "Model"}


async def _fixtures(client, w):
    await make_asset(w.job, b"photo")
    run = await client.post(
        job_url(w.job.id, "/analysis"), headers={**w.owner.headers, "Idempotency-Key": "idor-run-1"}
    )
    obs = await client.post(job_url(w.job.id, "/observations"), json={"text": "note"}, headers=w.owner.headers)
    m = await client.post(job_url(w.job.id, "/measurements"), json=MEASURE, headers=w.owner.headers)
    item = await client.post(job_url(w.job.id, "/preparation-items"), json=ITEM, headers=w.owner.headers)
    preview = await client.post(job_url(w.job.id, "/briefs/preview"), headers=w.owner.headers)
    brief = await client.post(job_url(w.job.id, f"/briefs/{preview.json()['id']}/publish"), headers=w.owner.headers)
    scope = await client.post(job_url(w.job.id, "/scopes"), json=SCOPE, headers=w.tech.headers)
    product = await create_product(name="Torch (synthetic)")
    for r in (run, obs, m, item, brief, scope):
        assert r.status_code in (200, 201, 202), r.text
    return {
        "run": run.json()["id"],
        "obs": obs.json()["id"],
        "m": m.json()["id"],
        "item": item.json()["id"],
        "brief": brief.json()["id"],
        "scope": scope.json()["id"],
        "digest": scope.json()["content_digest"],
        "product": str(product.id),
    }


def _endpoints(ids: dict) -> list[tuple[str, str, dict | None, str | None]]:
    """(method, path suffix, body, section) — section None means owner-only."""
    i, b, s = ids["item"], ids["brief"], ids["scope"]
    return [
        ("GET", "/analysis", None, "evidence"),
        ("POST", "/analysis", None, "evidence"),
        ("GET", f"/analysis/{ids['run']}", None, "evidence"),
        ("GET", "/observations", None, "evidence"),
        ("POST", "/observations", {"text": "x"}, "evidence"),
        ("POST", f"/observations/{ids['obs']}/reject", {}, "evidence"),
        ("POST", f"/observations/{ids['obs']}/supersede", {"assertion": "x"}, "evidence"),
        ("GET", "/measurements", None, "measurements"),
        ("POST", "/measurements", TECH_MEASURE, "measurements"),
        ("POST", f"/measurements/{ids['m']}/revise", TECH_MEASURE, "measurements"),
        ("POST", f"/measurements/{ids['m']}/confirm", {"method": "contractor_site"}, "measurements"),
        ("POST", f"/measurements/{ids['m']}/reject", {}, "measurements"),
        ("GET", "/preparation-items", None, "preparation"),
        ("POST", "/preparation-items/suggest", None, "preparation"),
        ("POST", "/preparation-items", ITEM, "preparation"),
        ("POST", f"/preparation-items/{i}/confirm", {}, "preparation"),
        ("POST", f"/preparation-items/{i}/replace", ITEM, "preparation"),
        ("POST", f"/preparation-items/{i}/reject", {}, "preparation"),
        ("POST", f"/preparation-items/{i}/request-evidence", ASK, "preparation"),
        ("POST", f"/preparation-items/{i}/catalogue-match", {"product_id": ids["product"]}, "preparation"),
        ("POST", "/briefs/preview", None, None),
        ("GET", "/briefs", None, "preparation"),
        ("GET", f"/briefs/{b}", None, "preparation"),
        ("POST", f"/briefs/{b}/publish", {}, None),
        ("POST", f"/briefs/{b}/acknowledgements", {"kind": "reviewed"}, "preparation"),
        ("GET", f"/briefs/{b}/export", None, "preparation"),
        ("GET", "/scopes", None, "scope"),
        ("GET", f"/scopes/{s}", None, "scope"),
        ("POST", "/scopes", SCOPE, "scope"),
        (
            "POST",
            f"/scopes/{s}/decision",
            {"decision": "accepted", "revision_digest": ids["digest"]},
            "scope",
        ),
    ]


async def _call(client, actor, job_id, method, suffix, body, n):
    headers = {**actor.headers, "Idempotency-Key": f"idor-key-{n:04d}"}
    if method == "GET":
        return await client.get(job_url(job_id, suffix), headers=headers)
    return await client.post(job_url(job_id, suffix), json=body, headers=headers)


async def _counts():
    async with async_session() as s:
        return [
            (await s.execute(select(func.count()).select_from(m))).scalar_one()
            for m in (
                AnalysisRun,
                Observation,
                Measurement,
                PreparationItem,
                PreparationBrief,
                BriefAcknowledgement,
                ScopeRevision,
                ScopeDecision,
            )
        ]


async def test_outsiders_get_404_on_every_endpoint(client, world, store):  # noqa: F811
    ids = await _fixtures(client, world)
    before = await _counts()
    n = 0
    for outsider in (world.other_owner, world.tech2, world.org_admin, world.other_tech):
        for method, suffix, body, _ in _endpoints(ids):
            n += 1
            r = await _call(client, outsider, world.job.id, method, suffix, body, n)
            assert r.status_code == 404, (outsider, method, suffix, r.status_code, r.text)
            assert world.job.title not in r.text
    assert await _counts() == before


async def test_ids_from_another_job_are_not_found(client, world, store):  # noqa: F811
    """On another job they legitimately hold (as its owner, or as its assigned contractor),
    nobody can reach this job's nested records: every nested id is 404 for one of the two
    roles, and a role refusal (403 owner_only/contractor_only) never reveals the record."""
    ids = await _fixtures(client, world)
    await assign(world.other_job.id, world.org_a, world.other_owner.id, [(world.tech, True)])
    before = await _counts()
    nested = [e for e in _endpoints(ids) if any(str(v) in e[1] for v in ids.values())]
    for n, (method, suffix, body, _) in enumerate(nested):
        statuses = []
        for k, actor in enumerate((world.other_owner, world.tech)):
            r = await _call(client, actor, world.other_job.id, method, suffix, body, 500 + 2 * n + k)
            assert r.status_code == 404 or (
                r.status_code == 403 and r.json()["code"] in ("owner_only", "contractor_only")
            ), (method, suffix, r.status_code, r.text)
            statuses.append(r.status_code)
        assert 404 in statuses, (method, suffix, statuses)
    assert await _counts() == before


async def test_revoked_assignment_is_404_and_unshared_section_is_403(client, world, store):  # noqa: F811
    ids = await _fixtures(client, world)
    await set_sections(world.assignment_id, ["summary"])
    before = await _counts()
    for n, (method, suffix, body, section) in enumerate(_endpoints(ids)):
        r = await _call(client, world.tech, world.job.id, method, suffix, body, 1000 + n)
        expected = 404 if section is None else 403
        assert r.status_code == expected, (method, suffix, r.status_code, r.text)
        if expected == 403:
            assert r.json()["code"] == "section_not_shared"
    assert await _counts() == before
    await set_sections(world.assignment_id, ["summary", "evidence", "measurements", "preparation", "scope"])
    await revoke(world.assignment_id)
    for n, (method, suffix, body, _) in enumerate(_endpoints(ids)):
        r = await _call(client, world.tech, world.job.id, method, suffix, body, 2000 + n)
        assert r.status_code == 404, (method, suffix, r.status_code, r.text)
    assert await _counts() == before
