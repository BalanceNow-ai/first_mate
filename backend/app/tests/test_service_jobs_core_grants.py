"""A2 organizations, memberships, assignments/grants and the contractor inbox (SJ-06, SJ-07, SJ-21)."""

from __future__ import annotations

import asyncio
import json
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.database import async_session
from app.main import app
from app.models.notifications import NotificationOutbox
from app.models.ops import AuditLog
from app.models.service_jobs import ContractorMembership, JobAssignment
from app.tests.conftest import create_actor, create_vessel
from app.tests.service_jobs_support import create_job, world  # noqa: F401

API = "/api/v1"
JOBS = f"{API}/service-jobs"


def idem(key: str | None = None) -> dict:
    return {"Idempotency-Key": key or f"invite-{uuid.uuid4().hex}"}


async def _audit(action: str) -> list[AuditLog]:
    async with async_session() as s:
        return list((await s.execute(select(AuditLog).where(AuditLog.action == action))).scalars())


async def _fresh_job(w):
    vessel = await create_vessel(w.owner.id, nickname="Second")
    return await create_job(w.owner, vessel.id, status="draft")


# --- Organizations and membership --------------------------------------------------------
async def test_platform_admin_provisions_orgs_and_members(client, world):  # noqa: F811
    admin = await create_actor("admin")
    newbie = await create_actor("customer", full_name="Nina Newbie")
    r = await client.post(f"{API}/contractors/organizations", json={"name": "Sea Fix Ltd"}, headers=world.owner.headers)
    assert r.status_code == 403
    r = await client.post(f"{API}/contractors/organizations", json={"name": "Sea Fix Ltd"}, headers=admin.headers)
    assert r.status_code == 201
    org_id = r.json()["id"]
    r = await client.post(
        f"{API}/contractors/organizations/{org_id}/members",
        json={"email": newbie.email, "role": "admin"},
        headers=admin.headers,
    )
    assert r.status_code == 201 and r.json()["role"] == "admin" and r.json()["verified_at"]
    r = await client.post(
        f"{API}/contractors/organizations/{org_id}/members",
        json={"email": "nobody@example.test"},
        headers=admin.headers,
    )
    assert r.status_code == 404
    me = (await client.get(f"{API}/contractors/me", headers=newbie.headers)).json()
    assert me == [
        {
            "organization_id": org_id,
            "name": "Sea Fix Ltd",
            "trading_name": None,
            "role": "admin",
            "verified_at": me[0]["verified_at"],
        }
    ]
    orgs = (await client.get(f"{API}/contractors/organizations", headers=admin.headers)).json()
    assert {o["name"] for o in orgs} >= {"Sea Fix Ltd", "Harbour Marine Services", "Other Marine Ltd"}
    assert (await client.get(f"{API}/contractors/organizations", headers=world.org_admin.headers)).status_code == 403

    # Org admins see their members; ordinary members get 403; outsiders 404.
    r = await client.get(f"{API}/contractors/organizations/{world.org_a}/members", headers=world.org_admin.headers)
    assert r.status_code == 200 and len(r.json()) == 3
    assert (
        await client.get(f"{API}/contractors/organizations/{world.org_a}/members", headers=world.tech.headers)
    ).status_code == 403
    assert (
        await client.get(f"{API}/contractors/organizations/{world.org_a}/members", headers=world.other_tech.headers)
    ).status_code == 404

    r = await client.delete(f"{API}/contractors/organizations/{org_id}/members/{newbie.id}", headers=admin.headers)
    assert r.status_code == 204
    assert (await client.get(f"{API}/contractors/me", headers=newbie.headers)).json() == []
    actions = (
        {a.action for a in await _audit("contractor_org_create")}
        | {a.action for a in await _audit("contractor_member_add")}
        | {a.action for a in await _audit("contractor_member_remove")}
    )
    assert actions == {"contractor_org_create", "contractor_member_add", "contractor_member_remove"}


async def test_directory_lists_orgs_but_grants_nothing(client, world):  # noqa: F811
    d = (await client.get(f"{API}/contractors/directory?q=harbour", headers=world.other_owner.headers)).json()
    assert [o["name"] for o in d] == ["Harbour Marine Services"]
    assert set(d[0]) == {"id", "name", "trading_name"}
    stranger = await create_actor("customer")
    # Knowing the org id and the job id gives a stranger nothing.
    assert (await client.get(f"{JOBS}/{world.job.id}", headers=stranger.headers)).status_code == 404
    r = await client.get(f"{API}/contractors/organizations/{world.org_a}/invitations", headers=stranger.headers)
    assert r.status_code == 404


async def test_membership_removal_blocks_the_next_request(client, world):  # noqa: F811
    """SJ-07: removing a member takes effect on their very next request."""
    admin = await create_actor("admin")
    url = f"{JOBS}/{world.job.id}"
    assert (await client.get(url, headers=world.tech.headers)).status_code == 200
    r = await client.delete(
        f"{API}/contractors/organizations/{world.org_a}/members/{world.tech.id}", headers=admin.headers
    )
    assert r.status_code == 204
    assert (await client.get(url, headers=world.tech.headers)).status_code == 404
    assert (await client.get(f"{url}/evidence-requests", headers=world.tech.headers)).status_code == 404
    assert (await client.get(f"{API}/contractors/me/jobs", headers=world.tech.headers)).json()["assigned"] == []
    # Re-adding the membership does not silently restore the job assignment.
    await client.post(
        f"{API}/contractors/organizations/{world.org_a}/members",
        json={"email": world.tech.email, "role": "member"},
        headers=admin.headers,
    )
    assert (await client.get(url, headers=world.tech.headers)).status_code == 404


async def test_cli_provisions_and_removes_members(world, capsys):  # noqa: F811
    from app.cli.__main__ import main

    assert await asyncio.to_thread(main, ["create-contractor-org", "Bay Rigging", "--trading-name", "BR"]) == 0
    org_id = capsys.readouterr().out.split("\t")[0]
    newbie = await create_actor("customer")
    assert await asyncio.to_thread(main, ["add-contractor-member", org_id, newbie.email, "--role", "admin"]) == 0
    assert "admin of" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["add-contractor-member", org_id, "nobody@example.test"]) == 1
    assert await asyncio.to_thread(main, ["list-contractor-orgs"]) == 0
    assert "Bay Rigging" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["remove-contractor-member", org_id, newbie.email]) == 0
    async with async_session() as s:
        m = (
            await s.execute(select(ContractorMembership).where(ContractorMembership.user_id == newbie.id))
        ).scalar_one()
        assert m.status == "removed" and m.removed_at is not None
    assert len(await _audit("contractor_member_add")) == 1 and len(await _audit("contractor_member_remove")) == 1


# --- Owner sharing ----------------------------------------------------------------------
async def test_preview_shows_exactly_what_would_be_shared(client, world):  # noqa: F811
    job = await _fresh_job(world)
    r = await client.post(
        f"{JOBS}/{job.id}/assignments/preview",
        json={"organization_id": str(world.org_b), "sections": ["summary", "access_restricted", "evidence"]},
        headers=world.owner.headers,
    )
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["organization"]["name"] == "Other Marine Ltd"
    assert [s["section"] for s in p["sections"]] == ["summary", "evidence", "access_restricted"]
    restricted = p["sections"][2]
    assert restricted["exposes"] == ["berth", "contact_phone", "gate_code"] and restricted["counts"] == {"fields": 3}
    assert "4512#" not in json.dumps(p)  # names only, never values
    assert "access_general" in p["withheld"] and "invoices" in p["withheld"]
    # Only the owner previews; unknown org → 404.
    r = await client.post(
        f"{JOBS}/{job.id}/assignments/preview",
        json={"organization_id": str(uuid.uuid4()), "sections": ["summary"]},
        headers=world.owner.headers,
    )
    assert r.status_code == 404
    r = await client.post(
        f"{JOBS}/{world.job.id}/assignments/preview",
        json={"organization_id": str(world.org_b), "sections": ["summary"]},
        headers=world.tech.headers,
    )
    assert r.status_code == 404


async def test_invite_accept_assign_members_and_inbox(client, world):  # noqa: F811
    job = await _fresh_job(world)
    body = {"organization_id": str(world.org_a), "sections": ["summary", "evidence", "access_restricted"]}
    assert (
        await client.post(f"{JOBS}/{job.id}/assignments", json=body, headers=world.owner.headers)
    ).status_code == 400
    r = await client.post(f"{JOBS}/{job.id}/assignments", json=body, headers={**world.owner.headers, **idem()})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "invited" and a["members"] == [] and a["version"] == 1
    # A second live invitation (different key) is refused.
    r = await client.post(
        f"{JOBS}/{job.id}/assignments",
        json={**body, "organization_id": str(world.org_b)},
        headers={**world.owner.headers, **idem()},
    )
    assert r.status_code == 409 and r.json()["code"] == "assignment_exists"
    # Org admins are notified (content-free).
    async with async_session() as s:
        rows = list(
            (
                await s.execute(select(NotificationOutbox).where(NotificationOutbox.user_id == world.org_admin.id))
            ).scalars()
        )
    assert rows and all(set(r.payload) == {"kind", "job_id"} for r in rows)

    # Org admin inbox: the invitation summary only — no evidence or access.
    inbox = (await client.get(f"{API}/contractors/me/jobs", headers=world.org_admin.headers)).json()
    inv = next(i for i in inbox["invitations"] if i["assignment_id"] == a["id"])
    assert inv["job_title"] == job.title and inv["inviter_first_name"] == "Olivia"
    assert set(inv) == {
        "assignment_id", "job_id", "organization_id", "status", "job_title", "vessel_make", "vessel_model",
        "sections", "live_updates", "inviter_first_name", "invited_at", "accepted_at", "version", "members",
    }  # fmt: skip
    assert "issue_description" not in json.dumps(inbox) and "4512#" not in json.dumps(inbox)
    # The admin of the invited org still cannot open the job.
    assert (await client.get(f"{JOBS}/{job.id}", headers=world.org_admin.headers)).status_code == 404
    # Members and other orgs see no invitations; members cannot accept.
    assert (await client.get(f"{API}/contractors/me/jobs", headers=world.tech.headers)).json()["invitations"] == []
    acc = f"{API}/contractors/assignments/{a['id']}/accept"
    assert (await client.post(acc, json={}, headers=world.tech.headers)).status_code == 403
    assert (await client.post(acc, json={}, headers=world.other_tech.headers)).status_code == 404
    assert (await client.post(acc, json={}, headers=world.owner.headers)).status_code == 404
    r = await client.post(acc, json={"member_user_ids": [str(world.other_tech.id)]}, headers=world.org_admin.headers)
    assert r.status_code == 422  # not a member of org A
    r = await client.post(acc, json={"member_user_ids": [str(world.tech2.id)]}, headers=world.org_admin.headers)
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert [m["user_id"] for m in r.json()["members"]] == [str(world.tech2.id)]
    assert (await client.post(acc, json={}, headers=world.org_admin.headers)).status_code == 409

    # tech2 now sees the job (sections only); tech (not on this assignment) does not.
    j = (await client.get(f"{JOBS}/{job.id}", headers=world.tech2.headers)).json()
    assert j["viewer"]["sections"] == ["summary", "evidence"]  # restricted needs the owner's per-member flag
    assert (await client.get(f"{JOBS}/{job.id}", headers=world.tech.headers)).status_code == 404
    inbox = (await client.get(f"{API}/contractors/me/jobs", headers=world.tech2.headers)).json()
    assert [x["job_id"] for x in inbox["assigned"]] == [str(job.id)]

    # Org admin puts tech on and takes tech2 off; takes effect on the next request.
    m = f"{API}/contractors/assignments/{a['id']}/members"
    assert (
        await client.post(m, json={"user_id": str(world.tech.id)}, headers=world.org_admin.headers)
    ).status_code == 200
    assert (await client.delete(f"{m}/{world.tech2.id}", headers=world.org_admin.headers)).status_code == 200
    assert (await client.get(f"{JOBS}/{job.id}", headers=world.tech2.headers)).status_code == 404
    assert (await client.get(f"{JOBS}/{job.id}", headers=world.tech.headers)).status_code == 200

    # Owner authorises tech for restricted access (audited), then tech can read it.
    url = f"{JOBS}/{job.id}/assignments/{a['id']}/members/{world.tech.id}"
    assert (await client.put(url, json={"restricted_access": True}, headers=world.tech.headers)).status_code == 404
    r = await client.put(url, json={"restricted_access": True}, headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["members"][0]["restricted_access"] is True
    assert (await client.get(f"{JOBS}/{job.id}/access/restricted", headers=world.tech.headers)).status_code == 200
    assert len(await _audit("service_job_restricted_access")) == 1
    inv_url = f"{API}/contractors/organizations/{world.org_a}/invitations?status=accepted"
    accepted = (await client.get(inv_url, headers=world.org_admin.headers)).json()
    assert {i["assignment_id"] for i in accepted} >= {a["id"]}


async def test_decline_frees_the_job_for_another_invite(client, world):  # noqa: F811
    job = await _fresh_job(world)
    a = (
        await client.post(
            f"{JOBS}/{job.id}/assignments",
            json={"organization_id": str(world.org_b), "sections": ["summary"]},
            headers={**world.owner.headers, **idem()},
        )
    ).json()
    dec = f"{API}/contractors/assignments/{a['id']}/decline"
    assert (await client.post(dec, headers=world.org_admin.headers)).status_code == 404  # org A admin
    r = await client.post(dec, headers=world.other_tech.headers)  # org B admin
    assert r.status_code == 200 and r.json()["status"] == "declined"
    r = await client.post(
        f"{JOBS}/{job.id}/assignments",
        json={"organization_id": str(world.org_a), "sections": ["summary"]},
        headers={**world.owner.headers, **idem()},
    )
    assert r.status_code == 201


async def test_double_invite_same_key_creates_one_assignment(client, world):  # noqa: F811
    """SJ-21: the same Idempotency-Key, sent twice concurrently, yields one assignment."""
    job = await _fresh_job(world)
    headers = {**world.owner.headers, **idem("invite-key-0001")}
    body = {"organization_id": str(world.org_b), "sections": ["summary", "evidence"]}
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c1,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c2,
    ):
        r1, r2 = await asyncio.gather(
            c1.post(f"{JOBS}/{job.id}/assignments", json=body, headers=headers),
            c2.post(f"{JOBS}/{job.id}/assignments", json=body, headers=headers),
        )
    assert sorted([r1.status_code, r2.status_code]) == [200, 201]
    assert r1.json()["id"] == r2.json()["id"]
    async with async_session() as s:
        n = (await s.execute(select(func.count()).where(JobAssignment.job_id == job.id))).scalar_one()
    assert n == 1
    # The same key with a different payload is a conflict, not a second invitation.
    r = await client.post(f"{JOBS}/{job.id}/assignments", json={**body, "sections": ["summary"]}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_conflict"


async def test_change_sections_revoke_and_reassign(client, world):  # noqa: F811
    base = f"{JOBS}/{world.job.id}/assignments/{world.assignment_id}"
    r = await client.patch(base, json={"expected_version": 1, "sections": ["summary"]}, headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["sections"] == ["summary"]
    assert (await client.get(f"{JOBS}/{world.job.id}/evidence-requests", headers=world.tech.headers)).status_code == 403
    r = await client.patch(base, json={"expected_version": 1, "sections": ["evidence"]}, headers=world.owner.headers)
    assert r.status_code == 409
    assert (
        await client.patch(base, json={"expected_version": 2, "sections": []}, headers=world.owner.headers)
    ).status_code == 422
    assert len(await _audit("service_job_sharing_change")) == 1

    # Revoke: the tech's very next request is refused (SJ-07).
    r = await client.post(f"{base}/revoke", json={"reason": "Found another contractor"}, headers=world.tech.headers)
    assert r.status_code == 404
    r = await client.post(f"{base}/revoke", json={"reason": "Found another contractor"}, headers=world.owner.headers)
    assert r.status_code == 200 and r.json()["status"] == "revoked" and r.json()["revoked_at"]
    for path in ("", "/evidence-requests", "/access/general", "/evidence-requests/next"):
        assert (await client.get(f"{JOBS}/{world.job.id}{path}", headers=world.tech.headers)).status_code == 404
    assert (await client.get(f"{API}/contractors/me/jobs", headers=world.tech.headers)).json()["assigned"] == []
    assert len(await _audit("service_job_revoke")) == 1
    assert (await client.post(f"{base}/revoke", json={}, headers=world.owner.headers)).status_code == 409

    # Reassign needs a live assignment; invite org B fresh, then reassign back to org A atomically.
    r = await client.post(
        f"{JOBS}/{world.job.id}/assignments",
        json={"organization_id": str(world.org_b), "sections": ["summary"]},
        headers={**world.owner.headers, **idem()},
    )
    b_id = r.json()["id"]
    r = await client.post(
        f"{JOBS}/{world.job.id}/assignments/{b_id}/reassign",
        json={"organization_id": str(world.org_a), "sections": ["summary", "evidence"]},
        headers={**world.owner.headers, **idem()},
    )
    assert r.status_code == 201 and r.json()["organization"]["id"] == str(world.org_a)
    history = (await client.get(f"{JOBS}/{world.job.id}/assignments", headers=world.owner.headers)).json()
    assert [h["status"] for h in history] == ["invited", "revoked", "revoked"]
    assert (await client.get(f"{JOBS}/{world.job.id}/assignments", headers=world.tech.headers)).status_code == 404


async def test_suspended_org_loses_access(client, world):  # noqa: F811
    admin = await create_actor("admin")
    r = await client.patch(
        f"{API}/contractors/organizations/{world.org_a}", json={"status": "suspended"}, headers=admin.headers
    )
    assert r.status_code == 200
    assert (await client.get(f"{JOBS}/{world.job.id}", headers=world.tech.headers)).status_code == 404
    assert (await client.get(f"{API}/contractors/me", headers=world.tech.headers)).json() == []
