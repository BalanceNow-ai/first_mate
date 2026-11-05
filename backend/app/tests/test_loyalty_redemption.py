"""Discount entitlements (single use, no double spend) and Signature Experiences."""

import asyncio

import httpx
import pytest
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.models.loyalty import DiscountEntitlement, ExperienceRedemption, PointsTransaction
from app.services import cms, loyalty
from app.tests.test_loyalty_support import balance, grant_points, make_crew

P = "/api/v1/loyalty"


@pytest.fixture(autouse=True)
def _reset_cms():
    cms.clear_cache()
    yield
    cms.clear_cache()
    cms.http_transport = None


async def test_redeem_discount_validation(client, customer):
    await grant_points(customer.id, 250)
    for pts in (0, 50, 150, 99):
        r = await client.post(f"{P}/redeem/discount", json={"points": pts}, headers=customer.headers)
        assert r.status_code == 422, pts
    r = await client.post(f"{P}/redeem/discount", json={"points": 300}, headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "insufficient_points"
    r = await client.post(
        f"{P}/redeem/discount", json={"points": 200, "user_id": str(customer.id)}, headers=customer.headers
    )
    assert r.status_code == 422  # unknown fields rejected
    r = await client.post(f"{P}/redeem/discount", json={"points": 200}, headers=customer.headers)
    assert r.status_code == 201
    ent = r.json()
    assert ent["amount_cents"] == 200 and ent["points_cost"] == 200 and ent["status"] == "issued"
    assert ent["code"].startswith("CREW-") and ent["currency"] == "NZD"
    assert await balance(customer.id) == 50


async def test_concurrent_redemptions_cannot_overspend(client, customer):
    await grant_points(customer.id, 500)
    results = await asyncio.gather(
        *(client.post(f"{P}/redeem/discount", json={"points": 200}, headers=customer.headers) for _ in range(6))
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 201, 409, 409, 409, 409]
    assert await balance(customer.id) == 100
    async with async_session() as s:
        ents = list((await s.execute(select(DiscountEntitlement))).scalars())
        debits = list(
            (await s.execute(select(PointsTransaction).where(PointsTransaction.kind == "redeem_discount"))).scalars()
        )
    assert len(ents) == 2 and len(debits) == 2 and len({e.code for e in ents}) == 2


async def test_concurrent_service_level_redemptions(customer):
    await grant_points(customer.id, 300)

    async def redeem():
        async with async_session() as s:
            try:
                await loyalty.redeem_discount(s, customer.id, 100)
                await s.commit()
                return True
            except loyalty.InsufficientPointsError:
                await s.rollback()
                return False

    outcomes = await asyncio.gather(*(redeem() for _ in range(8)))
    assert outcomes.count(True) == 3
    assert await balance(customer.id) == 0


async def test_idempotency_key_returns_same_entitlement(client, customer):
    await grant_points(customer.id, 400)
    headers = {**customer.headers, "Idempotency-Key": "redeem-1"}
    a = await client.post(f"{P}/redeem/discount", json={"points": 100}, headers=headers)
    b = await client.post(f"{P}/redeem/discount", json={"points": 100}, headers=headers)
    assert a.status_code == b.status_code == 201 and a.json()["id"] == b.json()["id"]
    assert await balance(customer.id) == 300


async def test_void_restores_points_once(client, customer, other_customer):
    await grant_points(customer.id, 300)
    ent = (await client.post(f"{P}/redeem/discount", json={"points": 300}, headers=customer.headers)).json()
    r = await client.post(f"{P}/entitlements/{ent['id']}/void", headers=other_customer.headers)
    assert r.status_code == 404  # another user's entitlement is invisible
    r = await client.post(f"{P}/entitlements/{ent['id']}/void", headers=customer.headers)
    assert r.status_code == 200 and r.json()["status"] == "voided"
    assert await balance(customer.id) == 300
    r = await client.post(f"{P}/entitlements/{ent['id']}/void", headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "entitlement_not_voidable"
    assert await balance(customer.id) == 300
    listing = (await client.get(f"{P}/entitlements", headers=customer.headers)).json()
    assert [e["status"] for e in listing] == ["voided"]


async def test_reserved_entitlement_cannot_be_voided(client, customer):
    await grant_points(customer.id, 100)
    ent = (await client.post(f"{P}/redeem/discount", json={"points": 100}, headers=customer.headers)).json()
    async with async_session() as s:
        e = await s.get(DiscountEntitlement, ent["id"])
        e.status = "reserved"  # applied at checkout by the commerce workflow
        await s.commit()
    r = await client.post(f"{P}/entitlements/{ent['id']}/void", headers=customer.headers)
    assert r.status_code == 409
    assert await balance(customer.id) == 0


async def test_crew_wallet_is_display_only(client, customer, other_customer):
    await make_crew(customer.id, other_customer.id)
    await grant_points(other_customer.id, 500)
    body = (await client.get(f"{P}/points", headers=customer.headers)).json()
    assert body["points_balance"] == 0 and body["crew_wallet_points"] == 500
    r = await client.post(f"{P}/redeem/discount", json={"points": 100}, headers=customer.headers)
    assert r.status_code == 409  # cannot spend a crew mate's points
    assert await balance(other_customer.id) == 500


# ----------------------------------------------------------------------- experiences
async def test_experiences_unavailable_has_no_defaults(client, customer, monkeypatch):
    await grant_points(customer.id, 1_000_000)
    for provider, reason in (("disabled", "cms_disabled"), ("strapi", "cms_not_configured")):
        monkeypatch.setattr(get_settings(), "cms_provider", provider)
        monkeypatch.setattr(get_settings(), "strapi_url", "")
        body = (await client.get(f"{P}/experiences", headers=customer.headers)).json()
        assert body == {"available": False, "provider": provider, "items": [], "reason": reason}
        r = await client.post(
            f"{P}/redeem/experience", json={"experience_id": "synthetic-test-day-trip"}, headers=customer.headers
        )
        assert r.status_code == 503 and r.json()["code"] == "catalogue_unavailable"
    assert await balance(customer.id) == 1_000_000
    async with async_session() as s:
        assert list((await s.execute(select(ExperienceRedemption))).scalars()) == []


async def test_strapi_unreachable_is_unavailable(client, customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "cms_provider", "strapi")
    monkeypatch.setattr(get_settings(), "strapi_url", "http://strapi.test")
    cms.http_transport = httpx.MockTransport(lambda req: httpx.Response(502))
    body = (await client.get(f"{P}/experiences", headers=customer.headers)).json()
    assert body["available"] is False and body["items"] == [] and body["reason"] == "cms_unreachable"


async def test_strapi_catalogue_and_fresh_validation(client, customer, monkeypatch):
    monkeypatch.setattr(get_settings(), "cms_provider", "strapi")
    monkeypatch.setattr(get_settings(), "strapi_url", "http://strapi.test")
    monkeypatch.setattr(get_settings(), "strapi_api_token", "strapi-test-token")
    seen = []
    catalogue = {
        "data": [
            {
                "id": 7,
                "documentId": "kingfish",
                "title": "Kingfish Masterclass",
                "points_cost": 800,
                "description": "Day on the gulf",
                "available": True,
            }
        ]
    }

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.url.path, req.headers.get("authorization")))
        return httpx.Response(200, json=catalogue)

    cms.http_transport = httpx.MockTransport(handler)
    await grant_points(customer.id, 1000)
    body = (await client.get(f"{P}/experiences", headers=customer.headers)).json()
    assert body["available"] is True and body["provider"] == "strapi"
    assert body["items"][0]["id"] == "kingfish" and body["items"][0]["is_synthetic"] is False
    assert seen[0] == ("/api/signature-experiences", "Bearer strapi-test-token")
    await client.get(f"{P}/experiences", headers=customer.headers)
    assert len(seen) == 1  # cached
    catalogue["data"][0]["available"] = False  # withdrawn in the CMS after caching
    r = await client.post(f"{P}/redeem/experience", json={"experience_id": "kingfish"}, headers=customer.headers)
    assert r.status_code == 409 and r.json()["code"] == "experience_unavailable"
    assert len(seen) == 2  # redemption validated against a fresh fetch
    assert await balance(customer.id) == 1000


async def test_local_fixture_redemption_lifecycle(client, customer, admin):
    body = (await client.get(f"{P}/experiences", headers=customer.headers)).json()
    assert body["available"] is True and body["provider"] == "local_fixture"
    assert body["items"] and all(i["title"].startswith("[SYNTHETIC]") and i["is_synthetic"] for i in body["items"])
    await grant_points(customer.id, 1200)
    r = await client.post(
        f"{P}/redeem/experience", json={"experience_id": "synthetic-sold-out"}, headers=customer.headers
    )
    assert r.status_code == 409
    r = await client.post(f"{P}/redeem/experience", json={"experience_id": "nope"}, headers=customer.headers)
    assert r.status_code == 404
    r = await client.post(
        f"{P}/redeem/experience",
        json={"experience_id": "synthetic-test-day-trip", "note": "Weekend please"},
        headers=customer.headers,
    )
    assert r.status_code == 201, r.text
    red = r.json()
    assert red["status"] == "requested" and red["points_cost"] == 500 and red["is_synthetic"] is True
    assert await balance(customer.id) == 700
    mine = (await client.get(f"{P}/redemptions", headers=customer.headers)).json()
    assert [m["id"] for m in mine] == [red["id"]]
    # Staff workflow
    assert (
        await client.post(f"{P}/admin/redemptions/{red['id']}/confirm", headers=customer.headers)
    ).status_code == 403
    r = await client.post(f"{P}/admin/redemptions/{red['id']}/fulfil", headers=admin.headers)
    assert r.status_code == 409  # must be confirmed first
    r = await client.post(
        f"{P}/admin/redemptions/{red['id']}/confirm", json={"staff_note": "Booked"}, headers=admin.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["staff_note"] == "Booked"
    r = await client.post(f"{P}/admin/redemptions/{red['id']}/fulfil", headers=admin.headers)
    assert r.status_code == 200 and r.json()["fulfilled_at"] is not None
    r = await client.post(f"{P}/admin/redemptions/{red['id']}/cancel", headers=admin.headers)
    assert r.status_code == 409  # fulfilled is final
    assert await balance(customer.id) == 700


async def test_cancel_redemption_restores_points_once(client, customer, admin):
    await grant_points(customer.id, 500)
    red = (
        await client.post(
            f"{P}/redeem/experience", json={"experience_id": "synthetic-test-day-trip"}, headers=customer.headers
        )
    ).json()
    assert await balance(customer.id) == 0
    r = await client.post(f"{P}/admin/redemptions/{red['id']}/cancel", headers=admin.headers)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert (await client.post(f"{P}/admin/redemptions/{red['id']}/cancel", headers=admin.headers)).status_code == 409
    assert await balance(customer.id) == 500
    listing = (await client.get(f"{P}/admin/redemptions", params={"status": "cancelled"}, headers=admin.headers)).json()
    assert [x["id"] for x in listing] == [red["id"]]


async def test_insufficient_points_for_experience(client, customer):
    await grant_points(customer.id, 499)
    r = await client.post(
        f"{P}/redeem/experience", json={"experience_id": "synthetic-test-day-trip"}, headers=customer.headers
    )
    assert r.status_code == 409 and r.json()["code"] == "insufficient_points"
    async with async_session() as s:
        assert list((await s.execute(select(ExperienceRedemption))).scalars()) == []


async def test_experience_redemption_is_idempotent_per_request_key(client, customer):
    await grant_points(customer.id, 100_000)
    before = await balance(customer.id)
    headers = {**customer.headers, "Idempotency-Key": "exp-req-123456"}
    body = {"experience_id": "synthetic-test-day-trip"}
    first = await client.post(f"{P}/redeem/experience", json=body, headers=headers)
    second = await client.post(f"{P}/redeem/experience", json=body, headers=headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    cost = first.json()["points_cost"]
    assert await balance(customer.id) == before - cost
    async with async_session() as s:
        assert len(list((await s.execute(select(ExperienceRedemption))).scalars())) == 1
    pts = (await client.get(f"{P}/points", headers=customer.headers)).json()
    assert pts["points_per_dollar"] == 100
