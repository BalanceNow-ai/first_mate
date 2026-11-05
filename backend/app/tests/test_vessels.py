"""Vessel CRUD through the canonical contract, with owner isolation."""

from app.tests.conftest import create_vessel

VESSEL = {
    "nickname": "My Stabi",
    "make": "Stabicraft",
    "model": "2050 Supercab",
    "year": 2022,
    "hull_type": "aluminium",
    "length_ft": 20.5,
    "engine_make": "Yamaha",
    "engine_model": "F150",
    "engine_hours": 120,
}


async def test_create_read_update_delete(client, customer):
    r = await client.post("/api/v1/vessels/", json=VESSEL, headers=customer.headers)
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["nickname"] == "My Stabi" and v["length_ft"] == 20.5
    assert v["is_primary"] is True  # first vessel becomes primary
    assert "name" not in v
    vid = v["id"]
    r = await client.patch(
        f"/api/v1/vessels/{vid}", json={"engine_model": "F200", "engine_year": 2023}, headers=customer.headers
    )
    assert r.status_code == 200 and r.json()["engine_model"] == "F200"
    assert len((await client.get("/api/v1/vessels/", headers=customer.headers)).json()) == 1
    assert (await client.delete(f"/api/v1/vessels/{vid}", headers=customer.headers)).status_code == 204
    assert (await client.get(f"/api/v1/vessels/{vid}", headers=customer.headers)).status_code == 404


async def test_year_and_nickname_required(client, customer):
    for missing in ("year", "nickname", "make", "model"):
        body = {k: v for k, v in VESSEL.items() if k != missing}
        assert (await client.post("/api/v1/vessels/", json=body, headers=customer.headers)).status_code == 422
    # Legacy client field name is rejected rather than silently ignored.
    bad = {**VESSEL, "name": "x"}
    assert (await client.post("/api/v1/vessels/", json=bad, headers=customer.headers)).status_code == 422


async def test_owner_isolation(client, customer, other_customer):
    theirs = await create_vessel(other_customer.id)
    for method, kwargs in (("get", {}), ("patch", {"json": {"nickname": "x"}}), ("delete", {})):
        r = await getattr(client, method)(f"/api/v1/vessels/{theirs.id}", headers=customer.headers, **kwargs)
        assert r.status_code == 404
    assert (await client.get("/api/v1/vessels/", headers=customer.headers)).json() == []


async def test_single_primary(client, customer):
    a = (await client.post("/api/v1/vessels/", json=VESSEL, headers=customer.headers)).json()
    b = (
        await client.post(
            "/api/v1/vessels/", json={**VESSEL, "nickname": "Tender", "is_primary": True}, headers=customer.headers
        )
    ).json()
    vessels = {v["id"]: v for v in (await client.get("/api/v1/vessels/", headers=customer.headers)).json()}
    assert vessels[b["id"]]["is_primary"] and not vessels[a["id"]]["is_primary"]
