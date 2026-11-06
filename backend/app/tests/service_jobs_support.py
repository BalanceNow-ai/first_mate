"""Shared fixtures/helpers for the service-jobs tests (all workstreams).

``world`` builds the standard cast: an owner with a vessel and a job; contractor org A
(admin + two members, one assigned with restricted access) holding an accepted
assignment; an unrelated contractor org B; and an unrelated third owner — so every test
can prove isolation as well as access.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest_asyncio

from app.database import async_session, utcnow
from app.models.service_jobs import (
    ContractorMembership,
    ContractorOrganization,
    JobAccessDetails,
    JobAssignment,
    JobAssignmentMember,
    ServiceJob,
)
from app.tests.conftest import Actor, create_actor, create_vessel

DEFAULT_SECTIONS = ["summary", "evidence", "measurements", "preparation", "access_general", "scope"]


async def create_org(name: str = "Harbour Marine Services", *members: tuple[Actor, str]) -> uuid.UUID:
    async with async_session() as s:
        org = ContractorOrganization(name=name)
        s.add(org)
        await s.flush()
        for actor, role in members:
            s.add(
                ContractorMembership(
                    organization_id=org.id, user_id=actor.id, role=role, status="active", verified_at=utcnow()
                )
            )
        await s.commit()
        return org.id


async def create_job(owner: Actor, vessel_id: uuid.UUID | None = None, **overrides) -> ServiceJob:
    data = {
        "owner_id": owner.id,
        "vessel_id": vessel_id,
        "title": "Water under the sink when the pump runs",
        "issue_description": "There is water under the galley sink whenever the freshwater pump runs.",
        "affected_system": "plumbing",
        "affected_equipment": "freshwater pump",
        "status": "evidence_collection",
    }
    data.update(overrides)
    async with async_session() as s:
        job = ServiceJob(**data)
        s.add(job)
        await s.flush()
        s.add(
            JobAccessDetails(
                job_id=job.id,
                general={"marina": "Westhaven Marina, Pier F", "access_hours": "08:00–17:00"},
                restricted={"gate_code": "4512#", "contact_phone": "+64 21 000 0000", "berth": "F-27"},
            )
        )
        await s.commit()
        await s.refresh(job)
        return job


async def assign(
    job_id: uuid.UUID,
    org_id: uuid.UUID,
    invited_by: uuid.UUID,
    members: list[tuple[Actor, bool]] = (),
    *,
    sections: list[str] | None = None,
    status: str = "accepted",
    live_updates: bool = False,
) -> uuid.UUID:
    """An assignment (accepted by default) with ``members`` [(actor, restricted_access)]."""
    async with async_session() as s:
        a = JobAssignment(
            job_id=job_id,
            organization_id=org_id,
            status=status,
            sections=sections if sections is not None else DEFAULT_SECTIONS,
            live_updates=live_updates,
            invited_by=invited_by,
            accepted_at=utcnow() if status == "accepted" else None,
        )
        s.add(a)
        await s.flush()
        for actor, restricted in members:
            s.add(
                JobAssignmentMember(
                    assignment_id=a.id, user_id=actor.id, restricted_access=restricted, added_by=invited_by
                )
            )
        await s.commit()
        return a.id


@dataclass
class World:
    owner: Actor
    vessel_id: uuid.UUID
    job: ServiceJob
    org_a: uuid.UUID
    org_admin: Actor
    tech: Actor  # assigned, restricted access
    tech2: Actor  # member of org A, not assigned to the job
    assignment_id: uuid.UUID
    org_b: uuid.UUID
    other_tech: Actor  # member of org B (unrelated contractor)
    other_owner: Actor  # unrelated owner with their own job
    other_job: ServiceJob


async def make_world() -> World:
    owner = await create_actor("customer", full_name="Olivia Owner")
    vessel = await create_vessel(owner.id)
    job = await create_job(owner, vessel.id)
    org_admin = await create_actor("customer", full_name="Ada OrgAdmin")
    tech = await create_actor("customer", full_name="Tama Technician")
    tech2 = await create_actor("customer", full_name="Tui SecondTech")
    org_a = await create_org("Harbour Marine Services", (org_admin, "admin"), (tech, "member"), (tech2, "member"))
    # Live updates on: most tests exercise working access to the live sections. The default
    # (live updates off: content as of the published brief) is covered by
    # test_service_jobs_visibility.py, which builds its own assignment.
    assignment_id = await assign(job.id, org_a, owner.id, [(tech, True)], live_updates=True)
    other_tech = await create_actor("customer", full_name="Nikau OtherOrg")
    org_b = await create_org("Other Marine Ltd", (other_tech, "admin"))
    other_owner = await create_actor("customer", full_name="Oscar OtherOwner")
    other_vessel = await create_vessel(other_owner.id, nickname="Other Boat")
    other_job = await create_job(other_owner, other_vessel.id, title="Other owner's job")
    return World(
        owner, vessel.id, job, org_a, org_admin, tech, tech2, assignment_id, org_b, other_tech, other_owner, other_job
    )


@pytest_asyncio.fixture
async def world() -> World:
    return await make_world()
