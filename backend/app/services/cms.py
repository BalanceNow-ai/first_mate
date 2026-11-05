"""Content adapter: Strapi (authoritative), a local synthetic fixture, or disabled.

* ``strapi``        — REST API at ``STRAPI_URL`` with ``STRAPI_API_TOKEN``; collections
  ``signature-experiences`` and ``articles``; cached in-process for
  ``CMS_CACHE_SECONDS``. Redemption always validates against a fresh fetch.
* ``local_fixture`` — JSON under ``app/seed/cms``; local/test only. Every entry is
  titled "[SYNTHETIC] ..." and carries ``is_synthetic: true``.
* ``disabled``      — no catalogue.

When the authoritative source is unavailable the result is ``available: false`` with
no items: there are never default or invented experiences or articles.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "seed" / "cms"

# Tests replace this with an ``httpx.MockTransport`` to fake Strapi at the HTTP boundary.
http_transport: httpx.AsyncBaseTransport | None = None
_cache: dict[str, tuple[float, CatalogueResult]] = {}


@dataclass
class CatalogueResult:
    available: bool
    provider: str
    items: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"available": self.available, "provider": self.provider, "items": self.items, "reason": self.reason}


def clear_cache() -> None:
    _cache.clear()


def _unavailable(provider: str, reason: str) -> CatalogueResult:
    return CatalogueResult(available=False, provider=provider, items=[], reason=reason)


def _fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten Strapi v4 ({id, attributes}) and v5 (flat) entries."""
    attrs = entry.get("attributes")
    if isinstance(attrs, dict):
        return {"id": entry.get("id"), **attrs}
    return dict(entry)


def _media_url(value: Any) -> str | None:
    base = get_settings().strapi_url.rstrip("/")
    if isinstance(value, dict):
        data = value.get("data", value)
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict):
            url = _fields(data).get("url")
            if isinstance(url, str):
                return url if url.startswith("http") else f"{base}{url}"
    if isinstance(value, str):
        return value
    return None


def _experience(raw: dict[str, Any], synthetic: bool) -> dict[str, Any] | None:
    f = _fields(raw)
    ident = f.get("documentId") or f.get("slug") or f.get("id")
    title = f.get("title") or f.get("name")
    cost = f.get("points_cost", f.get("pointsCost"))
    if ident is None or not title or cost is None:
        return None
    try:
        cost = int(cost)
    except (TypeError, ValueError):
        return None
    return {
        "id": str(ident),
        "title": str(title),
        "description": f.get("description") or "",
        "points_cost": cost,
        "location": f.get("location"),
        "capacity": f.get("capacity"),
        "available": bool(f.get("available", True)),
        "image_url": _media_url(f.get("image")) if f.get("image") else f.get("image_url"),
        "is_synthetic": synthetic or bool(f.get("is_synthetic", False)),
    }


def _article(raw: dict[str, Any], synthetic: bool) -> dict[str, Any] | None:
    f = _fields(raw)
    slug = f.get("slug") or f.get("documentId") or f.get("id")
    title = f.get("title")
    if slug is None or not title:
        return None
    return {
        "id": str(f.get("documentId") or f.get("id") or slug),
        "slug": str(slug),
        "title": str(title),
        "summary": f.get("summary") or f.get("excerpt") or "",
        "body": f.get("body") or f.get("content") or "",
        "category": f.get("category"),
        "author": f.get("author") if isinstance(f.get("author"), str) else None,
        "published_at": f.get("publishedAt") or f.get("published_at"),
        "image_url": _media_url(f.get("image")) if f.get("image") else f.get("image_url"),
        "is_synthetic": synthetic or bool(f.get("is_synthetic", False)),
    }


def _load_fixture(name: str) -> list[dict[str, Any]]:
    data = json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))
    for entry in data:
        # Guard the fixture contract: synthetic content is always labelled.
        if not str(entry.get("title", "")).startswith("[SYNTHETIC]") or entry.get("is_synthetic") is not True:
            raise ValueError(f"CMS fixture entry {entry.get('id')} is not labelled synthetic")
    return data


async def _strapi_get(collection: str) -> list[dict[str, Any]]:
    settings = get_settings()
    url = f"{settings.strapi_url.rstrip('/')}/api/{collection}"
    headers = {"Accept": "application/json"}
    if settings.strapi_api_token:
        headers["Authorization"] = f"Bearer {settings.strapi_api_token}"
    async with httpx.AsyncClient(transport=http_transport, timeout=10.0) as client:
        resp = await client.get(url, params={"populate": "*", "pagination[pageSize]": 100}, headers=headers)
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ValueError("unexpected Strapi response shape")
    return data


async def _fetch(kind: str, fresh: bool) -> CatalogueResult:
    settings = get_settings()
    provider = settings.cms_provider
    mapper = _experience if kind == "experiences" else _article
    if provider == "disabled":
        return _unavailable(provider, "cms_disabled")
    if provider == "local_fixture":
        if not settings.is_local:
            return _unavailable(provider, "fixture_not_permitted")
        items = [m for m in (mapper(e, True) for e in _load_fixture(kind)) if m]
        return CatalogueResult(available=True, provider=provider, items=items)
    # strapi
    if not settings.strapi_url:
        return _unavailable(provider, "cms_not_configured")
    cache_key = f"{kind}:{settings.strapi_url}"
    cached = _cache.get(cache_key)
    if not fresh and cached and cached[0] > time.monotonic():
        return cached[1]
    collection = "signature-experiences" if kind == "experiences" else "articles"
    try:
        raw = await _strapi_get(collection)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Strapi %s fetch failed: %s", collection, type(exc).__name__)
        return _unavailable(provider, "cms_unreachable")
    items = [m for m in (mapper(e, False) for e in raw) if m]
    result = CatalogueResult(available=True, provider=provider, items=items)
    _cache[cache_key] = (time.monotonic() + settings.cms_cache_seconds, result)
    return result


async def fetch_experiences(fresh: bool = False) -> CatalogueResult:
    return await _fetch("experiences", fresh)


async def fetch_articles(fresh: bool = False) -> CatalogueResult:
    return await _fetch("articles", fresh)
