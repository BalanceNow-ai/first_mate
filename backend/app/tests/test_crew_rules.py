"""Crews: one crew per user, captain-only invites, verified-email acceptance, size cap,
expiry, removal, leaving and deterministic captain handover."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.database import async_session, utcnow
from app.models.loyalty import CrewInvite, CrewTeam, CrewTeamMember
from app.models.notifications import NotificationOutbox
from app.tests.conftest import auth_headers, create_actor

P = "/api/v1/loyalty"


async def _create(client, actor, name="Gulf Raiders"):
    r = await client.post(f"{P}/crews", json={"name": name}, headers=actor.headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _invite(client, captain, email):
    return await client.post(f"{P}/crews/mine/invites", json={"email": email}, headers=captain.headers)


async def _join(client, captain, member):
    inv = (await _invite(client, captain, member.email)).json()
    r = await client.post(f"{P}/invites/{inv['id']}/accept", headers=member.headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_and_one_crew_per_user(client, customer):
    crew = await _create(client, customer)
    assert crew["my_role"] == "captain" and crew["member_count"] == 1 and crew["max_members"] == 10
    r = await client.post(f"{P}/crews", json={"name": "Second"}, headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "already_in_crew"
    mine = (await client.get(f"{P}/crews/mine", headers=customer.headers)).json()
    assert mine["id"] == crew["id"] and mine["members"][0]["is_you"] is True


async def test_invite_accept_flow_and_notification(client, customer, other_customer):
    await _create(client, customer)
    r = await _invite(client, customer, other_customer.email.upper())
    assert r.status_code == 201 and r.json()["invited_email"] == other_customer.email
    expires = r.json()["expires_at"]
    # Invitee sees it; a third user does not.
    third = await create_actor("customer")
    assert (await client.get(f"{P}/invites", headers=third.headers)).json() == []
    mine = (await client.get(f"{P}/invites", headers=other_customer.headers)).json()
    assert len(mine) == 1 and mine[0]["crew_name"] == "Gulf Raiders" and mine[0]["expires_at"] == expires
    # Third user cannot accept someone else's invite.
    assert (await client.post(f"{P}/invites/{mine[0]['id']}/accept", headers=third.headers)).status_code == 404
    crew = (await client.post(f"{P}/invites/{mine[0]['id']}/accept", headers=other_customer.headers)).json()
    assert crew["member_count"] == 2 and crew["my_role"] == "member"
    again = await client.post(f"{P}/invites/{mine[0]['id']}/accept", headers=other_customer.headers)
    assert again.status_code == 409
    async with async_session() as s:
        rows = list(
            (await s.execute(select(NotificationOutbox).where(NotificationOutbox.template == "crew_invite"))).scalars()
        )
    assert len(rows) == 1 and rows[0].recipient == other_customer.email


async def test_only_captain_invites_and_removes(client, customer, other_customer):
    await _create(client, customer)
    await _join(client, customer, other_customer)
    r = await _invite(client, other_customer, "friend@example.test")
    assert r.status_code == 403 and r.json()["code"] == "captain_only"
    r = await client.delete(f"{P}/crews/mine/members/{customer.id}", headers=other_customer.headers)
    assert r.status_code == 403
    r = await client.delete(f"{P}/crews/mine/members/{other_customer.id}", headers=customer.headers)
    assert r.status_code == 204
    assert (await client.get(f"{P}/crews/mine", headers=other_customer.headers)).status_code == 404


async def test_email_must_match_token_principal(client, other_customer, customer):
    await _create(client, customer)
    inv = (await _invite(client, customer, other_customer.email)).json()
    spoof = auth_headers(other_customer.id, "someone-else@example.test")
    assert (await client.get(f"{P}/invites", headers=spoof)).status_code == 403
    r = await client.post(f"{P}/invites/{inv['id']}/accept", headers=spoof)
    assert r.status_code == 403 and r.json()["code"] == "email_mismatch"
    no_email = auth_headers(other_customer.id, None)
    assert (await client.post(f"{P}/invites/{inv['id']}/accept", headers=no_email)).status_code == 403


async def test_size_cap_counts_pending_invites(client, customer):
    await _create(client, customer)
    members = [await create_actor("customer") for _ in range(4)]
    for m in members:
        await _join(client, customer, m)  # 5 members
    for i in range(5):
        assert (await _invite(client, customer, f"pending{i}@example.test")).status_code == 201  # 5 pending
    r = await _invite(client, customer, "overflow@example.test")
    assert r.status_code == 409 and r.json()["code"] == "crew_full"
    # Revoking a pending invite frees a slot.
    pending = (await client.get(f"{P}/crews/mine/invites", headers=customer.headers)).json()
    assert len(pending) == 5
    assert (
        await client.delete(f"{P}/crews/mine/invites/{pending[0]['id']}", headers=customer.headers)
    ).status_code == 200
    assert (await _invite(client, customer, "overflow@example.test")).status_code == 201


async def test_duplicate_and_member_invites_rejected(client, customer, other_customer):
    await _create(client, customer)
    assert (await _invite(client, customer, customer.email)).status_code == 409
    assert (await _invite(client, customer, "x@example.test")).status_code == 201
    assert (await _invite(client, customer, "x@example.test")).json()["code"] == "invite_pending"
    await _join(client, customer, other_customer)
    assert (await _invite(client, customer, other_customer.email)).json()["code"] == "already_member"


async def test_expired_invite_cannot_be_accepted(client, customer, other_customer):
    await _create(client, customer)
    inv = (await _invite(client, customer, other_customer.email)).json()
    async with async_session() as s:
        row = await s.get(CrewInvite, inv["id"])
        assert row.expires_at - row.created_at >= timedelta(days=13, hours=23)
        row.expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    assert (await client.get(f"{P}/invites", headers=other_customer.headers)).json() == []
    r = await client.post(f"{P}/invites/{inv['id']}/accept", headers=other_customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "invite_not_pending"


async def test_member_of_another_crew_cannot_accept(client, customer, other_customer):
    await _create(client, customer)
    inv = (await _invite(client, customer, other_customer.email)).json()
    await _create(client, other_customer, "Own Crew")
    r = await client.post(f"{P}/invites/{inv['id']}/accept", headers=other_customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "already_in_crew"


async def test_concurrent_accepts_join_only_one_crew(client, other_customer):
    a, b = await create_actor("customer"), await create_actor("customer")
    await _create(client, a, "Crew A")
    await _create(client, b, "Crew B")
    ia = (await _invite(client, a, other_customer.email)).json()
    ib = (await _invite(client, b, other_customer.email)).json()
    results = await asyncio.gather(
        client.post(f"{P}/invites/{ia['id']}/accept", headers=other_customer.headers),
        client.post(f"{P}/invites/{ib['id']}/accept", headers=other_customer.headers),
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    async with async_session() as s:
        rows = list(
            (await s.execute(select(CrewTeamMember).where(CrewTeamMember.user_id == other_customer.id))).scalars()
        )
    assert len(rows) == 1


async def test_decline(client, customer, other_customer):
    await _create(client, customer)
    inv = (await _invite(client, customer, other_customer.email)).json()
    r = await client.post(f"{P}/invites/{inv['id']}/decline", headers=other_customer.headers)
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert (await client.post(f"{P}/invites/{inv['id']}/accept", headers=other_customer.headers)).status_code == 409


async def test_member_leaves_and_captain_handover_then_disband(client, customer):
    m1, m2 = await create_actor("customer"), await create_actor("customer")
    crew = await _create(client, customer)
    await _join(client, customer, m1)
    await _join(client, customer, m2)
    # Make m2 the earliest-joined non-captain so the order is not just insertion order.
    async with async_session() as s:
        row = (await s.execute(select(CrewTeamMember).where(CrewTeamMember.user_id == m2.id))).scalar_one()
        row.joined_at = utcnow() - timedelta(days=30)
        await s.commit()
    r = await client.post(f"{P}/crews/mine/leave", headers=customer.headers)
    assert r.status_code == 200 and r.json()["new_captain_id"] == str(m2.id) and r.json()["disbanded"] is False
    view = (await client.get(f"{P}/crews/mine", headers=m2.headers)).json()
    assert view["my_role"] == "captain" and view["member_count"] == 2
    # A plain member leaves.
    assert (await client.post(f"{P}/crews/mine/leave", headers=m1.headers)).json()["new_captain_id"] is None
    # The last member (captain) leaves: the crew is disbanded.
    r = await client.post(f"{P}/crews/mine/leave", headers=m2.headers)
    assert r.json()["disbanded"] is True
    async with async_session() as s:
        assert await s.get(CrewTeam, crew["id"]) is None


async def test_handover_ties_broken_by_user_id(client, customer):
    m1, m2 = await create_actor("customer"), await create_actor("customer")
    await _create(client, customer)
    await _join(client, customer, m1)
    await _join(client, customer, m2)
    same = utcnow() - timedelta(days=1)
    async with async_session() as s:
        for uid in (m1.id, m2.id):
            (await s.execute(select(CrewTeamMember).where(CrewTeamMember.user_id == uid))).scalar_one().joined_at = same
        await s.commit()
    r = await client.post(f"{P}/crews/mine/leave", headers=customer.headers)
    assert r.json()["new_captain_id"] == str(min(m1.id, m2.id, key=str))
