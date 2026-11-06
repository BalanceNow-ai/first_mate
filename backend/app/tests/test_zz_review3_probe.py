"""TEMPORARY review probes (review3) — delete after running."""

from __future__ import annotations

import asyncio
import uuid
from io import BytesIO

from sqlalchemy import select, text

from app.database import async_session, utcnow
from app.models.service_jobs import AnalysisRun, Observation, ServiceJob
from app.services.service_jobs import media, revisions, runs
from app.tests.service_jobs_support import world  # noqa: F401
from app.tests.test_service_feedback import open_window, visit
from app.tests.test_service_prep_support import job_url, make_asset, store  # noqa: F401

API = "/api/v1"


def k():
    return f"k-{uuid.uuid4().hex}"


async def test_p1_revoked_contractor_reads_new_contractors_visits(client, world):  # noqa: F811
    await open_window(client, world)  # tech (org A) records attended -> window bound to org A
    # owner reassigns to org B
    r = await client.post(
        f"{API}/service-jobs/{world.job.id}/assignments/{world.assignment_id}/reassign",
        json={"organization_id": str(world.org_b), "sections": ["summary"], "live_updates": False},
        headers={**world.owner.headers, "Idempotency-Key": k()},
    )
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]
    r = await client.post(
        f"{API}/contractors/assignments/{new_id}/accept",
        json={"member_user_ids": [str(world.other_tech.id)]},
        headers=world.other_tech.headers,
    )
    assert r.status_code == 200, r.text
    # New contractor + owner record visits with private notes
    await visit(client, world.other_tech, world.job.id, "attended", note="Org B: replaced impeller, invoice to follow")
    # Revoked org A tech: no working access
    r = await client.get(f"{API}/service-jobs/{world.job.id}", headers=world.tech.headers)
    print("A tech GET job:", r.status_code)
    r = await client.get(f"{API}/service-jobs/{world.job.id}/visits", headers=world.tech.headers)
    print("A tech GET visits:", r.status_code, [(e["kind"], e["actor_name"], e["note"]) for e in r.json()])
    ev_b = [e for e in r.json() if e["actor_name"] == "Nikau OtherOrg"]
    assert ev_b, "revoked org A sees org B's visit + note"
    # owner records a completion; revoked A tech can contest it -> job disputed
    owner_ev = await visit(client, world.owner, world.job.id, "completed", note="owner confirms")
    r = await client.post(
        f"{API}/service-jobs/{world.job.id}/visits/{owner_ev['event']['id']}/contest",
        json={"reason": "I was revoked but I can still dispute this"},
        headers={**world.tech.headers, "Idempotency-Key": k()},
    )
    print("A tech contest owner's (org B) completion:", r.status_code, r.json().get("job_disputed"))


async def test_p2_live_updates_false_not_enforced(client, world):  # noqa: F811
    async with async_session() as s:
        from app.models.service_jobs import JobAssignment

        a = await s.get(JobAssignment, world.assignment_id)
        print("live_updates:", a.live_updates, "shared_brief_id:", a.shared_brief_id)
    job = (await client.get(f"{API}/service-jobs/{world.job.id}", headers=world.owner.headers)).json()
    r = await client.patch(
        f"{API}/service-jobs/{world.job.id}",
        json={"expected_version": job["version"], "issue_description": "LATER CHANGE after sharing"},
        headers=world.owner.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"{API}/service-jobs/{world.job.id}", headers=world.tech.headers)
    print("contractor sees:", r.status_code, r.json().get("issue_description"))
    assert r.json().get("issue_description") == "LATER CHANGE after sharing"


async def test_p3_invoice_asset_caption_in_brief(client, world, store):  # noqa: F811
    r = await client.post(
        f"{API}/service-assets/invoice-intents",
        json={
            "job_id": str(world.job.id),
            "caption": "PRIVATE: other yard quoted 4,200 for this",
            "filename": "inv.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1000,
        },
        headers=world.owner.headers,
    )
    assert r.status_code == 201, r.text
    await make_asset(world.job, b"photo bytes")
    r = await client.post(job_url(world.job.id, "/briefs/preview"), headers=world.owner.headers)
    assert r.status_code == 201, r.text
    brief = r.json()
    r = await client.post(
        job_url(world.job.id, f"/briefs/{brief['id']}/publish"),
        json={"content_digest": brief["content_digest"]},
        headers=world.owner.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.get(job_url(world.job.id, f"/briefs/{brief['id']}"), headers=world.tech.headers)
    assets = r.json()["content"]["evidence"]["assets"]
    print("contractor brief assets:", [(a["purpose"], a["status"], a["caption"]) for a in assets])
    assert any(a["purpose"] == "invoice" for a in assets)


async def test_p4_deadlock_analysis_publish_vs_job_lock(world, store):  # noqa: F811
    asset_id = await make_asset(world.job, b"helm-synthetic-fixture:pump-label")
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        from app.models.service_jobs import EvidenceAsset

        a = await s.get(EvidenceAsset, asset_id)
        run, _ = await runs.create(
            s, kind="evidence_observations", requested_by=world.owner.id, job=job, assets=[a], idempotency_key=k()
        )
        await s.commit()
        run_id = run.id
    async with async_session() as s:
        token = await runs.claim(s, run_id)
    t1_has_run_lock = asyncio.Event()
    t2_has_job_lock = asyncio.Event()

    async def apply(session, published):
        t1_has_run_lock.set()
        await t2_has_job_lock.wait()
        await asyncio.sleep(0.3)  # let T2 block on the run row
        session.add(
            Observation(
                job_id=published.job_id,
                asset_id=asset_id,
                kind="label_text",
                assertion="x",
                state="model_suggested",
                analysis_run_id=published.id,
                job_revision=published.job_revision or 0,
            )
        )
        await session.flush()

    async def t1():
        async with async_session() as s:
            return await runs.publish(s, run_id, token, {"observations": []}, apply)

    async def t2():
        await t1_has_run_lock.wait()
        async with async_session() as s:
            j = (await s.execute(select(ServiceJob).where(ServiceJob.id == world.job.id).with_for_update())).scalar_one()
            t2_has_job_lock.set()
            await revisions.bump(s, j, reason="asset_available")  # what media.publish_available does
            await s.commit()
            return "t2-ok"

    res = await asyncio.gather(t1(), t2(), return_exceptions=True)
    print("deadlock probe:", [type(x).__name__ + ":" + str(x)[:160] for x in res])


def test_p5_exif_gps_stripped():
    from PIL import Image

    img = Image.new("RGB", (64, 64), (200, 10, 10))
    exif = Image.Exif()
    exif[0x010F] = "CameraMakerX"
    gps = {1: "S", 2: (36.0, 51.0, 0.0), 3: "E", 4: (174.0, 46.0, 0.0)}
    exif[0x8825] = gps
    buf = BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes(), icc_profile=b"\x00" * 128)
    out = media.process_image(buf.getvalue(), media.JPEG)
    d = Image.open(BytesIO(out.derivative))
    print("derivative info keys:", list(d.info.keys()), "exif:", dict(d.getexif()))
    assert b"CameraMakerX" not in out.derivative
    # PNG with eXIf / text chunks
    from PIL.PngImagePlugin import PngInfo

    pi = PngInfo()
    pi.add_text("Comment", "GPS 36.85S 174.76E secret")
    buf = BytesIO()
    img.save(buf, "PNG", pnginfo=pi, exif=exif.tobytes())
    out = media.process_image(buf.getvalue(), media.PNG)
    assert b"secret" not in out.derivative and b"CameraMakerX" not in out.derivative
    print("png ok")


async def test_p4b_stale_publish_when_job_lock_held(world, store):  # noqa: F811
    from app.models.service_jobs import EvidenceAsset
    from app.services.service_jobs import observations, vision

    asset_id = await make_asset(world.job, b"helm-synthetic-fixture:pump-label")
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        a = await s.get(EvidenceAsset, asset_id)
        run, _ = await runs.create(
            s, kind="evidence_observations", requested_by=world.owner.id, job=job, assets=[a], idempotency_key=k()
        )
        await s.commit()
        run_id = run.id
    async with async_session() as s:
        token = await runs.claim(s, run_id)
    obs = [vision.VisionObservation(kind="label_text", assertion="appears to read X", extracted_text="X",
                                    page=None, region=None)]
    t2_locked = asyncio.Event()

    async def t2():
        async with async_session() as s:
            j = (await s.execute(select(ServiceJob).where(ServiceJob.id == world.job.id).with_for_update())).scalar_one()
            await revisions.bump(s, j, reason="measurement_recorded")  # e.g. owner records a measurement
            t2_locked.set()
            await asyncio.sleep(0.5)
            await s.commit()

    async def t1():
        await t2_locked.wait()
        async with async_session() as s:
            async def apply(session, published):
                await observations._publish_observations(session, published, [(str(asset_id), obs)], "fixture:-")
            return await runs.publish(s, run_id, token, {"observations": []}, apply)

    res = await asyncio.gather(t1(), t2(), return_exceptions=True)
    async with async_session() as s:
        run = await s.get(AnalysisRun, run_id)
        job = await s.get(ServiceJob, world.job.id)
        n = len((await s.execute(select(Observation).where(Observation.analysis_run_id == run_id))).scalars().all())
    print("stale publish probe:", res, "run.status", run.status, "run.rev", run.job_revision, "job.rev", job.evidence_revision, "obs", n)


def _pdf_with_jpeg(jpeg: bytes) -> bytes:
    objs = []
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objs.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 64 64] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>")
    objs.append(b"<< /Type /XObject /Subtype /Image /Width 64 /Height 64 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length " + str(len(jpeg)).encode() + b" >>\nstream\n" + jpeg + b"\nendstream")
    content = b"q 64 0 0 64 0 0 cm /Im0 Do Q"
    objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_p6_pdf_embedded_jpeg_exif_survives():
    from PIL import Image

    img = Image.new("RGB", (64, 64), (10, 200, 10))
    exif = Image.Exif()
    exif[0x010F] = "CameraMakerGPSLEAK"
    exif[0x8825] = {1: "S", 2: (36.0, 51.0, 0.0), 3: "E", 4: (174.0, 46.0, 0.0)}
    buf = BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    pdf = _pdf_with_jpeg(buf.getvalue())
    out = media.process_pdf(pdf)
    print("pdf derivative keeps EXIF:", b"CameraMakerGPSLEAK" in out.derivative, b"Exif" in out.derivative)
