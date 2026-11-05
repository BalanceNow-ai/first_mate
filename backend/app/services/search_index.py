"""Typesense product index: collection schema, document building, sync and search.

The HTTP boundary is a small ``httpx`` client so tests can substitute a fake transport.
Only *verified* fitment rules (confidence ≥ ``FITMENT_MIN_CONFIDENCE``) contribute
fitment keys; Typesense keys are only a pre-filter — every fit status shown to a
customer is produced by :mod:`app.services.fitment`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models.boat_db import EquipmentCategory
from app.models.product import Product, ProductCompatibility
from app.services.fitment import VesselProfile, norm
from app.services.pricing import effective_price_cents, is_on_sale

logger = logging.getLogger(__name__)

SYNC_ALL_TASK = "app.tasks.search.sync_products_to_typesense"
SYNC_ONE_TASK = "app.tasks.search.sync_product"
QUERY_BY = "name,sku,oem_part_numbers,brand,description"
FACET_FIELDS = ("category", "brand", "in_stock", "on_sale", "part_role")


class TypesenseError(RuntimeError):
    """Any failure talking to Typesense (network, HTTP status, malformed reply)."""


def collection_schema(name: str) -> dict[str, Any]:
    """CLAUDE_CODE_PROMPT §2.4 product collection, adapted to integer cents and verified fitment keys."""
    return {
        "name": name,
        "fields": [
            {"name": "name", "type": "string"},
            {"name": "description", "type": "string", "optional": True},
            {"name": "brand", "type": "string", "facet": True, "optional": True},
            {"name": "category", "type": "string", "facet": True},
            {"name": "sub_category", "type": "string", "facet": True, "optional": True},
            {"name": "price_cents", "type": "int32"},
            {"name": "effective_price_cents", "type": "int32"},
            {"name": "sku", "type": "string"},
            {"name": "in_stock", "type": "bool", "facet": True},
            {"name": "on_sale", "type": "bool", "facet": True},
            {"name": "part_role", "type": "string", "facet": True, "optional": True},
            {"name": "universal", "type": "bool", "facet": True},
            {"name": "fitment_engine_keys", "type": "string[]", "optional": True},
            {"name": "fitment_vessel_keys", "type": "string[]", "optional": True},
            {"name": "fitment_equipment_keys", "type": "string[]", "optional": True},
            {"name": "oem_part_numbers", "type": "string[]", "optional": True},
        ],
        "default_sorting_field": "effective_price_cents",
    }


def is_configured(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(settings.typesense_api_key and settings.typesense_host)


class TypesenseClient:
    """Minimal async Typesense REST client."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        collection: str,
        *,
        timeout: float = 3.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.collection = collection
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-TYPESENSE-API-KEY": api_key},
            timeout=timeout,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kwargs) -> TypesenseClient:
        s = settings or get_settings()
        return cls(
            f"{s.typesense_protocol}://{s.typesense_host}:{s.typesense_port}",
            s.typesense_api_key,
            s.typesense_collection,
            timeout=s.typesense_timeout_seconds,
            **kwargs,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> TypesenseClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def _request(self, method: str, path: str, *, ok: Iterable[int] = (200, 201), **kwargs) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise TypesenseError(f"Typesense request failed: {type(exc).__name__}") from exc
        if resp.status_code not in set(ok):
            raise TypesenseError(f"Typesense {method} {path} returned HTTP {resp.status_code}")
        return resp

    async def ensure_collection(self) -> bool:
        """Create the collection if missing. Returns True when it was created."""
        resp = await self._request("GET", f"/collections/{self.collection}", ok=(200, 404))
        if resp.status_code == 200:
            return False
        await self._request("POST", "/collections", json=collection_schema(self.collection))
        return True

    async def drop_collection(self) -> None:
        await self._request("DELETE", f"/collections/{self.collection}", ok=(200, 404))

    async def upsert(self, documents: list[dict[str, Any]]) -> int:
        if not documents:
            return 0
        body = "\n".join(json.dumps(d) for d in documents)
        resp = await self._request(
            "POST",
            f"/collections/{self.collection}/documents/import",
            params={"action": "upsert"},
            content=body.encode(),
            headers={"Content-Type": "text/plain"},
        )
        failures = []
        for line in resp.text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise TypesenseError("Malformed Typesense import response") from exc
            if not row.get("success"):
                failures.append(row.get("error", "unknown error"))
        if failures:
            raise TypesenseError(f"{len(failures)} document(s) failed to import")
        return len(documents)

    async def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            await self._request(
                "DELETE",
                f"/collections/{self.collection}/documents",
                params={"filter_by": f"id:[{','.join(chunk)}]"},
                ok=(200, 404),
            )

    async def search(self, params: dict[str, Any]) -> dict[str, Any]:
        resp = await self._request("GET", f"/collections/{self.collection}/documents/search", params=params)
        try:
            return resp.json()
        except ValueError as exc:
            raise TypesenseError("Malformed Typesense search response") from exc


# --------------------------------------------------------------------------- documents
def fitment_keys(rules: list[ProductCompatibility], slugs: dict[uuid.UUID, str]) -> dict[str, list[str]]:
    """Index keys from *verified*, sufficiently confident rules only."""
    threshold = Decimal(str(get_settings().fitment_min_confidence))
    engine: set[str] = set()
    vessel: set[str] = set()
    equipment: set[str] = set()
    for r in rules:
        if r.verification_status != "verified" or Decimal(str(r.confidence_score)) < threshold:
            continue
        if r.engine_make:
            engine.add(norm(r.engine_make))
        if r.vessel_make:
            vessel.add(norm(r.vessel_make))
        if r.equipment_category_id:
            slug = slugs.get(r.equipment_category_id, "")
            equipment.add(f"{slug.upper()}:{norm(r.equipment_make)}" if r.equipment_make else f"{slug.upper()}:*")
    return {
        "fitment_engine_keys": sorted(engine),
        "fitment_vessel_keys": sorted(vessel),
        "fitment_equipment_keys": sorted(equipment),
    }


def product_document(p: Product, rules: list[ProductCompatibility], slugs: dict[uuid.UUID, str]) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": str(p.id),
        "name": p.name,
        "category": p.category,
        "price_cents": p.price_cents,
        "effective_price_cents": effective_price_cents(p),
        "sku": p.sku,
        "in_stock": p.is_active and p.stock_quantity > 0,
        "on_sale": is_on_sale(p),
        "universal": p.fitment_scope == "universal",
        "oem_part_numbers": [str(n) for n in (p.oem_part_numbers or [])],
        **fitment_keys(rules, slugs),
    }
    for key in ("description", "brand", "sub_category", "part_role"):
        value = getattr(p, key)
        if value:
            doc[key] = value
    return doc


async def _slugs(db: AsyncSession) -> dict[uuid.UUID, str]:
    return {c.id: c.slug for c in (await db.execute(select(EquipmentCategory))).scalars()}


async def build_documents(db: AsyncSession, products: list[Product]) -> list[dict[str, Any]]:
    if not products:
        return []
    rules: dict[uuid.UUID, list[ProductCompatibility]] = defaultdict(list)
    for r in (
        await db.execute(
            select(ProductCompatibility).where(ProductCompatibility.product_id.in_([p.id for p in products]))
        )
    ).scalars():
        rules[r.product_id].append(r)
    slugs = await _slugs(db)
    return [product_document(p, rules[p.id], slugs) for p in products]


# --------------------------------------------------------------------------- sync
async def full_sync(db: AsyncSession, client: TypesenseClient | None = None) -> dict[str, Any]:
    """Ensure the collection, upsert every active product and delete inactive ones."""
    settings = get_settings()
    if client is None and not is_configured(settings):
        logger.info("Typesense sync skipped: TYPESENSE_API_KEY/TYPESENSE_HOST not configured")
        return {"status": "skipped", "reason": "typesense_not_configured"}
    own = client is None
    client = client or TypesenseClient.from_settings(settings)
    try:
        created = await client.ensure_collection()
        batch = settings.typesense_import_batch_size
        upserted = 0
        last_id: uuid.UUID | None = None
        while True:
            q = select(Product).where(Product.is_active.is_(True)).order_by(Product.id).limit(batch)
            if last_id is not None:
                q = q.where(Product.id > last_id)
            chunk = list((await db.execute(q)).scalars())
            if not chunk:
                break
            upserted += await client.upsert(await build_documents(db, chunk))
            last_id = chunk[-1].id
        inactive = [str(i) for i in (await db.execute(select(Product.id).where(Product.is_active.is_(False)))).scalars()]
        await client.delete(inactive)
        result = {"status": "ok", "created_collection": created, "upserted": upserted, "deleted": len(inactive)}
        logger.info("Typesense full sync: %s", result)
        return result
    finally:
        if own:
            await client.close()


async def sync_one(db: AsyncSession, product_id: uuid.UUID, client: TypesenseClient | None = None) -> dict[str, Any]:
    """Upsert one active product, or delete it from the index when inactive/missing."""
    settings = get_settings()
    if client is None and not is_configured(settings):
        logger.info("Typesense sync of %s skipped: not configured", product_id)
        return {"status": "skipped", "reason": "typesense_not_configured"}
    own = client is None
    client = client or TypesenseClient.from_settings(settings)
    try:
        await client.ensure_collection()
        product = await db.get(Product, product_id)
        if product is None or not product.is_active:
            await client.delete([str(product_id)])
            return {"status": "ok", "action": "deleted", "product_id": str(product_id)}
        await client.upsert(await build_documents(db, [product]))
        return {"status": "ok", "action": "upserted", "product_id": str(product_id)}
    finally:
        if own:
            await client.close()


def enqueue_product_sync(product_ids: Iterable[uuid.UUID]) -> int:
    """Queue incremental index updates. Call *after* the change is committed.

    Broker failures are logged and never propagate to the request. When Typesense is
    not configured there is nothing to keep in sync, so nothing is queued.
    """
    ids = sorted({str(i) for i in product_ids})
    if not ids:
        return 0
    if not is_configured():
        logger.debug("Search sync not queued for %d product(s): Typesense not configured", len(ids))
        return 0
    try:
        from app.celery_app import celery

        for pid in ids:
            celery.send_task(SYNC_ONE_TASK, args=[pid], retry=False, ignore_result=True)
        return len(ids)
    except Exception as exc:  # broker outage must not fail the admin request
        logger.error("Could not queue search sync for %d product(s): %s", len(ids), type(exc).__name__)
        return 0


# --------------------------------------------------------------------------- search
def _quote(value: str) -> str:
    return "`" + value.replace("`", "") + "`"


def filter_by(filters, profile: VesselProfile | None = None, compatible_only: bool = False) -> str:
    """Typesense ``filter_by`` for :class:`product_catalogue.ProductFilters`."""
    parts: list[str] = []
    if filters.category:
        parts.append(f"category:={_quote(filters.category)}")
    if filters.sub_category:
        parts.append(f"sub_category:={_quote(filters.sub_category)}")
    if filters.brand:
        parts.append(f"brand:={_quote(filters.brand)}")
    if filters.min_price_cents is not None:
        parts.append(f"effective_price_cents:>={int(filters.min_price_cents)}")
    if filters.max_price_cents is not None:
        parts.append(f"effective_price_cents:<={int(filters.max_price_cents)}")
    if filters.in_stock is not None:
        parts.append(f"in_stock:={'true' if filters.in_stock else 'false'}")
    if filters.on_sale is not None:
        parts.append(f"on_sale:={'true' if filters.on_sale else 'false'}")
    if filters.part_role:
        parts.append(f"part_role:={_quote(filters.part_role)}")
    if profile is not None and compatible_only:
        alts = ["universal:=true"]
        engines = sorted({norm(e.make) for e in profile.engines if e.make})
        if engines:
            alts.append(f"fitment_engine_keys:=[{','.join(_quote(e) for e in engines)}]")
        alts.append(f"fitment_vessel_keys:={_quote(norm(profile.make))}")
        eq_keys = {f"{f.category.upper()}:{norm(f.make)}" for f in profile.facts}
        eq_keys |= {f"{f.category.upper()}:*" for f in profile.facts}
        if eq_keys:
            alts.append(f"fitment_equipment_keys:=[{','.join(_quote(k) for k in sorted(eq_keys))}]")
        parts.append("(" + " || ".join(alts) + ")")
    return " && ".join(parts)


def parse_facets(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for facet in raw.get("facet_counts", []) or []:
        out[facet.get("field_name", "")] = [
            {"value": c.get("value"), "count": int(c.get("count", 0))} for c in facet.get("counts", [])
        ]
    return out
