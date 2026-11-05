"""Content articles via the CMS adapter: synthetic fixture, Strapi, unavailable."""

import httpx
import pytest

from app.config import get_settings
from app.services import cms

C = "/api/v1/content"


@pytest.fixture(autouse=True)
def _reset():
    cms.clear_cache()
    yield
    cms.clear_cache()
    cms.http_transport = None


async def test_local_fixture_articles_are_synthetic(client):
    body = (await client.get(f"{C}/articles")).json()
    assert body["available"] is True and body["provider"] == "local_fixture" and body["items"]
    assert all(a["title"].startswith("[SYNTHETIC]") and a["is_synthetic"] is True for a in body["items"])
    assert "body" not in body["items"][0]
    slug = body["items"][0]["slug"]
    detail = (await client.get(f"{C}/articles/{slug}")).json()
    assert detail["slug"] == slug and detail["body"]
    assert (await client.get(f"{C}/articles/does-not-exist")).status_code == 404
    safety = (await client.get(f"{C}/articles", params={"category": "safety"})).json()
    assert [a["category"] for a in safety["items"]] == ["Safety"]


async def test_unavailable_returns_no_items(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cms_provider", "disabled")
    body = (await client.get(f"{C}/articles")).json()
    assert body["available"] is False and body["items"] == []
    r = await client.get(f"{C}/articles/synthetic-safety-gear-checklist")
    assert r.status_code == 503 and r.json()["code"] == "content_unavailable"


async def test_fixture_refused_outside_local(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "app_env", "production")
    body = (await client.get(f"{C}/articles")).json()
    assert body == {"available": False, "provider": "local_fixture", "items": [], "reason": "fixture_not_permitted"}


async def test_strapi_articles(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "cms_provider", "strapi")
    monkeypatch.setattr(get_settings(), "strapi_url", "http://strapi.test")
    payload = {
        "data": [
            {
                "id": 3,
                "attributes": {
                    "slug": "antifouling-101",
                    "title": "Antifouling 101",
                    "summary": "Basics",
                    "body": "Text",
                    "publishedAt": "2026-10-01T00:00:00Z",
                },
            }
        ]
    }
    cms.http_transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=payload) if req.url.path == "/api/articles" else httpx.Response(404)
    )
    body = (await client.get(f"{C}/articles")).json()
    assert body["available"] is True and body["items"][0]["slug"] == "antifouling-101"
    assert body["items"][0]["is_synthetic"] is False
    assert (await client.get(f"{C}/articles/antifouling-101")).json()["body"] == "Text"


async def test_old_boat_make_proxies_removed(client):
    assert (await client.get(f"{C}/boat-makes")).status_code == 404
