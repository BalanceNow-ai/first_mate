"""Evidence analysis runs and observations (SJ-02, SJ-07, SJ-20, SJ-21, SJ-22)."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import func, select

from app.config import get_settings
from app.database import async_session
from app.models.service_jobs import (
    AnalysisRun,
    EvidenceAsset,
    JobAssignment,
    Measurement,
    Observation,
    PreparationItem,
    ScopeDecision,
    ScopeRevision,
    ServiceJob,
)
from app.services.service_jobs import observations as osvc
from app.services.service_jobs import revisions, runs, vision
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_prep_support import (  # noqa: F401
    analyse,
    execute,
    job_url,
    make_asset,
    revoke,
    store,
    synthetic,
)


async def _observations(client, actor, job_id, **params):
    r = await client.get(job_url(job_id, "/observations"), params=params, headers=actor.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_sj02_unreadable_or_blurry_evidence_yields_retake_never_invented_text(client, world, store):  # noqa: F811
    await make_asset(world.job, b"an unrecognised photo of a label")
    await make_asset(world.job, synthetic("pump-label"), quality={"blur": "blurry"})
    run = await analyse(client, world.owner, world.job.id)
    assert run["final"] == "draft_ready"
    obs = await _observations(client, world.owner, world.job.id)
    assert len(obs) == 2
    for o in obs:
        assert o["kind"] == "quality" and o["extracted_text"] is None and o["state"] == "model_suggested"
        assert "retake" in o["assertion"] and o["origin"] == "model"
    # A readable synthetic label is reported as text that "appears to read", with uncertainty.
    await make_asset(world.job, synthetic("pump-label"))
    await analyse(client, world.owner, world.job.id, key="analysis-key-2")
    label = next(o for o in await _observations(client, world.owner, world.job.id) if o["kind"] == "label_text")
    assert label["assertion"] == 'Image label text appears to read "FIXTURE PUMPCO FW-12 12V"'
    assert label["uncertainty"] and label["region"] == {"x": 0.1, "y": 0.1, "w": 0.6, "h": 0.15}
    assert label["model_version"] == "local_fixture:fixture-registry"
    # Re-analysis retires the earlier suggestions for the same assets.
    states = [o["state"] for o in await _observations(client, world.owner, world.job.id)]
    assert states.count("superseded") == 2


async def test_sj20_embedded_instructions_change_no_state(client, world, store, monkeypatch):  # noqa: F811
    await make_asset(world.job, synthetic("injection-text"))
    seen: list[vision.VisionInput] = []
    real = vision.LocalFixtureProvider()

    class Spy:
        name, model = real.name, real.model

        def available(self):
            return True

        async def analyse(self, item):
            seen.append(item)
            return await real.analyse(item)

    monkeypatch.setattr(vision, "get_provider", lambda settings=None: Spy())
    async with async_session() as s:
        before = (await s.get(JobAssignment, world.assignment_id)).sections
    run = await analyse(client, world.owner, world.job.id)
    assert run["final"] == "draft_ready"
    obs = await _observations(client, world.owner, world.job.id)
    assert len(obs) == 1
    o = obs[0]
    assert o["state"] == "model_suggested" and o["confidence"] == 0.99
    assert o["assertion"].startswith("Image label text appears to read")
    async with async_session() as s:
        for model in (Measurement, PreparationItem, ScopeRevision, ScopeDecision):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == 0
        a = await s.get(JobAssignment, world.assignment_id)
        assert a.sections == before and a.status == "accepted"
        assert (
            await s.execute(select(func.count()).select_from(JobAssignment).where(JobAssignment.job_id == world.job.id))
        ).scalar_one() == 1
    # Restricted access details never reach the provider.
    blob = json.dumps(seen[0].context)
    assert "4512#" not in blob and "+64 21 000 0000" not in blob and "F-27" not in blob


async def test_restricted_values_typed_into_the_description_are_masked(client, world, store, monkeypatch):  # noqa: F811
    from app.models.service_jobs import ServiceJob

    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        job.issue_description = "Leak under sink. Gate code is 4512# and we are at F-27."
        await s.commit()
    await make_asset(world.job, b"photo")
    seen = []

    class Spy(vision.LocalFixtureProvider):
        async def analyse(self, item):
            seen.append(item.context)
            return await super().analyse(item)

    monkeypatch.setattr(vision, "get_provider", lambda settings=None: Spy())
    await analyse(client, world.tech, world.job.id)
    assert "4512#" not in json.dumps(seen) and "[restricted]" in seen[0]["issue_description"]


async def test_sj22_disabled_provider_is_honest_and_manual_paths_work(client, world, store, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "service_vision_provider", "disabled")
    await make_asset(world.job, b"photo")
    r = await client.get(job_url(world.job.id, "/analysis"), headers=world.owner.headers)
    assert r.json()["available"] is False and r.json()["provider"] == "disabled"
    r = await client.post(
        job_url(world.job.id, "/analysis"), headers={**world.owner.headers, "Idempotency-Key": "analysis-off-1"}
    )
    assert r.status_code == 503 and r.json()["code"] == "analysis_unavailable"
    async with async_session() as s:
        assert (await s.execute(select(func.count()).select_from(AnalysisRun))).scalar_one() == 0
    # Manual measurement, notes and preparation keep working.
    r = await client.post(
        job_url(world.job.id, "/measurements"),
        json={
            "dimension": "hose_external_diameter",
            "component": "hose",
            "value_text": "32",
            "unit": "mm",
            "method": "owner_tape",
        },
        headers=world.owner.headers,
    )
    assert r.status_code == 201
    r = await client.post(
        job_url(world.job.id, "/observations"), json={"text": "Drip at the elbow"}, headers=world.owner.headers
    )
    assert r.status_code == 201 and r.json()["state"] == "owner_declared"
    r = await client.post(job_url(world.job.id, "/preparation-items/suggest"), headers=world.owner.headers)
    assert r.status_code == 200 and len(r.json()) >= 2


async def test_provider_failure_is_recorded_not_faked(client, world, store, monkeypatch):  # noqa: F811
    await make_asset(world.job, b"photo")

    class Broken(vision.LocalFixtureProvider):
        async def analyse(self, item):
            raise vision.VisionUnavailableError("down")

    r = await client.post(
        job_url(world.job.id, "/analysis"), headers={**world.owner.headers, "Idempotency-Key": "analysis-fail-1"}
    )
    monkeypatch.setattr(vision, "get_provider", lambda settings=None: Broken())
    run_id = r.json()["id"]
    assert await execute(run_id) == "pending"  # retried while attempts remain
    async with async_session() as s:
        run = await s.get(AnalysisRun, run_id)
        assert run.error == "analysis_unavailable"
        assert (await s.execute(select(func.count()).select_from(Observation))).scalar_one() == 0


async def test_sj21_evidence_changed_during_the_run_is_superseded_not_published(client, world, store, monkeypatch):  # noqa: F811
    """The provider call runs with no lock held: the owner records a measurement meanwhile
    (which locks the job row) and the stale result is kept only as a diagnostic."""
    await make_asset(world.job, synthetic("hose-marking-25mm-id"))
    r = await client.post(
        job_url(world.job.id, "/analysis"), headers={**world.owner.headers, "Idempotency-Key": "analysis-stale-1"}
    )
    run_id = r.json()["id"]

    class Slow(vision.LocalFixtureProvider):
        async def analyse(self, item):
            m = await client.post(
                job_url(world.job.id, "/measurements"),
                json={
                    "dimension": "hose_external_diameter",
                    "component": "hose",
                    "value_text": "32",
                    "unit": "mm",
                    "method": "owner_tape",
                },
                headers=world.owner.headers,
            )
            assert m.status_code == 201
            return await super().analyse(item)

    monkeypatch.setattr(vision, "get_provider", lambda settings=None: Slow())
    assert await execute(run_id) == "superseded"
    assert await _observations(client, world.owner, world.job.id) == []
    r = await client.get(job_url(world.job.id, f"/analysis/{run_id}"), headers=world.owner.headers)
    assert r.json()["status"] == "superseded" and r.json()["superseded_reason"] == "evidence_changed"


async def _claimed_run(world) -> tuple:  # noqa: F811
    asset_id = await make_asset(world.job, synthetic("pump-label"))
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        asset = await s.get(EvidenceAsset, asset_id)
        run, _ = await runs.create(
            s,
            kind="evidence_observations",
            requested_by=world.owner.id,
            job=job,
            assets=[asset],
            idempotency_key="race-1",
        )
        await s.commit()
        run_id = run.id
    async with async_session() as s:
        token = await runs.claim(s, run_id)
    return asset_id, run_id, token


async def test_publication_waits_for_a_concurrent_revision_bump_and_publishes_nothing(world, store):  # noqa: F811
    """Review finding (p4b): publication locked only the run row, so it read the evidence
    revision while another transaction held the job lock and was about to bump it — stale
    observations were published. Now the job row is locked first (job → run)."""
    asset_id, run_id, token = await _claimed_run(world)
    observed = [
        vision.VisionObservation(
            kind="label_text", assertion="appears to read X", extracted_text="X", page=None, region=None
        )
    ]
    bumped = asyncio.Event()

    async def bump_and_hold():
        async with async_session() as s:
            j = (
                await s.execute(select(ServiceJob).where(ServiceJob.id == world.job.id).with_for_update())
            ).scalar_one()
            await revisions.bump(s, j, reason="measurement_recorded")  # e.g. the owner records a measurement
            bumped.set()
            await asyncio.sleep(0.5)
            await s.commit()

    async def publish():
        await bumped.wait()
        async with async_session() as s:

            async def apply(session, published):
                await osvc._publish_observations(session, published, [(str(asset_id), observed)], "fixture:-")

            return await runs.publish(s, run_id, token, {"observations": []}, apply)

    _, status = await asyncio.gather(bump_and_hold(), publish())
    assert status == "superseded"
    async with async_session() as s:
        run = await s.get(AnalysisRun, run_id)
        published = (await s.execute(select(func.count()).select_from(Observation))).scalar_one()
    assert run.status == "superseded" and run.lease_token is None and published == 0


async def test_evidence_change_supersedes_a_running_run_and_a_late_failure_cannot_revive_it(world, store):  # noqa: F811
    _asset_id, run_id, token = await _claimed_run(world)
    async with async_session() as s:
        job = (await s.execute(select(ServiceJob).where(ServiceJob.id == world.job.id).with_for_update())).scalar_one()
        await revisions.bump(s, job, reason="asset_available")
        await s.commit()
    async with async_session() as s:
        run = await s.get(AnalysisRun, run_id)
        assert run.status == "superseded" and run.output == {"stale": "evidence_changed"}
    async with async_session() as s:
        await runs.fail(s, run_id, token, "analysis_unavailable")  # the provider then fails: no retry
    async with async_session() as s:
        run = await s.get(AnalysisRun, run_id)
        assert run.status == "superseded" and run.lease_token is None
        assert await runs.claim(s, run_id) is None


async def test_sj07_access_revoked_during_the_run_blocks_publication(client, world, store, monkeypatch):  # noqa: F811
    await make_asset(world.job, synthetic("pump-label"))
    r = await client.post(
        job_url(world.job.id, "/analysis"), headers={**world.tech.headers, "Idempotency-Key": "analysis-revoke-1"}
    )
    assert r.status_code == 202
    run_id = r.json()["id"]

    class Revoking(vision.LocalFixtureProvider):
        async def analyse(self, item):
            await revoke(world.assignment_id)
            return await super().analyse(item)

    monkeypatch.setattr(vision, "get_provider", lambda settings=None: Revoking())
    assert await execute(run_id) == "superseded"
    async with async_session() as s:
        assert (await s.get(AnalysisRun, run_id)).output == {"stale": "access_revoked"}
        assert (await s.execute(select(func.count()).select_from(Observation))).scalar_one() == 0


async def test_analysis_idempotency_and_asset_binding(client, world, store):  # noqa: F811
    ok = await make_asset(world.job, b"photo")
    pending = await make_asset(world.job, b"quarantined", status="quarantined")
    other = await make_asset(world.other_job, b"other")
    h = {**world.owner.headers, "Idempotency-Key": "analysis-idem-1"}
    r1 = await client.post(job_url(world.job.id, "/analysis"), headers=h)
    r2 = await client.post(job_url(world.job.id, "/analysis"), headers=h)
    assert r1.status_code == 202 and r2.status_code == 200 and r1.json()["id"] == r2.json()["id"]
    assert r1.json()["asset_ids"] == [str(ok)]  # only available assets are bound
    r = await client.post(job_url(world.job.id, "/analysis"), headers=world.owner.headers)
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await client.post(
        job_url(world.job.id, "/analysis"),
        json={"asset_ids": [str(pending)]},
        headers={**world.owner.headers, "Idempotency-Key": "analysis-idem-2"},
    )
    assert r.status_code == 422 and r.json()["code"] == "asset_not_available"
    r = await client.post(
        job_url(world.job.id, "/analysis"),
        json={"asset_ids": [str(other)]},
        headers={**world.owner.headers, "Idempotency-Key": "analysis-idem-3"},
    )
    assert r.status_code == 404
    # A second worker cannot claim a run already executed.
    assert await execute(r1.json()["id"]) == "draft_ready"
    assert await execute(r1.json()["id"]) == "not_claimed"


async def test_observation_notes_reject_and_supersede(client, world, store):  # noqa: F811
    asset = await make_asset(world.job, synthetic("hose-marking-25mm-id"))
    await analyse(client, world.owner, world.job.id)
    obs = await _observations(client, world.owner, world.job.id)
    marking = next(o for o in obs if o["kind"] == "marking_text")
    feature = next(o for o in obs if o["kind"] == "visible_feature")
    # Contractor corrects the reading; the original stays as superseded.
    r = await client.post(
        job_url(world.job.id, f"/observations/{marking['id']}/supersede"),
        json={"assertion": "Marking reads 25 mm ID (checked in a closer photo)", "extracted_text": "25 mm ID"},
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    corrected = r.json()
    assert corrected["supersedes_id"] == marking["id"] and corrected["state"] == "contractor_confirmed"
    assert corrected["origin"] == "contractor" and corrected["is_measurement"] is False
    r = await client.post(job_url(world.job.id, f"/observations/{marking['id']}/reject"), headers=world.owner.headers)
    assert r.status_code == 409
    r = await client.post(
        job_url(world.job.id, f"/observations/{feature['id']}/reject"),
        json={"note": "that is a different hose"},
        headers=world.owner.headers,
    )
    assert r.status_code == 200 and r.json()["state"] == "rejected"
    # Notes with a region on this job's asset.
    r = await client.post(
        job_url(world.job.id, "/observations"),
        json={"text": "Clamp is corroded", "asset_id": str(asset), "region": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}},
        headers=world.tech.headers,
    )
    assert r.status_code == 201 and r.json()["kind"] == "contractor_note"
    note_id = r.json()["id"]
    # Only the author or the owner can change a person's note.
    r = await client.post(job_url(world.job.id, f"/observations/{note_id}/reject"), headers=world.owner.headers)
    assert r.status_code == 200
    r = await client.post(
        job_url(world.job.id, "/observations"),
        json={"text": "bad", "region": {"x": 0.9, "y": 0.1, "w": 0.5, "h": 0.2}, "asset_id": str(asset)},
        headers=world.owner.headers,
    )
    assert r.status_code == 422
    active = await _observations(client, world.owner, world.job.id, include_inactive="false")
    assert {o["state"] for o in active} <= {"model_suggested", "owner_declared", "contractor_confirmed"}
