"""Authentication, provisioning and authorization tests (no auth overrides)."""

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import Settings
from app.core.errors import AppError
from app.middleware import auth as auth_mod
from app.tests.conftest import TEST_ISSUER, TEST_JWT_SECRET, auth_headers, create_actor, make_token


async def test_missing_token_is_rejected(client):
    r = await client.get("/api/v1/auth/me")
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_token"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expires_in": -120},  # expired beyond leeway
        {"audience": "anon"},  # wrong audience
        {"issuer": "https://evil.example/auth/v1"},  # wrong issuer
        {"secret": "a-different-secret-that-is-long-enough-000"},  # forged signature
    ],
    ids=["expired", "wrong-audience", "wrong-issuer", "forged"],
)
async def test_invalid_tokens_rejected(client, customer, kwargs):
    headers = {"Authorization": f"Bearer {make_token(customer.id, customer.email, **kwargs)}"}
    r = await client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401
    # No library/exception detail leaks to the client.
    assert "Signature" not in r.text and "Traceback" not in r.text


async def test_alg_none_and_anon_key_tokens_rejected(client, customer):
    now = int(time.time())
    claims = {"sub": str(customer.id), "aud": "authenticated", "iss": TEST_ISSUER, "iat": now, "exp": now + 60}
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {unsigned}"})
    assert r.status_code == 401
    # A token signed with the *public anon key* must never verify.
    anon_signed = jwt.encode(claims, "public-anon-key-value-xxxxxxxxxxxxxxxxxxxx", algorithm="HS256")
    r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {anon_signed}"})
    assert r.status_code == 401


async def test_missing_subject_and_service_role_rejected(client):
    now = int(time.time())
    base = {"aud": "authenticated", "iss": TEST_ISSUER, "iat": now, "exp": now + 60}
    no_sub = jwt.encode(base, TEST_JWT_SECRET, algorithm="HS256")
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {no_sub}"})).status_code == 401
    svc = make_token(uuid.uuid4(), "x@example.test", extra={"role": "service_role"})
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {svc}"})).status_code == 401


async def test_provision_creates_profile_from_token_identity(client):
    sub = uuid.uuid4()
    headers = auth_headers(sub, "New.Skipper@Example.Test")
    r = await client.post("/api/v1/auth/provision", json={"full_name": "New Skipper"}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == str(sub)
    assert body["email"] == "new.skipper@example.test"
    assert body["role"] == "customer" and body["created"] is True
    # Idempotent: repeating returns the same profile with 200.
    r2 = await client.post("/api/v1/auth/provision", json={}, headers=headers)
    assert r2.status_code == 200 and r2.json()["id"] == str(sub) and r2.json()["created"] is False
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["full_name"] == "New Skipper"


async def test_provision_rejects_smuggled_identity_and_role(client, customer):
    sub = uuid.uuid4()
    headers = auth_headers(sub, "someone@example.test")
    for body in ({"id": str(customer.id)}, {"role": "admin"}, {"email": customer.email}):
        r = await client.post("/api/v1/auth/provision", json=body, headers=headers)
        assert r.status_code == 422, body
    # The deprecated /register alias also takes identity only from the token.
    r = await client.post("/api/v1/auth/register", json={"id": str(customer.id)}, headers=headers)
    assert r.status_code == 422


async def test_provision_refuses_email_bound_to_other_subject(client, customer):
    headers = auth_headers(uuid.uuid4(), customer.email.upper())
    r = await client.post("/api/v1/auth/provision", json={}, headers=headers)
    assert r.status_code == 409
    assert r.json()["code"] == "email_bound_to_other_account"


async def test_unprovisioned_token_cannot_use_api(client):
    headers = auth_headers(uuid.uuid4(), "ghost@example.test")
    r = await client.get("/api/v1/vessels/", headers=headers)
    assert r.status_code == 403
    assert r.json()["code"] == "profile_not_provisioned"


async def test_role_cannot_be_self_assigned(client, customer):
    r = await client.patch("/api/v1/users/me", json={"role": "admin"}, headers=customer.headers)
    assert r.status_code == 422
    # Role claims inside the token are ignored for authorization.
    forged_role = auth_headers(customer.id, customer.email, extra={"user_metadata": {"role": "admin"}, "app_role": "admin"})
    r = await client.get("/api/v1/admin/users", headers=forged_role)
    assert r.status_code == 403


async def test_admin_role_management_and_last_admin_guard(client, admin, customer):
    r = await client.put(f"/api/v1/admin/users/{customer.id}/role", json={"role": "dispatcher"}, headers=admin.headers)
    assert r.status_code == 200 and r.json()["role"] == "dispatcher"
    r = await client.put(f"/api/v1/admin/users/{admin.id}/role", json={"role": "customer"}, headers=admin.headers)
    assert r.status_code == 409 and r.json()["code"] == "last_admin"
    audit = await client.get("/api/v1/admin/audit", headers=admin.headers)
    assert any(a["action"] == "set_role" for a in audit.json())
    r = await client.put(f"/api/v1/admin/users/{admin.id}/role", json={"role": "customer"}, headers=customer.headers)
    assert r.status_code == 403


async def test_auth_rate_limit(client):
    headers = auth_headers(uuid.uuid4(), "burst@example.test")
    codes = [
        (await client.post("/api/v1/auth/provision", json={}, headers=headers)).status_code for _ in range(25)
    ]
    assert 429 in codes


async def test_jwks_mode_verifies_asymmetric_tokens(monkeypatch, customer):
    key = ec.generate_private_key(ec.SECP256R1())
    kid = "test-kid"
    public_jwk = jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
    public_jwk.update({"kid": kid, "alg": "ES256", "use": "sig"})
    settings = Settings(
        app_env="test", auth_mode="jwks", supabase_url="https://proj.supabase.test",
        supabase_jwt_audience="authenticated",
    )
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: {"keys": [public_jwk]})
    auth_mod._jwk_clients.clear()
    now = int(time.time())
    claims = {
        "sub": str(customer.id), "email": customer.email, "aud": "authenticated",
        "iss": "https://proj.supabase.test/auth/v1", "iat": now, "exp": now + 300, "role": "authenticated",
    }
    good = jwt.encode(claims, key, algorithm="ES256", headers={"kid": kid})
    principal = await auth_mod.verify_access_token(good, settings)
    assert principal.subject == customer.id

    other = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode(claims, other, algorithm="ES256", headers={"kid": kid})
    with pytest.raises(AppError):
        await auth_mod.verify_access_token(forged, settings)
    # HS256 tokens are refused in JWKS mode (algorithm confusion).
    hs = jwt.encode(claims, "x" * 40, algorithm="HS256", headers={"kid": kid})
    with pytest.raises(AppError):
        await auth_mod.verify_access_token(hs, settings)
    wrong_aud = jwt.encode({**claims, "aud": "other"}, key, algorithm="ES256", headers={"kid": kid})
    with pytest.raises(AppError):
        await auth_mod.verify_access_token(wrong_aud, settings)


async def test_cross_account_isolation_of_profiles(client, customer, other_customer):
    me1 = (await client.get("/api/v1/users/me", headers=customer.headers)).json()
    me2 = (await client.get("/api/v1/users/me", headers=other_customer.headers)).json()
    assert me1["id"] == str(customer.id) and me2["id"] == str(other_customer.id)


async def test_actor_helper_roles():
    a = await create_actor("operator")
    assert a.role == "operator"
