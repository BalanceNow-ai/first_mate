async def test_health_and_ready(client):
    assert (await client.get("/health")).json()["status"] == "healthy"
    r = await client.get("/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"]["migration"] == "0006"


async def test_public_config_exposes_no_secrets(client):
    r = await client.get("/api/v1/config/public")
    assert r.status_code == 200
    body = r.json()
    text = r.text
    assert "test-only-supabase-jwt-secret" not in text
    assert body["payments"]["local_test_mode"] is True
    methods = {m["id"]: m for m in body["payments"]["methods"]}
    assert methods["afterpay"]["enabled"] is False and methods["afterpay"]["reason"]
    assert methods["laybuy"]["enabled"] is False
