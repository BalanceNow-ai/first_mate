"""Product search: PostgreSQL ranking/facets, Typesense sync and search (fake HTTP boundary),
fallback to PostgreSQL, Celery task registration, and a live Typesense integration test."""

from __future__ import annotations

import json
import os
import uuid
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import get_settings
from app.database import async_session
from app.services import search_index
from app.tests.conftest import add_fitment_rule, create_product, create_vessel
from app.tests.test_catalogue_support import API

TS_URL = os.environ.get("TYPESENSE_TEST_URL", "http://localhost:18108")
TS_KEY = os.environ.get("TYPESENSE_TEST_API_KEY", "test-key")


class FakeTypesense:
    """In-memory stand-in for the Typesense REST API at the HTTP boundary."""

    def __init__(self, fail: bool = False):
        self.collections: dict[str, dict] = {}
        self.docs: dict[str, dict[str, dict]] = {}
        self.requests: list[tuple[str, str]] = []
        self.search_params: list[dict] = []
        self.fail = fail
        self.canned_hits: list[str] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if self.fail:
            return httpx.Response(503, json={"message": "down"})
        if request.headers.get("X-TYPESENSE-API-KEY") != "fake-key":
            return httpx.Response(401, json={"message": "Forbidden"})
        parts = request.url.path.strip("/").split("/")
        if parts == ["collections"] and request.method == "POST":
            schema = json.loads(request.content)
            self.collections[schema["name"]] = schema
            self.docs[schema["name"]] = {}
            return httpx.Response(201, json=schema)
        name = parts[1]
        if len(parts) == 2:
            if name not in self.collections:
                return httpx.Response(404, json={"message": "Not found"})
            return httpx.Response(200, json=self.collections[name])
        store = self.docs[name]
        if parts[2:] == ["documents", "import"]:
            out = []
            for line in request.content.decode().splitlines():
                doc = json.loads(line)
                store[doc["id"]] = doc
                out.append(json.dumps({"success": True}))
            return httpx.Response(200, text="\n".join(out))
        if parts[2:] == ["documents"] and request.method == "DELETE":
            flt = parse_qs(request.url.query.decode())["filter_by"][0]
            ids = flt[len("id:[") : -1].split(",")
            for i in ids:
                store.pop(i, None)
            return httpx.Response(200, json={"num_deleted": len(ids)})
        if parts[2:] == ["documents", "search"]:
            params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
            self.search_params.append(params)
            ids = self.canned_hits if self.canned_hits is not None else list(store)
            return httpx.Response(
                200,
                json={
                    "found": len(ids),
                    "hits": [{"document": {"id": i}} for i in ids],
                    "facet_counts": [{"field_name": "brand", "counts": [{"value": "FixtureParts", "count": len(ids)}]}],
                },
            )
        return httpx.Response(400, json={"message": "unexpected"})

    def client(self, collection: str = "products") -> search_index.TypesenseClient:
        return search_index.TypesenseClient(
            "http://ts.fake:8108", "fake-key", collection, transport=httpx.MockTransport(self.handler)
        )


# =========================================================================== postgres
async def test_postgres_search_ranking_facets_and_fitment(client, customer):
    exact = await create_product(
        sku="IMP-100", name="Water pump impeller", brand="FixtureParts", part_role="impeller", fitment_scope="specific"
    )
    await add_fitment_rule(exact.id)
    desc = await create_product(sku="KIT-9", name="Service kit", description="Includes an impeller", brand="Other")
    oem = await create_product(sku="X-1", name="Gasket", oem_part_numbers=["IMP-100-OEM"], brand="Other")
    await create_product(sku="Z-9", name="Unrelated anchor", brand="Other")
    r = await client.get(f"{API}/search/products", params={"q": "impeller"})
    body = r.json()
    assert r.status_code == 200 and body["engine"] == "postgres" and body["notice"] is None
    ids = [i["id"] for i in body["items"]]
    assert ids == [str(exact.id), str(desc.id)] and body["total"] == 2  # name match ranks above description
    assert {f["value"]: f["count"] for f in body["facets"]["brand"]} == {"FixtureParts": 1, "Other": 1}
    assert body["facets"]["in_stock"] == [{"value": True, "count": 2}]
    r = (await client.get(f"{API}/search/products", params={"q": "IMP-100"})).json()
    assert [i["id"] for i in r["items"]][:2] == [str(exact.id), str(oem.id)]  # SKU, then OEM number

    vessel = await create_vessel(customer.id)
    r = (
        await client.get(
            f"{API}/search/products", params={"q": "impeller", "vessel_id": str(vessel.id)}, headers=customer.headers
        )
    ).json()
    status = {i["id"]: i["fitment"]["status"] for i in r["items"]}
    assert status == {str(exact.id): "verified_fit", str(desc.id): "unknown"}
    r = (
        await client.get(
            f"{API}/search/products",
            params={"q": "impeller", "vessel_id": str(vessel.id), "compatible_only": "true"},
            headers=customer.headers,
        )
    ).json()
    assert [i["id"] for i in r["items"]] == [str(exact.id)] and r["total"] == 1
    r = (await client.get(f"{API}/search/products", params={"brand": "Other", "sort": "name"})).json()
    assert [i["name"] for i in r["items"]] == ["Gasket", "Service kit", "Unrelated anchor"]


# =========================================================================== sync (fake)
async def test_full_sync_upserts_active_and_only_verified_keys():
    fake = FakeTypesense()
    p = await create_product(sku="S-1", name="Plug", fitment_scope="specific", sale_price_cents=5000, price_cents=6290)
    await add_fitment_rule(p.id, engine_make="Yamaha", engine_model="F150")
    await add_fitment_rule(p.id, engine_make="Suzuki", engine_model="DF140", verification_status="unverified")
    await add_fitment_rule(p.id, engine_make="Honda", engine_model="BF150", confidence_score=0.5)
    await add_fitment_rule(p.id, engine_make=None, engine_model=None, vessel_make="Stabicraft")
    u = await create_product(sku="S-2", name="Zip ties", fitment_scope="universal", stock_quantity=0)
    gone = await create_product(sku="S-3", name="Old", is_active=False)
    async with async_session() as db:
        result = await search_index.full_sync(db, fake.client())
    assert result == {"status": "ok", "created_collection": True, "upserted": 2, "deleted": 1}
    schema = fake.collections["products"]
    fields = {f["name"]: f["type"] for f in schema["fields"]}
    assert fields["price_cents"] == "int32" and fields["effective_price_cents"] == "int32"
    assert {"fitment_engine_keys", "fitment_vessel_keys", "oem_part_numbers", "universal", "part_role"} <= set(fields)
    docs = fake.docs["products"]
    assert set(docs) == {str(p.id), str(u.id)} and str(gone.id) not in docs
    d = docs[str(p.id)]
    assert d["fitment_engine_keys"] == ["YAMAHA"]  # unverified and low-confidence rules excluded
    assert d["fitment_vessel_keys"] == ["STABICRAFT"]
    assert d["effective_price_cents"] == 5000 and d["price_cents"] == 6290 and d["on_sale"] is True
    assert docs[str(u.id)]["universal"] is True and docs[str(u.id)]["in_stock"] is False

    async with async_session() as db:  # second run reuses the collection
        again = await search_index.full_sync(db, fake.client())
    assert again["created_collection"] is False


async def test_sync_one_and_not_configured(monkeypatch):
    fake = FakeTypesense()
    p = await create_product(sku="ONE-1")
    async with async_session() as db:
        assert (await search_index.sync_one(db, p.id, fake.client()))["action"] == "upserted"
    assert str(p.id) in fake.docs["products"]
    async with async_session() as db:
        from sqlalchemy import update

        from app.models.product import Product

        await db.execute(update(Product).where(Product.id == p.id).values(is_active=False))
        await db.commit()
        assert (await search_index.sync_one(db, p.id, fake.client()))["action"] == "deleted"
        assert (await search_index.sync_one(db, uuid.uuid4(), fake.client()))["action"] == "deleted"
    assert fake.docs["products"] == {}
    monkeypatch.setattr(get_settings(), "typesense_api_key", "")
    async with async_session() as db:
        assert (await search_index.full_sync(db))["status"] == "skipped"
        assert (await search_index.sync_one(db, p.id))["status"] == "skipped"


def test_celery_task_names_match_schedule():
    from app.celery_app import celery
    from app.tasks import search  # noqa: F401

    assert "app.tasks.search.sync_products_to_typesense" in celery.tasks
    assert "app.tasks.search.sync_product" in celery.tasks
    assert (
        celery.conf.beat_schedule["sync-products-to-typesense"]["task"] == "app.tasks.search.sync_products_to_typesense"
    )


def test_task_runs_and_skips_when_not_configured(monkeypatch):
    from app.tasks.search import sync_products_to_typesense

    monkeypatch.setattr(get_settings(), "typesense_api_key", "")
    assert sync_products_to_typesense.run() == {"status": "skipped", "reason": "typesense_not_configured"}


def test_filter_by_mirrors_candidate_prefilter():
    from app.services.fitment import EquipmentFact, VesselProfile
    from app.services.product_catalogue import ProductFilters

    profile = VesselProfile(
        vessel_id=uuid.uuid4(),
        nickname="n",
        make="Stabi Craft",
        model="m",
        year=2022,
        facts=[EquipmentFact("engine", "Yamaha", "F150", 2022, 1, "vessel_record")],
    )
    f = search_index.filter_by(ProductFilters(brand="x`y", in_stock=True, min_price_cents=100), profile, True)
    assert "brand:=`xy`" in f and "in_stock:=true" in f and "effective_price_cents:>=100" in f
    assert (
        "universal:=true" in f and "fitment_engine_keys:=[`YAMAHA`]" in f and "fitment_vessel_keys:=`STABICRAFT`" in f
    )


# =========================================================================== search (fake)
@pytest.fixture
def typesense_backend(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "search_backend", "typesense")
    monkeypatch.setattr(settings, "typesense_api_key", "fake-key")
    fake = FakeTypesense()
    monkeypatch.setattr(
        search_index.TypesenseClient, "from_settings", classmethod(lambda cls, s=None, **k: fake.client())
    )
    return fake


async def test_typesense_search_results_pass_through_fitment(client, customer, typesense_backend):
    fake = typesense_backend
    fits = await create_product(name="Fits", fitment_scope="specific")
    await add_fitment_rule(fits.id)
    unknown = await create_product(name="Unknown fit")
    inactive = await create_product(name="Stale", is_active=False)
    vessel = await create_vessel(customer.id)
    fake.canned_hits = [str(unknown.id), str(inactive.id), str(fits.id)]
    fake.collections["products"] = search_index.collection_schema("products")
    fake.docs["products"] = {}
    r = await client.get(
        f"{API}/search/products",
        params={"q": "plug", "vessel_id": str(vessel.id), "brand": "Yamaha"},
        headers=customer.headers,
    )
    body = r.json()
    assert r.status_code == 200 and body["engine"] == "typesense"
    assert [i["id"] for i in body["items"]] == [str(unknown.id), str(fits.id)]  # stale hit dropped, index order kept
    assert [i["fitment"]["status"] for i in body["items"]] == ["unknown", "verified_fit"]
    assert body["facets"]["brand"][0]["value"] == "FixtureParts"
    params = fake.search_params[-1]
    assert params["q"] == "plug" and "brand:=`Yamaha`" in params["filter_by"]
    r = (
        await client.get(
            f"{API}/search/products",
            params={"vessel_id": str(vessel.id), "compatible_only": "true"},
            headers=customer.headers,
        )
    ).json()
    assert [i["id"] for i in r["items"]] == [str(fits.id)] and r["total"] == 1  # exact evaluation after prefilter
    assert "fitment_engine_keys" in fake.search_params[-1]["filter_by"]


async def test_typesense_failure_falls_back_to_postgres(client, typesense_backend):
    typesense_backend.fail = True
    p = await create_product(name="Bilge pump")
    r = await client.get(f"{API}/search/products", params={"q": "bilge"})
    body = r.json()
    assert r.status_code == 200 and body["engine"] == "postgres_fallback"
    assert "unavailable" in body["notice"] and [i["id"] for i in body["items"]] == [str(p.id)]


# =========================================================================== live Typesense
def _typesense_up() -> bool:
    try:
        return httpx.get(f"{TS_URL}/health", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(not _typesense_up(), reason=f"Typesense not reachable at {TS_URL}")
async def test_live_typesense_sync_and_search(client, customer, monkeypatch):
    from urllib.parse import urlparse

    url = urlparse(TS_URL)
    settings = get_settings()
    collection = f"products_test_{uuid.uuid4().hex[:8]}"
    for k, v in {
        "search_backend": "typesense",
        "typesense_api_key": TS_KEY,
        "typesense_host": url.hostname,
        "typesense_port": url.port or 8108,
        "typesense_protocol": url.scheme,
        "typesense_collection": collection,
    }.items():
        monkeypatch.setattr(settings, k, v)
    fits = await create_product(sku="LIVE-1", name="Impeller kit F150", fitment_scope="specific", brand="FixtureParts")
    await add_fitment_rule(fits.id)
    wrong = await create_product(
        sku="LIVE-2", name="Impeller kit DF140", fitment_scope="specific", brand="FixtureParts"
    )
    await add_fitment_rule(wrong.id, engine_make="Suzuki", engine_model="DF140")
    await create_product(sku="LIVE-3", name="Impeller retired", is_active=False)
    vessel = await create_vessel(customer.id)
    try:
        async with async_session() as db:
            result = await search_index.full_sync(db)
        assert result["status"] == "ok" and result["upserted"] == 2
        r = (await client.get(f"{API}/search/products", params={"q": "impeller"})).json()
        assert r["engine"] == "typesense" and {i["sku"] for i in r["items"]} == {"LIVE-1", "LIVE-2"}
        assert any(f["value"] == "FixtureParts" for f in r["facets"]["brand"])
        r = (
            await client.get(
                f"{API}/search/products",
                params={"q": "impeller", "vessel_id": str(vessel.id), "compatible_only": "true"},
                headers=customer.headers,
            )
        ).json()
        assert [i["sku"] for i in r["items"]] == ["LIVE-1"] and r["items"][0]["fitment"]["status"] == "verified_fit"
        async with async_session() as db:
            await search_index.sync_one(db, wrong.id)  # still active → upsert is idempotent
    finally:
        async with search_index.TypesenseClient.from_settings(settings) as ts:
            await ts.drop_collection()
