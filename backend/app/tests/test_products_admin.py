"""Admin product and fitment curation: role checks, validation, audit and search-sync queueing."""

import pytest

from app.services import search_index
from app.tests.conftest import create_product, create_vessel
from app.tests.test_catalogue_support import API, audit_actions, categories  # noqa: F401

NEW = {"sku": "ADM-1", "name": "Admin product", "category": "Engine Parts", "price_cents": 5000,
       "sale_price_cents": 4500, "stock_quantity": 3, "part_role": "impeller", "fitment_scope": "specific"}


@pytest.fixture
def queued(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(search_index, "enqueue_product_sync", lambda ids: calls.append([str(i) for i in ids]) or 1)
    return calls


async def test_non_admins_get_403(client, customer, operator, dispatcher):
    p = await create_product()
    for actor in (customer, operator, dispatcher):
        h = actor.headers
        assert (await client.post(f"{API}/products/", json=NEW, headers=h)).status_code == 403
        assert (await client.patch(f"{API}/products/{p.id}", json={"name": "x"}, headers=h)).status_code == 403
        assert (await client.post(f"{API}/products/{p.id}/stock", json={"delta": 1, "reason": "x"}, headers=h)).status_code == 403
        assert (await client.delete(f"{API}/products/{p.id}", headers=h)).status_code == 403
        assert (await client.post(f"{API}/products/{p.id}/fitment-rules", json={"engine_make": "Yamaha"}, headers=h)).status_code == 403
        assert (await client.get(f"{API}/products/admin", headers=h)).status_code == 403
        assert (await client.get(f"{API}/products/fitment-rules", headers=h)).status_code == 403
    assert (await client.post(f"{API}/products/", json=NEW)).status_code == 401
    assert await audit_actions() == []


async def test_product_create_update_stock_deactivate(client, admin, queued):
    r = await client.post(f"{API}/products/", json=NEW, headers=admin.headers)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["effective_price_cents"] == 4500 and p["cost_price_cents"] is None
    pid = p["id"]
    assert (await client.post(f"{API}/products/", json=NEW, headers=admin.headers)).status_code == 409
    bad = {**NEW, "sku": "ADM-2", "sale_price_cents": 5000}
    assert (await client.post(f"{API}/products/", json=bad, headers=admin.headers)).status_code == 422
    assert (await client.post(f"{API}/products/", json={**NEW, "sku": "ADM-3", "price": 10}, headers=admin.headers)).status_code == 422

    assert (await client.patch(f"{API}/products/{pid}", json={"price_cents": 4000}, headers=admin.headers)).status_code == 422
    r = await client.patch(f"{API}/products/{pid}", json={"sale_price_cents": None, "price_cents": 4000}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["effective_price_cents"] == 4000 and r.json()["on_sale"] is False

    r = await client.post(f"{API}/products/{pid}/stock", json={"delta": -2, "reason": "damaged"}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["stock_quantity"] == 1
    r = await client.post(f"{API}/products/{pid}/stock", json={"delta": -2, "reason": "oops"}, headers=admin.headers)
    assert r.status_code == 409 and r.json()["code"] == "insufficient_stock"
    assert (await client.post(f"{API}/products/{pid}/stock", json={"delta": 0, "reason": "x"}, headers=admin.headers)).status_code == 422

    r = await client.delete(f"{API}/products/{pid}", headers=admin.headers)
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (await client.get(f"{API}/products/{pid}")).status_code == 404
    listing = (await client.get(f"{API}/products/admin", headers=admin.headers)).json()
    assert listing["total"] == 1 and listing["items"][0]["is_active"] is False

    assert await audit_actions(pid) == ["product.create", "product.update", "product.stock_adjust", "product.deactivate"]
    assert queued == [[pid]] * 4  # one queued sync per committed change


async def test_fitment_rule_lifecycle(client, admin, customer, queued, categories):  # noqa: F811
    p = await create_product(fitment_scope="specific")
    vessel = await create_vessel(customer.id)
    body = {"engine_make": "Yamaha", "engine_model": "F150", "confidence_score": 0.5, "data_source": "dealer"}
    r = await client.post(f"{API}/products/{p.id}/fitment-rules", json=body, headers=admin.headers)
    assert r.status_code == 201, r.text
    rule = r.json()
    assert rule["verification_status"] == "unverified" and rule["confidence_score"] == 0.5
    # Smuggled verification is rejected outright.
    smuggle = {**body, "verification_status": "verified"}
    assert (await client.post(f"{API}/products/{p.id}/fitment-rules", json=smuggle, headers=admin.headers)).status_code == 422
    assert (await client.post(f"{API}/products/{p.id}/fitment-rules", json={"confidence_score": 0.9}, headers=admin.headers)).status_code == 422
    assert (await client.post(f"{API}/products/{p.id}/fitment-rules", json={"equipment_category": "nope"}, headers=admin.headers)).status_code == 422

    async def fit():
        r = await client.get(f"{API}/products/{p.id}/fitment", params={"vessel_id": str(vessel.id)}, headers=customer.headers)
        return r.json()["status"]

    assert await fit() == "unknown"
    r = await client.post(f"{API}/products/fitment-rules/{rule['id']}/verify", headers=admin.headers)
    assert r.status_code == 422 and r.json()["code"] == "confidence_too_low"
    r = await client.post(f"{API}/products/fitment-rules/{rule['id']}/verify", json={"confidence_score": 0.85}, headers=admin.headers)
    assert r.status_code == 200
    v = r.json()
    assert v["verification_status"] == "verified" and v["verified_by"] == str(admin.id) and v["verified_at"]
    assert await fit() == "verified_fit"
    queue = (await client.get(f"{API}/products/fitment-rules", params={"verification_status": "verified"}, headers=admin.headers)).json()
    assert [q["id"] for q in queue] == [rule["id"]]

    r = await client.post(f"{API}/products/fitment-rules/{rule['id']}/reject", json={"notes": "wrong engine"}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["verification_status"] == "rejected"
    assert await fit() == "unknown"

    eq = await client.post(f"{API}/products/{p.id}/fitment-rules", json={"equipment_category": "bilge_pump"}, headers=admin.headers)
    assert eq.status_code == 201 and eq.json()["equipment_category"] == "bilge_pump"
    assert len((await client.get(f"{API}/products/{p.id}/fitment-rules", headers=admin.headers)).json()) == 2

    assert (await client.delete(f"{API}/products/fitment-rules/{rule['id']}", headers=admin.headers)).status_code == 204
    assert (await client.delete(f"{API}/products/fitment-rules/{rule['id']}", headers=admin.headers)).status_code == 404
    assert await audit_actions(rule["id"]) == [
        "fitment_rule.create", "fitment_rule.verify", "fitment_rule.reject", "fitment_rule.delete"]
    assert all(c == [str(p.id)] for c in queued) and len(queued) == 5


async def test_enqueue_failure_is_logged_not_raised(monkeypatch):
    from app.config import get_settings

    errors: list[str] = []

    class SpyLogger:
        def error(self, msg, *args):
            errors.append(msg % args)

        def debug(self, *a):
            pass

    monkeypatch.setattr(search_index, "logger", SpyLogger())

    settings = get_settings()
    monkeypatch.setattr(settings, "typesense_api_key", "configured")

    class BrokenCelery:
        def send_task(self, *a, **k):
            raise ConnectionError("broker down")

    import app.celery_app

    monkeypatch.setattr(app.celery_app, "celery", BrokenCelery())
    import uuid

    assert search_index.enqueue_product_sync([uuid.uuid4()]) == 0
    assert errors and "Could not queue search sync" in errors[0]
    monkeypatch.setattr(settings, "typesense_api_key", "")
    assert search_index.enqueue_product_sync([uuid.uuid4()]) == 0  # not configured: nothing to sync
