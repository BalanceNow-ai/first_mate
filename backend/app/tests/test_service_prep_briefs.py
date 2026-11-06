"""Preparation briefs: preview, publish, contractor acknowledgement, outdating, export (SJ-08)."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.database import async_session
from app.models.notifications import NotificationOutbox
from app.models.service_jobs import EvidenceRequest, JobAssignment, ServiceJob
from app.tests.service_jobs_support import assign, world  # noqa: F401
from app.tests.test_service_prep_support import analyse, job_url, make_asset, measure, set_sections, store, synthetic  # noqa: F401


async def _preview(client, w):
    r = await client.post(job_url(w.job.id, "/briefs/preview"), headers=w.owner.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _publish(client, w, brief):
    r = await client.post(
        job_url(w.job.id, f"/briefs/{brief['id']}/publish"),
        json={"content_digest": brief["content_digest"]},
        headers=w.owner.headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_sj08_preview_publish_request_view_and_answer(client, world, store):  # noqa: F811
    async with async_session() as s:
        s.add(
            EvidenceRequest(
                job_id=world.job.id,
                requester_role="assistant",
                category="connections",
                prompt="Far end of the hose",
                reason="Both ends determine fittings",
                status="unavailable",
                unavailable_reason="cannot_safely_access",
                technician_inspection_required=True,
            )
        )
        await s.commit()
    await make_asset(world.job, synthetic("hose-marking-25mm-id"))
    await analyse(client, world.owner, world.job.id)
    await measure(
        client,
        world.owner,
        world.job.id,
        dimension="hose_external_diameter",
        component="hose",
        value_text="32",
        unit="mm",
        method="owner_caliper",
    )
    await client.post(job_url(world.job.id, "/preparation-items/suggest"), headers=world.owner.headers)

    preview = await _preview(client, world)
    content = preview["content"]
    assert preview["status"] == "preview"
    assert content["recipient"]["organization_name"] == "Harbour Marine Services"
    assert [m["name"] for m in content["recipient"]["members"]] == ["Tama Technician"]
    assert set(content["sections"]) == {"summary", "evidence", "measurements", "preparation", "access_general", "scope"}
    blob = json.dumps(content)
    # access_restricted is never in a brief, even though tech has the restricted flag.
    assert "4512#" not in blob and "+64 21 000 0000" not in blob and "F-27" not in blob
    assert content["access_general"]["marina"] == "Westhaven Marina, Pier F"
    assert content["summary"]["attribution"] == "owner_declared"
    assert content["summary"]["vessel"]["make"] == "Stabicraft"
    assert content["evidence"]["gaps"][0]["unavailable_reason"] == "cannot_safely_access"
    assert any(o["extracted_text"] == "25 mm ID" for o in content["evidence"]["observations"])
    assert content["measurements"]["current"][0]["provenance"]["badge"] == "owner_measured"
    assert {i["status"] for i in content["preparation"]["items"]} == {"suggested"}
    assert content["preparation"]["needs_site_inspection"]
    assert content["scope"]["current"] is None
    assert any("not that the diagnosis" in line for line in content["limitations"])

    # The contractor cannot see a preview.
    r = await client.get(job_url(world.job.id, f"/briefs/{preview['id']}"), headers=world.tech.headers)
    assert r.status_code == 404
    published = await _publish(client, world, preview)
    assert published["status"] == "published" and published["is_current"] and not published["outdated"]
    async with async_session() as s:
        assert (await s.get(JobAssignment, world.assignment_id)).shared_brief_id is not None
        notes = (
            await s.execute(select(NotificationOutbox).where(NotificationOutbox.user_id == world.tech.id))
        ).scalars()
        assert any(n.payload.get("kind") == "brief_published" for n in notes)

    r = await client.get(job_url(world.job.id, f"/briefs/{preview['id']}"), headers=world.tech.headers)
    assert r.status_code == 200 and r.json()["content"]["job"]["title"] == world.job.title
    listed = (await client.get(job_url(world.job.id, "/briefs"), headers=world.tech.headers)).json()
    assert [b["id"] for b in listed] == [preview["id"]] and listed[0]["content"] is None

    # Contractor: preparation incomplete — requests one specific view.
    r = await client.post(
        job_url(world.job.id, f"/briefs/{preview['id']}/acknowledgements"),
        json={
            "kind": "incomplete",
            "note": "Need the pump label",
            "requested_view": {
                "category": "label",
                "prompt": "Photograph the pump label without moving the unit",
                "reason": "Model and voltage decide the fitting",
            },
        },
        headers=world.tech.headers,
    )
    assert r.status_code == 201, r.text
    req_id = r.json()["evidence_request"]["id"]
    assert r.json()["evidence_request"]["requester_role"] == "contractor"
    r = await client.post(
        job_url(world.job.id, f"/briefs/{preview['id']}/acknowledgements"),
        json={"kind": "incomplete"},
        headers=world.tech.headers,
    )
    assert r.status_code == 422
    # The owner answers with a new photo (evidence changes) → the published brief is outdated.
    await make_asset(world.job, synthetic("pump-label"))
    async with async_session() as s:
        req = await s.get(EvidenceRequest, req_id)
        req.status = "answered"
        job = await s.get(ServiceJob, world.job.id, with_for_update=True)
        job.evidence_revision += 1  # what the media workstream's upload does via revisions.bump
        await s.commit()
    stale = (await client.get(job_url(world.job.id, f"/briefs/{preview['id']}"), headers=world.tech.headers)).json()
    assert stale["outdated"] and "evidence_changed" in stale["outdated_reasons"]
    r = await client.post(
        job_url(world.job.id, f"/briefs/{preview['id']}/acknowledgements"),
        json={"kind": "confirmed"},
        headers=world.tech.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "brief_outdated"
    # A new revision supersedes the old one; the contractor confirms that revision.
    second = await _publish(client, world, await _preview(client, world))
    assert second["revision_number"] == 2  # revision numbers count every preview of the job
    assert any(r["status"] == "answered" for r in second["content"]["evidence"]["requests"])
    old = (await client.get(job_url(world.job.id, f"/briefs/{preview['id']}"), headers=world.tech.headers)).json()
    assert old["status"] == "superseded" and not old["is_current"]
    r = await client.post(
        job_url(world.job.id, f"/briefs/{preview['id']}/acknowledgements"),
        json={"kind": "reviewed"},
        headers=world.tech.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "brief_superseded"
    r = await client.post(
        job_url(world.job.id, f"/briefs/{second['id']}/acknowledgements"),
        json={"kind": "confirmed", "note": "Preparation revision confirmed"},
        headers=world.tech.headers,
    )
    assert r.status_code == 201
    acks = (await client.get(job_url(world.job.id, f"/briefs/{second['id']}"), headers=world.owner.headers)).json()
    assert [a["kind"] for a in acks["acknowledgements"]] == ["confirmed"]


async def test_publish_requires_the_current_unchanged_preview(client, world):  # noqa: F811
    p1 = await _preview(client, world)
    p2 = await _preview(client, world)
    r = await client.post(job_url(world.job.id, f"/briefs/{p1['id']}/publish"), headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "not_a_preview"
    r = await client.post(
        job_url(world.job.id, f"/briefs/{p2['id']}/publish"),
        json={"content_digest": "0" * 64},
        headers=world.owner.headers,
    )
    assert r.status_code == 409 and r.json()["code"] == "digest_mismatch"
    await measure(
        client,
        world.owner,
        world.job.id,
        dimension="route_length",
        component="run",
        value_text="1",
        unit="m",
        method="owner_tape",
    )
    r = await client.post(job_url(world.job.id, f"/briefs/{p2['id']}/publish"), headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "preview_outdated"
    p3 = await _preview(client, world)
    await set_sections(world.assignment_id, ["summary", "preparation"])
    r = await client.post(job_url(world.job.id, f"/briefs/{p3['id']}/publish"), headers=world.owner.headers)
    assert r.status_code == 409 and r.json()["code"] == "sections_changed"
    r = await client.post(job_url(world.job.id, "/briefs/preview"), headers=world.tech.headers)
    assert r.status_code == 404  # owner-only operation


async def test_contractor_sees_only_currently_shared_sections_and_own_assignment(client, world):  # noqa: F811
    await _publish(client, world, await _preview(client, world))
    await set_sections(world.assignment_id, ["summary", "preparation"])
    brief = (await client.get(job_url(world.job.id, "/briefs"), headers=world.tech.headers)).json()[0]
    full = (await client.get(job_url(world.job.id, f"/briefs/{brief['id']}"), headers=world.tech.headers)).json()
    assert set(full["content"]["sections"]) == {"summary", "preparation"}
    assert "measurements" not in full["content"] and "access_general" not in full["content"]
    owner_view = (await client.get(job_url(world.job.id, f"/briefs/{brief['id']}"), headers=world.owner.headers)).json()
    assert "measurements" in owner_view["content"]
    # Reassignment to org B: the old brief is not theirs.
    async with async_session() as s:
        a = await s.get(JobAssignment, world.assignment_id)
        a.status = "revoked"
        await s.commit()
    await assign(world.job.id, world.org_b, world.owner.id, [(world.other_tech, False)])
    r = await client.get(job_url(world.job.id, "/briefs"), headers=world.other_tech.headers)
    assert r.status_code == 200 and r.json() == []
    r = await client.get(job_url(world.job.id, f"/briefs/{brief['id']}"), headers=world.other_tech.headers)
    assert r.status_code == 404


async def test_export_is_escaped_attachment_and_not_cached(client, world):  # noqa: F811
    async with async_session() as s:
        job = await s.get(ServiceJob, world.job.id)
        job.issue_description = '<script>alert("x")</script> =HYPERLINK("http://evil")'
        await s.commit()
    brief = await _publish(client, world, await _preview(client, world))
    for actor in (world.owner, world.tech):
        r = await client.get(job_url(world.job.id, f"/briefs/{brief['id']}/export"), headers=actor.headers)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["content-disposition"].startswith("attachment;")
        assert "default-src 'none'" in r.headers["content-security-policy"]
        assert "<script>" not in r.text and "&lt;script&gt;" in r.text
        assert "4512#" not in r.text
    for outsider in (world.tech2, world.other_tech, world.other_owner):
        r = await client.get(job_url(world.job.id, f"/briefs/{brief['id']}/export"), headers=outsider.headers)
        assert r.status_code == 404


async def test_brief_lists_only_available_job_photos_and_documents(client, world, store):  # noqa: F811
    """Review finding (p3): the brief listed every asset — an invoice document's private
    caption, uploads still pending or quarantined — for the contractor."""
    r = await client.post(
        "/api/v1/service-assets/invoice-intents",
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
    photo = await make_asset(world.job, b"photo bytes")
    document = await make_asset(world.job, b"%PDF doc", purpose="job_document", detected_type="application/pdf")
    await make_asset(world.job, b"invoice bytes", purpose="invoice", detected_type="application/pdf")
    for state in ("quarantined", "processing", "rejected", "upload_pending"):
        await make_asset(world.job, f"{state} bytes".encode(), status=state)
    brief = await _publish(client, world, await _preview(client, world))
    for actor in (world.owner, world.tech):  # the owner previews exactly what is shared
        r = await client.get(job_url(world.job.id, f"/briefs/{brief['id']}"), headers=actor.headers)
        assets = r.json()["content"]["evidence"]["assets"]
        assert {a["id"] for a in assets} == {str(photo), str(document)}
        assert all(a["status"] == "available" and a["purpose"] in ("job_photo", "job_document") for a in assets)
        assert "PRIVATE" not in r.text and "4,200" not in r.text
