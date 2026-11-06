"""Foundation: service-job authorization helper and analysis-run fencing (SJ-06, SJ-07, SJ-21)."""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.core.errors import AppError
from app.database import async_session
from app.models.service_jobs import AnalysisRun, ContractorMembership, JobAssignment, JobAssignmentMember, ServiceJob
from app.services.service_jobs import access, runs
from app.tests.service_jobs_support import world  # noqa: F401


async def _job_for(user, job_id, **kw):
    async with async_session() as s:
        return await access.job_for(s, user.id, job_id, **kw)


async def test_owner_and_assigned_member_only(world):  # noqa: F811
    owner = await _job_for(world.owner, world.job.id)
    assert owner.is_owner and owner.can("access_restricted")
    tech = await _job_for(world.tech, world.job.id, section="evidence")
    assert tech.role == "contractor" and not tech.can("access_restricted")  # not in the default grant
    assert not tech.can("invoices")
    with pytest.raises(AppError) as e:
        await _job_for(world.tech, world.job.id, section="invoices")
    assert e.value.status_code == 403
    # Same organization but not assigned; admin of the org; other org; other owner: 404.
    for outsider in (world.tech2, world.org_admin, world.other_tech, world.other_owner):
        with pytest.raises(AppError) as e:
            await _job_for(outsider, world.job.id)
        assert e.value.status_code == 404, outsider
    with pytest.raises(AppError):
        await _job_for(world.tech, world.job.id, owner_only=True)


async def test_revocation_and_membership_removal_apply_to_the_next_request(world):  # noqa: F811
    await _job_for(world.tech, world.job.id)
    async with async_session() as s:
        await s.execute(
            update(ContractorMembership).where(ContractorMembership.user_id == world.tech.id).values(status="removed")
        )
        await s.commit()
    with pytest.raises(AppError):
        await _job_for(world.tech, world.job.id)
    async with async_session() as s:
        await s.execute(
            update(ContractorMembership).where(ContractorMembership.user_id == world.tech.id).values(status="active")
        )
        await s.execute(update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(status="revoked"))
        await s.commit()
    with pytest.raises(AppError):
        await _job_for(world.tech, world.job.id)


async def test_restricted_section_needs_the_member_flag(world):  # noqa: F811
    async with async_session() as s:
        await s.execute(
            update(JobAssignment)
            .where(JobAssignment.id == world.assignment_id)
            .values(sections=["summary", "access_restricted"])
        )
        await s.execute(
            update(JobAssignmentMember)
            .where(JobAssignmentMember.assignment_id == world.assignment_id)
            .values(restricted_access=False)
        )
        await s.commit()
    with pytest.raises(AppError) as e:
        await _job_for(world.tech, world.job.id, section="access_restricted")
    assert e.value.code == "section_not_shared"


async def test_run_publication_rechecks_revision_and_access(world):  # noqa: F811
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        run, created = await runs.create(
            s,
            kind="evidence_observations",
            requested_by=world.tech.id,
            job=job,
            assignment_id=world.assignment_id,
            idempotency_key="k1",
        )
        again, created_again = await runs.create(
            s, kind="evidence_observations", requested_by=world.tech.id, job=job, idempotency_key="k1"
        )
        assert created and not created_again and again.id == run.id
        await s.commit()
        run_id = run.id
    async with async_session() as s:
        token = await runs.claim(s, run_id)
    async with async_session() as s:
        assert await runs.claim(s, run_id) is None  # leased by the first claim
    # Access revoked while the provider "runs": the result is not published.
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(status="revoked"))
        await s.commit()
    async with async_session() as s:
        assert await runs.publish(s, run_id, token, {"observations": ["x"]}) == "superseded"
    async with async_session() as s:
        stored = await s.get(AnalysisRun, run_id)
        assert stored.output == {"stale": "access_revoked"}


async def test_run_publication_rejects_changed_evidence_and_stale_tokens(world):  # noqa: F811
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        run, _ = await runs.create(s, kind="evidence_observations", requested_by=world.owner.id, job=job)
        await s.commit()
        run_id = run.id
    async with async_session() as s:
        token = await runs.claim(s, run_id)
    async with async_session() as s:
        assert await runs.publish(s, run_id, __import__("uuid").uuid4(), {}) == "lease_lost"
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id, with_for_update=True)
        job.evidence_revision += 1
        await s.commit()
    async with async_session() as s:
        assert await runs.publish(s, run_id, token, {"x": 1}) == "superseded"
