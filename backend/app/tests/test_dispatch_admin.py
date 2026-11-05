"""Helm Dash administration: operating areas, operator profiles, availability."""

from app.tests.conftest import create_actor
from app.tests.test_loyalty_support import make_area

D = "/api/v1/dispatch"
AREA = {"id": "tasman-bay", "name": "Tasman Bay", "center_lat": -41.1, "center_lng": 173.1, "radius_nm": 20}


async def test_area_crud_and_public_listing(client, admin, dispatcher, customer):
    assert (await client.post(f"{D}/areas", json=AREA, headers=dispatcher.headers)).status_code == 403
    r = await client.post(f"{D}/areas", json=AREA, headers=admin.headers)
    assert r.status_code == 201 and r.json()["enabled"] is False
    assert (await client.post(f"{D}/areas", json=AREA, headers=admin.headers)).status_code == 409
    assert (await client.get("/api/v1/helm-dash/areas")).json() == []  # disabled areas are hidden
    r = await client.patch(f"{D}/areas/tasman-bay", json={"enabled": True, "radius_nm": 30}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["enabled"] is True
    public = (await client.get("/api/v1/helm-dash/areas")).json()
    assert [a["id"] for a in public] == ["tasman-bay"] and public[0]["radius_nm"] == 30
    assert "enabled" not in public[0]
    assert (await client.patch(f"{D}/areas/tasman-bay", json={"name": None}, headers=admin.headers)).status_code == 422
    assert (await client.patch(f"{D}/areas/nowhere", json={"enabled": True}, headers=admin.headers)).status_code == 404
    listed = (await client.get(f"{D}/areas", headers=dispatcher.headers)).json()
    assert [a["id"] for a in listed] == ["tasman-bay"]
    assert (await client.get(f"{D}/areas", headers=customer.headers)).status_code == 403


async def test_operator_profile_requires_role_and_activation(client, admin, customer, operator):
    await make_area()
    body = {
        "user_id": str(customer.id),
        "display_name": "Casey",
        "area_id": "hauraki-gulf",
        "certification_reference": "MOSS 12345",
    }
    r = await client.post(f"{D}/operators", json=body, headers=admin.headers)
    assert r.status_code == 409 and r.json()["code"] == "role_required"
    body["user_id"] = str(operator.id)
    r = await client.post(f"{D}/operators", json=body, headers=admin.headers)
    assert r.status_code == 201
    prof = r.json()
    assert prof["active"] is False and prof["certification_reference"] == "MOSS 12345"
    assert prof["certification_verified"] is False  # recorded as unverified free text
    assert (await client.post(f"{D}/operators", json=body, headers=admin.headers)).status_code == 409
    # Inactive operators cannot go online.
    r = await client.put(f"{D}/me/availability", json={"is_online": True}, headers=operator.headers)
    assert r.status_code == 403
    assert (await client.post(f"{D}/operators/{operator.id}/activate", headers=admin.headers)).json()["active"] is True
    r = await client.put(f"{D}/me/availability", json={"is_online": True}, headers=operator.headers)
    assert r.status_code == 200 and r.json()["is_online"] is True
    assert (await client.get(f"{D}/me", headers=operator.headers)).json()["is_online"] is True
    r = await client.post(f"{D}/operators/{operator.id}/deactivate", headers=admin.headers)
    assert r.json()["active"] is False and r.json()["is_online"] is False


async def test_operator_without_profile(client):
    op = await create_actor("operator")
    r = await client.get(f"{D}/me", headers=op.headers)
    assert r.status_code == 404 and r.json()["code"] == "not_an_operator"
    assert (await client.get(f"{D}/jobs", headers=op.headers)).json() == []
