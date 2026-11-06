"""Shared helpers for the workstream-B (observations, measurements, preparation, briefs,
scope) tests. Collected by pytest but holds no tests itself."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from app.database import async_session
from app.models.service_jobs import EvidenceAsset, JobAssignment
from app.services.service_jobs import observations, storage, vision

API = "/api/v1/service-jobs"


def job_url(job_id, suffix: str = "") -> str:
    return f"{API}/{job_id}{suffix}"


@pytest.fixture
def store(tmp_path):
    """A private local_fs object store in a temp dir; the vision fixture registry is reset."""
    s = storage.LocalFsStore(str(tmp_path / "objects"))
    storage.set_store(s)
    vision.clear_registered_fixtures()
    yield s
    storage.set_store(None)
    vision.clear_registered_fixtures()


def synthetic(name: str) -> bytes:
    """Bytes matching an entry in app/seed/service_fixtures/vision_fixtures.json."""
    return f"helm-synthetic-fixture:{name}".encode()


async def make_asset(
    job,
    data: bytes,
    *,
    status: str = "available",
    purpose: str = "job_photo",
    quality: dict | None = None,
    detected_type: str = "image/jpeg",
) -> uuid.UUID:
    store = storage.get_store()
    derivative_key = storage.new_key("derived")
    store.put(derivative_key, data, detected_type)
    async with async_session() as s:
        asset = EvidenceAsset(
            owner_id=job.owner_id,
            job_id=job.id,
            uploaded_by=job.owner_id,
            purpose=purpose,
            max_bytes=10 * 1024 * 1024,
            storage_key=storage.new_key("original"),
            derivative_key=derivative_key,
            detected_type=detected_type,
            sha256=vision.fixture_sha(data),
            size_bytes=len(data),
            status=status,
            quality=quality or {},
        )
        s.add(asset)
        await s.commit()
        return asset.id


async def execute(run_id) -> str:
    async with async_session() as s:
        return await observations.execute(s, uuid.UUID(str(run_id)))


async def analyse(client, actor, job_id, key: str = "analysis-key-1", **body) -> dict:
    r = await client.post(
        job_url(job_id, "/analysis"), json=body or None, headers={**actor.headers, "Idempotency-Key": key}
    )
    assert r.status_code in (200, 202), r.text
    run = r.json()
    run["final"] = await execute(run["id"])
    return run


async def set_sections(assignment_id, sections: list[str]) -> None:
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == assignment_id).values(sections=sections))
        await s.commit()


async def revoke(assignment_id) -> None:
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == assignment_id).values(status="revoked"))
        await s.commit()


async def measure(client, actor, job_id, expect: int = 201, **body) -> dict:
    r = await client.post(job_url(job_id, "/measurements"), json=body, headers=actor.headers)
    assert r.status_code == expect, r.text
    return r.json()
