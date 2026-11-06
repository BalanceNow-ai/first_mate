"""Media API: intents, content receipt, limits/quotas, downloads, deletion, evidence
requests, cross-owner/org isolation (SJ-06/SJ-07), idempotency and leases (SJ-21),
retention sweeps."""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import func, select, update

from app.config import get_settings
from app.core.errors import AppError
from app.database import async_session, utcnow
from app.models.notifications import NotificationOutbox
from app.models.ops import AuditLog
from app.models.service_jobs import (
    AnalysisRun,
    EvidenceAsset,
    EvidenceRequest,
    JobAssignment,
    JobAssignmentMember,
    ModerationCase,
    ServiceJob,
)
from app.services.service_jobs import media, storage
from app.services.service_jobs.storage_s3 import S3Store
from app.tests.service_jobs_support import assign, create_job, world  # noqa: F401
from app.tests.test_service_media_support import (  # noqa: F401
    checkerboard,
    encode,
    fetch_download,
    job_intent,
    load_asset,
    media_env,
    process,
    put_content,
    scene,
    upload,
)


def photo(seed: int = 0) -> bytes:
    img = scene()
    img.putpixel((seed % 256, 0), (seed % 255, 1, 2))
    return encode(img, "JPEG", quality=95)


async def _request(job_id, requester, role="contractor") -> uuid.UUID:
    async with async_session() as s:
        req = EvidenceRequest(
            job_id=job_id,
            requested_by=requester.id,
            requester_role=role,
            category="label",
            prompt="Can you photograph the pump label without moving the unit?",
            reason="The model number decides which hose fittings fit.",
        )
        s.add(req)
        await s.commit()
        return req.id


# --------------------------------------------------------------------------- intents and receipt
async def test_owner_and_contractor_upload_flow(client, world, media_env):  # noqa: F811
    r = await job_intent(client, world.owner, world.job.id, caption="Pump label", filename="label.jpg")
    assert r.status_code == 201, r.text
    body = r.json()
    asset_id = body["asset"]["id"]
    assert body["upload"]["method"] == "PUT"
    assert body["upload"]["url"] == f"/api/v1/service-assets/{asset_id}/content"
    assert body["upload"]["max_bytes"] == get_settings().service_image_max_bytes
    assert body["asset"]["status"] == "upload_pending"
    text = r.text
    stored = await load_asset(asset_id)
    assert stored.storage_key.startswith("quarantine/") and stored.storage_key not in text
    r = await put_content(client, world.owner, asset_id, photo())
    assert r.status_code == 202 and r.json()["status"] == "quarantined"
    assert media_env.queued == [uuid.UUID(asset_id)]
    assert await process(asset_id) == "available"
    asset = (await client.get(f"/api/v1/service-assets/{asset_id}", headers=world.owner.headers)).json()
    assert asset["status"] == "available" and asset["uploaded_by_role"] == "owner"
    for forbidden in ("storage_key", "derivative_key", "sha256", "lease_token", "quarantine/", "derived/"):
        assert forbidden not in str(asset)
    # The assigned contractor (evidence section) uploads too, and sees the owner's photo.
    tech_asset = await upload(client, world.tech, world.job.id, photo(1))
    assert tech_asset["status"] == "available" and tech_asset["uploaded_by_role"] == "contractor"
    listing = (await client.get(f"/api/v1/service-jobs/{world.job.id}/assets", headers=world.tech.headers)).json()
    assert {a["id"] for a in listing["items"]} == {asset_id, tech_asset["id"]}


async def test_evidence_revision_bumps_and_request_is_answered(client, world, media_env):  # noqa: F811
    request_id = await _request(world.job.id, world.tech)
    async with async_session() as s:
        s.add(
            AnalysisRun(kind="evidence_observations", job_id=world.job.id, requested_by=world.owner.id, job_revision=0)
        )
        await s.commit()
    asset = await upload(client, world.owner, world.job.id, photo(), evidence_request_id=str(request_id))
    assert asset["status"] == "available" and asset["evidence_request_id"] == str(request_id)
    async with async_session() as s:
        req = await s.get(EvidenceRequest, request_id)
        job = await s.get(ServiceJob, world.job.id)
        run = (await s.execute(select(AnalysisRun).where(AnalysisRun.job_id == world.job.id))).scalar_one()
        outbox = (
            (
                await s.execute(
                    select(NotificationOutbox).where(
                        NotificationOutbox.idempotency_key.like("service:evidence_answered:%")
                    )
                )
            )
            .scalars()
            .all()
        )
    assert (req.status, req.answered_by) == ("answered", world.owner.id) and req.answered_at is not None
    assert job.evidence_revision == 1
    assert run.status == "superseded"  # pending analysis bound to the old revision is stale
    assert outbox and all(o.user_id == world.tech.id for o in outbox)
    assert all(set(o.payload) == {"kind", "job_id"} for o in outbox)  # content-free


async def test_evidence_request_must_belong_to_the_same_job(client, world, media_env):  # noqa: F811
    other_request = await _request(world.other_job.id, world.other_owner, role="owner")
    r = await job_intent(client, world.owner, world.job.id, evidence_request_id=str(other_request))
    assert r.status_code == 404


async def test_idempotent_intents_and_repeated_content(client, world, media_env):  # noqa: F811
    key = {"Idempotency-Key": "intent-0001-abcdef"}
    first = await job_intent(client, world.owner, world.job.id, headers=key)
    again = await job_intent(client, world.owner, world.job.id, headers=key)
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["asset"]["id"] == again.json()["asset"]["id"]
    reused = await job_intent(client, world.owner, world.job.id, headers=key, purpose="job_document")
    assert reused.status_code == 409 and reused.json()["code"] == "idempotency_key_reused"
    # The same key from another user is a different request.
    tech_first = await job_intent(client, world.tech, world.job.id, headers=key)
    assert tech_first.status_code == 201 and tech_first.json()["asset"]["id"] != first.json()["asset"]["id"]
    bad = await job_intent(client, world.owner, world.job.id, headers={"Idempotency-Key": "x"})
    assert bad.status_code == 422
    asset_id = first.json()["asset"]["id"]
    data = photo()
    assert (await put_content(client, world.owner, asset_id, data)).status_code == 202
    repeat = await put_content(client, world.owner, asset_id, data)
    assert repeat.status_code == 202 and repeat.json()["status"] == "quarantined"
    different = await put_content(client, world.owner, asset_id, photo(7))
    assert different.status_code == 409 and different.json()["code"] == "already_uploaded"
    assert media_env.queued == [uuid.UUID(asset_id)]  # queued once
    replay = await job_intent(client, world.owner, world.job.id, headers=key)
    assert replay.json()["upload"] is None  # content already received


async def test_concurrent_receipt_is_claimed_once(client, world, media_env):  # noqa: F811
    asset_id = uuid.UUID((await job_intent(client, world.owner, world.job.id)).json()["asset"]["id"])
    async with async_session() as s:
        receipt = await media.begin_receive(s, world.owner.id, asset_id, None)
    assert receipt.token is not None
    r = await put_content(client, world.owner, asset_id, photo())
    assert r.status_code == 409 and r.json()["code"] == "upload_in_progress"
    async with async_session() as s:
        asset = await media.finish_receive(s, receipt, photo(3))
    assert asset.status == "quarantined"
    # A stale receipt (its claim was lost) cannot overwrite the recorded content.
    async with async_session() as s:
        with pytest.raises(AppError):
            await media.finish_receive(s, receipt, photo(4))


async def test_sj19_oversized_body_is_refused_server_side(client, world, media_env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "service_image_max_bytes", 2000)
    r = await job_intent(client, world.owner, world.job.id, size_bytes=5000)
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"
    asset_id = (await job_intent(client, world.owner, world.job.id)).json()["asset"]["id"]
    # Declared Content-Length over the limit.
    r = await put_content(client, world.owner, asset_id, b"\xff\xd8\xff" + b"0" * 3000)
    assert r.status_code == 413
    # Chunked body without Content-Length: refused while streaming.

    async def chunks():
        for _ in range(10):
            yield b"\xff\xd8\xff" + b"0" * 500

    r = await client.put(f"/api/v1/service-assets/{asset_id}/content", content=chunks(), headers=world.owner.headers)
    assert r.status_code == 413
    stored = await load_asset(asset_id)
    assert stored.status == "upload_pending" and stored.lease_token is None  # claim released; retry allowed
    assert (await put_content(client, world.owner, asset_id, b"")).status_code == 422
    assert (await put_content(client, world.owner, asset_id, photo()[:1])).status_code == 202


async def test_expired_intent_and_wrong_uploader(client, world, media_env):  # noqa: F811
    asset_id = (await job_intent(client, world.tech, world.job.id)).json()["asset"]["id"]
    # Only the uploader may send content (the owner cannot hijack the tech's intent).
    assert (await put_content(client, world.owner, asset_id, photo())).status_code == 404
    assert (await put_content(client, world.other_owner, asset_id, photo())).status_code == 404
    async with async_session() as s:
        await s.execute(
            update(EvidenceAsset)
            .where(EvidenceAsset.id == uuid.UUID(asset_id))
            .values(upload_expires_at=utcnow() - timedelta(minutes=1))
        )
        await s.commit()
    r = await put_content(client, world.tech, asset_id, photo())
    assert r.status_code == 410 and r.json()["code"] == "upload_intent_expired"


async def test_limits_and_quotas(client, world, media_env, monkeypatch):  # noqa: F811
    settings = get_settings()
    monkeypatch.setattr(settings, "service_job_max_assets", 2)
    assert (await job_intent(client, world.owner, world.job.id)).status_code == 201
    assert (await job_intent(client, world.owner, world.job.id)).status_code == 201
    r = await job_intent(client, world.owner, world.job.id)
    assert r.status_code == 409 and r.json()["code"] == "asset_limit_reached"
    # Pending intents reserve their max_bytes against the job and the owner quota.
    monkeypatch.setattr(settings, "service_job_max_assets", 40)
    monkeypatch.setattr(settings, "service_job_max_total_bytes", 2 * settings.service_image_max_bytes + 10)
    r = await job_intent(client, world.owner, world.job.id)
    assert r.status_code == 409 and r.json()["code"] == "job_storage_limit"
    assert (await job_intent(client, world.owner, world.job.id, size_bytes=10)).status_code == 201
    monkeypatch.setattr(settings, "service_job_max_total_bytes", 250 * 1024 * 1024)
    monkeypatch.setattr(settings, "service_owner_storage_bytes", 2 * settings.service_image_max_bytes + 1000)
    r = await job_intent(client, world.owner, world.job.id, size_bytes=5000)
    assert r.status_code == 409 and r.json()["code"] == "storage_quota_exceeded"
    # The quota spans the owner's jobs and standalone invoices; another owner is unaffected.
    r = await client.post(
        "/api/v1/service-assets/invoice-intents", json={"size_bytes": 5000}, headers=world.owner.headers
    )
    assert r.status_code == 409
    assert (await job_intent(client, world.other_owner, world.other_job.id)).status_code == 201


# --------------------------------------------------------------------------- invoices
async def test_invoice_intents_are_owner_only(client, world, media_env):  # noqa: F811
    standalone = await client.post("/api/v1/service-assets/invoice-intents", json={}, headers=world.other_owner.headers)
    assert standalone.status_code == 201 and standalone.json()["asset"]["job_id"] is None
    linked = await client.post(
        "/api/v1/service-assets/invoice-intents", json={"job_id": str(world.job.id)}, headers=world.owner.headers
    )
    assert linked.status_code == 201 and linked.json()["asset"]["purpose"] == "invoice"
    for actor, job_id in ((world.owner, world.other_job.id), (world.tech, world.job.id)):
        r = await client.post(
            "/api/v1/service-assets/invoice-intents", json={"job_id": str(job_id)}, headers=actor.headers
        )
        assert r.status_code == 404
    asset_id = linked.json()["asset"]["id"]
    await put_content(client, world.owner, asset_id, photo())
    await process(asset_id)
    # Not part of the job's evidence list; the assigned contractor cannot see or fetch it.
    listing = (await client.get(f"/api/v1/service-jobs/{world.job.id}/assets", headers=world.owner.headers)).json()
    assert asset_id not in {a["id"] for a in listing["items"]}
    for actor in (world.tech, world.other_owner):
        assert (await client.get(f"/api/v1/service-assets/{asset_id}", headers=actor.headers)).status_code == 404
        r = await client.post(f"/api/v1/service-assets/{asset_id}/download-url", headers=actor.headers)
        assert r.status_code == 404
    async with async_session() as s:
        got = await media.get_invoice_asset(s, world.owner.id, uuid.UUID(asset_id))
        assert got.status == "available"
        with pytest.raises(AppError):
            await media.get_invoice_asset(s, world.tech.id, uuid.UUID(asset_id))


# --------------------------------------------------------------------------- isolation (IDOR)
async def test_cross_owner_and_org_isolation_on_every_endpoint(client, world, media_env):  # noqa: F811
    owner_asset = await upload(client, world.owner, world.job.id, photo())
    pending_id = (await job_intent(client, world.owner, world.job.id)).json()["asset"]["id"]
    outsiders = (world.tech2, world.org_admin, world.other_tech, world.other_owner)
    for actor in outsiders:
        assert (await job_intent(client, actor, world.job.id)).status_code == 404
        assert (
            await client.get(f"/api/v1/service-jobs/{world.job.id}/assets", headers=actor.headers)
        ).status_code == 404
        for asset_id in (owner_asset["id"], pending_id):
            assert (await client.get(f"/api/v1/service-assets/{asset_id}", headers=actor.headers)).status_code == 404
            r = await client.post(f"/api/v1/service-assets/{asset_id}/download-url", headers=actor.headers)
            assert r.status_code == 404
            assert (await client.delete(f"/api/v1/service-assets/{asset_id}", headers=actor.headers)).status_code == 404
            assert (await put_content(client, actor, asset_id, photo())).status_code == 404
    # The owner cannot reach another owner's job either.
    assert (await job_intent(client, world.owner, world.other_job.id)).status_code == 404
    assert (
        await client.get(f"/api/v1/service-jobs/{world.other_job.id}/assets", headers=world.owner.headers)
    ).status_code == 404
    # The assigned contractor sees neither pending owner uploads nor other owners' media.
    assert (await client.get(f"/api/v1/service-assets/{pending_id}", headers=world.tech.headers)).status_code == 404
    other = await upload(client, world.other_owner, world.other_job.id, photo(2))
    assert (await client.get(f"/api/v1/service-assets/{other['id']}", headers=world.tech.headers)).status_code == 404
    # Unauthenticated: 401.
    assert (await client.get(f"/api/v1/service-assets/{owner_asset['id']}")).status_code == 401


async def test_contractor_needs_the_evidence_section(client, world, media_env):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, photo())
    async with async_session() as s:
        await s.execute(
            update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(sections=["summary"])
        )
        await s.commit()
    r = await client.get(f"/api/v1/service-jobs/{world.job.id}/assets", headers=world.tech.headers)
    assert r.status_code == 403 and r.json()["code"] == "section_not_shared"
    for call in (
        client.get(f"/api/v1/service-assets/{asset['id']}", headers=world.tech.headers),
        client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.tech.headers),
        job_intent(client, world.tech, world.job.id),
    ):
        assert (await call).status_code == 403


# --------------------------------------------------------------------------- SJ-07
async def test_sj07_revocation_and_reassignment_block_new_downloads(client, world, media_env):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, photo())
    pending = (await job_intent(client, world.tech, world.job.id)).json()["asset"]["id"]
    got = await fetch_download(client, world.tech, asset["id"])
    assert got.status_code == 200
    # Removing the member from the assignment: the very next request is refused.
    async with async_session() as s:
        await s.execute(
            update(JobAssignmentMember).where(JobAssignmentMember.user_id == world.tech.id).values(removed_at=utcnow())
        )
        await s.commit()
    r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.tech.headers)
    assert r.status_code == 404
    async with async_session() as s:
        await s.execute(
            update(JobAssignmentMember).where(JobAssignmentMember.user_id == world.tech.id).values(removed_at=None)
        )
        await s.commit()
    assert (
        await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.tech.headers)
    ).status_code == 200
    # Reassignment to organization B.
    async with async_session() as s:
        await s.execute(update(JobAssignment).where(JobAssignment.id == world.assignment_id).values(status="revoked"))
        await s.commit()
    await assign(world.job.id, world.org_b, world.owner.id, [(world.other_tech, False)], live_updates=True)
    for call in (
        client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.tech.headers),
        client.get(f"/api/v1/service-assets/{asset['id']}", headers=world.tech.headers),
        client.get(f"/api/v1/service-jobs/{world.job.id}/assets", headers=world.tech.headers),
    ):
        assert (await call).status_code == 404
    # The revoked contractor's unfinished upload cannot be completed.
    assert (await put_content(client, world.tech, pending, photo(5))).status_code == 404
    got = await fetch_download(client, world.other_tech, asset["id"])
    assert got.status_code == 200


async def test_sj07_local_signed_url_expires_and_is_tamper_proof(client, world, media_env, monkeypatch):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, photo())
    r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.owner.headers)
    body = r.json()
    assert body["disposition"] == "attachment" and body["variant"] == "derivative"
    q = {k: v[0] for k, v in parse_qs(urlparse(body["url"]).query).items()}
    assert 0 < int(q["e"]) - time.time() <= 300
    got = await client.get(body["url"])
    assert got.status_code == 200
    assert got.headers["content-disposition"].startswith("attachment;")
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.headers["cache-control"] == "no-store"
    base = "/api/v1/service-assets/local-download"
    expired = int(time.time()) - 1
    token = storage.sign_local(q["k"], expired, q["n"], q["c"])
    r = await client.get(base, params={**q, "e": expired, "t": token})
    assert r.status_code == 403 and r.json()["code"] == "invalid_or_expired_link"
    for tampered in ({"t": "0" * 64}, {"c": "text/html"}, {"n": "x.html"}, {"e": int(q["e"]) + 100}):
        assert (await client.get(base, params={**q, **tampered})).status_code == 403
    # Configuration cannot stretch the lifetime beyond five minutes.
    monkeypatch.setattr(get_settings(), "signed_url_seconds", 3600)
    r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.owner.headers)
    q = {k: v[0] for k, v in parse_qs(urlparse(r.json()["url"]).query).items()}
    assert int(q["e"]) - time.time() <= 300
    # Not served at all when the S3 backend is configured.
    monkeypatch.setattr(get_settings(), "object_store_backend", "s3")
    assert (await client.get(r.json()["url"])).status_code == 404


def test_sj07_s3_presigned_expiry_is_capped_at_300_seconds():
    store = S3Store(
        bucket="helm-private",
        endpoint_url="http://objectstore:7070",
        public_endpoint_url="http://localhost:18080",
        region="us-east-1",
        access_key="k",
        secret_key="s",
    )
    url = store.signed_get_url("derived/abc", filename='x"; evil.jpg', content_type="image/jpeg", seconds=3600)
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert parsed.netloc == "localhost:18080" and parsed.path == "/helm-private/derived/abc"  # path style, public host
    assert q["X-Amz-Expires"] == ["300"]
    assert q["response-content-disposition"] == ['attachment; filename="x_evil.jpg"']


# --------------------------------------------------------------------------- deletion
async def test_delete_purges_objects_and_makes_dependants_stale(client, world, media_env):  # noqa: F811
    request_id = await _request(world.job.id, world.tech)
    asset = await upload(client, world.owner, world.job.id, photo(), evidence_request_id=str(request_id))
    assert media_env.object_count() == 2  # private original + derivative (quarantine copy removed)
    async with async_session() as s:
        s.add(AnalysisRun(kind="capture_quality", job_id=world.job.id, requested_by=world.owner.id, job_revision=1))
        await s.commit()
    # The contractor cannot delete a shared (available) file.
    r = await client.delete(f"/api/v1/service-assets/{asset['id']}", headers=world.tech.headers)
    assert r.status_code == 403
    r = await client.delete(f"/api/v1/service-assets/{asset['id']}?expected_version=1", headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    r = await client.delete(f"/api/v1/service-assets/{asset['id']}", headers=world.owner.headers)
    assert r.status_code == 204
    assert media_env.object_count() == 0
    stored = await load_asset(asset["id"])
    assert (
        stored.status == "deleted" and stored.storage_key == f"deleted/{asset['id']}" and stored.derivative_key is None
    )
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        run = (await s.execute(select(AnalysisRun).where(AnalysisRun.job_id == world.job.id))).scalar_one()
        req = await s.get(EvidenceRequest, request_id)
        audited = (
            await s.execute(
                select(func.count()).select_from(AuditLog).where(AuditLog.action == "service_asset_deleted")
            )
        ).scalar_one()
    assert job.evidence_revision == 2 and run.status == "superseded"
    assert req.status == "outstanding" and req.answered_by is None
    assert audited == 1
    assert (await client.get(f"/api/v1/service-assets/{asset['id']}", headers=world.owner.headers)).status_code == 404
    r = await client.post(f"/api/v1/service-assets/{asset['id']}/download-url", headers=world.owner.headers)
    assert r.status_code == 404


async def test_uploader_may_delete_before_sharing(client, world, media_env):  # noqa: F811
    pending = (await job_intent(client, world.tech, world.job.id)).json()["asset"]["id"]
    assert (await client.delete(f"/api/v1/service-assets/{pending}", headers=world.tech.headers)).status_code == 204
    asset = await upload(client, world.tech, world.job.id, photo())
    assert (await client.delete(f"/api/v1/service-assets/{asset['id']}", headers=world.tech.headers)).status_code == 403
    assert (
        await client.delete(f"/api/v1/service-assets/{asset['id']}", headers=world.owner.headers)
    ).status_code == 204


async def test_failed_object_deletion_is_retried_by_the_sweep(client, world, media_env, monkeypatch):  # noqa: F811
    asset = await upload(client, world.owner, world.job.id, photo())
    real_delete = media_env.store.delete

    def broken(_key):
        raise storage.ObjectStoreError("down")

    monkeypatch.setattr(media_env.store, "delete", broken)
    assert (
        await client.delete(f"/api/v1/service-assets/{asset['id']}", headers=world.owner.headers)
    ).status_code == 204
    assert media_env.object_count() == 2
    monkeypatch.setattr(media_env.store, "delete", real_delete)
    async with async_session() as s:
        assert await media.sweep_deleted_objects(s) == 1
    assert media_env.object_count() == 0


# --------------------------------------------------------------------------- SJ-21 leases
async def test_sj21_lease_expiry_reclaims_and_stale_token_cannot_publish(client, world, media_env):  # noqa: F811
    asset_id = uuid.UUID((await upload(client, world.owner, world.job.id, photo(), run=False))["id"])
    async with async_session() as s:
        first = await media.claim(s, asset_id)
        assert first is not None
        assert await media.claim(s, asset_id) is None  # the lease is held
        # The first worker stalls/crashes; its lease expires.
        await s.execute(
            update(EvidenceAsset)
            .where(EvidenceAsset.id == asset_id)
            .values(lease_expires_at=utcnow() - timedelta(seconds=1))
        )
        await s.commit()
        assert await media.recoverable_assets(s) == [asset_id]
        second = await media.claim(s, asset_id)
        assert second is not None and second.token != first.token
        data = media_env.store.get(first.storage_key)
        outcome = media.analyse(data, first.purpose, first.sha256)
        assert outcome.status == "available"
        assert await media.publish_available(s, first, outcome, "original/stale", "derived/stale") == "lease_lost"
        assert await media.publish_rejection(s, first, media.Outcome("rejected", reason="x")) == "lease_lost"
        assert await media.release_for_retry(s, first, {}) == "lease_lost"
        media_env.store.put("original/fresh", data, "image/jpeg")
        media_env.store.put("derived/fresh", outcome.derivative, "image/jpeg")
        assert await media.publish_available(s, second, outcome, "original/fresh", "derived/fresh") == "available"
        assert await media.publish_available(s, second, outcome, "original/x", "derived/x") == "lease_lost"  # once
        job = await s.get(ServiceJob, world.job.id, populate_existing=True)
    stored = await load_asset(asset_id)
    assert stored.status == "available" and stored.derivative_key == "derived/fresh" and stored.attempts == 2
    assert job.evidence_revision == 1  # one publication, one bump


async def test_sj21_crashed_worker_is_recovered_by_the_sweep(client, world, media_env):  # noqa: F811
    asset_id = uuid.UUID((await upload(client, world.owner, world.job.id, photo(), run=False))["id"])
    async with async_session() as s:
        assert await media.claim(s, asset_id) is not None  # ...and the worker dies here
        assert await media.recoverable_assets(s) == []  # lease still live
        await s.execute(
            update(EvidenceAsset).where(EvidenceAsset.id == asset_id).values(lease_expires_at=utcnow() - timedelta(1))
        )
        await s.commit()
        for recovered in await media.recoverable_assets(s):
            assert await media.process_asset(s, recovered) == "available"
    assert media_env.object_count() == 2


async def test_sj21_deletion_during_processing_discards_the_result(client, world, media_env):  # noqa: F811
    asset_id = uuid.UUID((await upload(client, world.owner, world.job.id, photo(), run=False))["id"])
    async with async_session() as s:
        c = await media.claim(s, asset_id)
    assert (await client.delete(f"/api/v1/service-assets/{asset_id}", headers=world.owner.headers)).status_code == 204
    async with async_session() as s:
        outcome = media.analyse(photo(), c.purpose, c.sha256)
        assert await media.publish_available(s, c, outcome, "original/late", "derived/late") == "lease_lost"
    assert (await load_asset(asset_id)).status == "deleted"


# --------------------------------------------------------------------------- retention
async def test_abandoned_intents_are_removed(client, world, media_env):  # noqa: F811
    stale = (await job_intent(client, world.owner, world.job.id)).json()["asset"]["id"]
    fresh = (await job_intent(client, world.owner, world.job.id)).json()["asset"]["id"]
    stored = await load_asset(stale)
    media_env.store.put(stored.storage_key, b"partial", "application/octet-stream")  # bytes a crashed PUT left
    async with async_session() as s:
        await s.execute(
            update(EvidenceAsset)
            .where(EvidenceAsset.id == uuid.UUID(stale))
            .values(upload_expires_at=utcnow() - timedelta(hours=1))
        )
        await s.commit()
        assert await media.sweep_abandoned_intents(s) == 1
        remaining = (await s.execute(select(EvidenceAsset.id))).scalars().all()
    assert remaining == [uuid.UUID(fresh)]
    assert media_env.object_count() == 0


async def _age(job_id, days: int) -> None:
    async with async_session() as s:
        await s.execute(
            update(ServiceJob).where(ServiceJob.id == job_id).values(updated_at=utcnow() - timedelta(days=days))
        )
        await s.commit()


async def test_inactive_unassigned_drafts_are_noticed_then_deleted(client, world, media_env):  # noqa: F811
    draft = await create_job(world.owner, world.vessel_id, status="draft", title="Old draft")
    asset = await upload(client, world.owner, draft.id, photo())
    held = await create_job(world.owner, world.vessel_id, status="draft", retention_hold=True)
    reported = await create_job(world.owner, world.vessel_id, status="draft")
    assigned = await create_job(world.owner, world.vessel_id, status="draft")
    await assign(assigned.id, world.org_a, world.owner.id, status="invited")
    async with async_session() as s:
        s.add(ModerationCase(job_id=reported.id, reporter_id=world.owner.id, category="other", reason="dispute"))
        await s.commit()
    for job in (draft, held, reported, assigned, world.job):
        await _age(job.id, 100)
    async with async_session() as s:
        assert await media.sweep_inactive_drafts(s) == {"noticed": 1, "deleted": 0}
        assert await media.sweep_inactive_drafts(s) == {"noticed": 0, "deleted": 0}  # notice period running
        await s.execute(
            update(AuditLog)
            .where(AuditLog.action == "service_job_retention_notice")
            .values(created_at=utcnow() - timedelta(days=media.RETENTION_NOTICE_DAYS + 1))
        )
        await s.commit()
        assert await media.sweep_inactive_drafts(s) == {"noticed": 0, "deleted": 1}
        remaining = set((await s.execute(select(ServiceJob.id))).scalars())
    assert draft.id not in remaining
    assert {held.id, reported.id, assigned.id, world.job.id, world.other_job.id} <= remaining
    assert media_env.object_count() == 0
    async with async_session() as s:
        assert await s.get(EvidenceAsset, uuid.UUID(asset["id"])) is None


async def test_activity_after_the_notice_restarts_the_clock(world, media_env):  # noqa: F811
    draft = await create_job(world.owner, world.vessel_id, status="draft")
    await _age(draft.id, 100)
    async with async_session() as s:
        assert (await media.sweep_inactive_drafts(s))["noticed"] == 1
        await s.execute(
            update(AuditLog)
            .where(AuditLog.action == "service_job_retention_notice")
            .values(created_at=utcnow() - timedelta(days=200))
        )
        await s.commit()
    await _age(draft.id, 95)  # owner touched it after the notice (still past the 90 days)
    async with async_session() as s:
        assert await media.sweep_inactive_drafts(s) == {"noticed": 1, "deleted": 0}
        assert await s.get(ServiceJob, draft.id) is not None
