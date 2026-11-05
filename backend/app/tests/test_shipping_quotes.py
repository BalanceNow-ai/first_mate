"""Server-owned delivery quotes, options and public estimates."""

import hashlib
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.models.shipping import DeliveryQuote
from app.services.geo import haversine_nm
from app.tests.conftest import create_product
from app.tests.test_commerce_support import API, WAIHEKE, WELLINGTON, add, quote, seed_area


async def test_courier_quote_from_current_cart(client, customer):
    a = await create_product(weight_grams=1200)
    b = await create_product(weight_grams=900)
    await add(client, customer, a, 2)
    await add(client, customer, b, 1)
    r = await quote(client, customer, "courier")
    assert r.status_code == 201, r.text
    q = r.json()
    assert q["parcel_weight_grams"] == 3300 and q["price_cents"] == 1290  # <= 5000 g band
    assert q["provider"] == "development_rate_card" and q["development_rate_card"] is True
    assert q["delivery_type"] == "courier" and q["currency"] == "NZD"
    assert q["free_shipping_threshold_cents"] == get_settings().free_shipping_threshold_cents
    assert q["destination"] == {"postcode": "1010", "city": "Auckland"}
    ttl = datetime.fromisoformat(q["expires_at"]) - datetime.fromisoformat(q["created_at"])
    assert ttl == timedelta(minutes=get_settings().quote_ttl_minutes)
    expected = hashlib.sha256(",".join(sorted([f"{a.id}:2", f"{b.id}:1"])).encode()).hexdigest()
    async with async_session() as s:
        row = (
            await s.execute(select(DeliveryQuote).where(DeliveryQuote.id == q["id"]))
        ).scalar_one()
    assert row.cart_fingerprint == expected and row.user_id == customer.id


async def test_explicit_rate_card_is_not_labelled_development(client, customer, monkeypatch):
    monkeypatch.setattr(
        get_settings(), "courier_rate_card", '[{"max_grams": 10000, "price_cents": 999}]'
    )
    p = await create_product(weight_grams=9000)
    await add(client, customer, p)
    q = (await quote(client, customer)).json()
    assert (
        q["price_cents"] == 999
        and q["provider"] == "rate_card"
        and q["development_rate_card"] is False
    )


async def test_courier_refuses_unknown_weight_and_heavy_parcels(client, customer, other_customer):
    nameless = await create_product(name="Mystery Anchor", weight_grams=None)
    await add(client, customer, nameless)
    r = await quote(client, customer)
    assert r.status_code == 422 and r.json()["code"] == "weight_unknown"
    assert r.json()["products"][0]["product_id"] == str(nameless.id)

    heavy = await create_product(weight_grams=31000)
    await add(client, other_customer, heavy)
    r = await quote(client, other_customer)
    assert r.status_code == 422 and r.json()["code"] == "parcel_too_heavy"


async def test_courier_unavailable_without_rate_card(client, customer, monkeypatch):
    p = await create_product()
    await add(client, customer, p)
    monkeypatch.setattr(get_settings(), "courier_rate_mode", "disabled")
    r = await quote(client, customer)
    assert r.status_code == 503 and r.json()["code"] == "courier_unavailable"
    monkeypatch.setattr(get_settings(), "courier_rate_mode", "rate_card")
    monkeypatch.setattr(get_settings(), "app_env", "production")  # no default card in production
    r = await quote(client, customer)
    assert r.status_code == 503 and r.json()["code"] == "courier_unavailable"


async def test_dangerous_goods_cannot_be_quoted_for_restricted_types(client, customer):
    await seed_area()
    gas = await create_product(name="LPG Cylinder 4kg", dangerous_goods=True)
    await add(client, customer, gas)
    for delivery_type in ("courier", "helm_dash"):
        r = await quote(client, customer, delivery_type)
        assert r.status_code == 422 and r.json()["code"] == "dangerous_goods_restricted"
        assert "LPG Cylinder 4kg" in r.json()["detail"]


async def test_helm_dash_quote_inside_operating_area(client, customer):
    await seed_area()
    p = await create_product()
    await add(client, customer, p)
    r = await quote(client, customer, "helm_dash", WAIHEKE)
    assert r.status_code == 201, r.text
    q = r.json()
    s = get_settings()
    nm = Decimal(
        str(haversine_nm(s.warehouse_lat, s.warehouse_lng, WAIHEKE["lat"], WAIHEKE["lng"]))
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert 10 < nm < 25
    assert q["nautical_miles"] == float(nm)
    fee = s.helm_dash_base_fee_cents + int(
        (Decimal(s.helm_dash_per_nm_fee_cents) * nm).quantize(Decimal(1), ROUND_HALF_UP)
    )
    assert q["price_cents"] == fee
    eta = (
        int((nm / Decimal(str(s.helm_dash_speed_knots)) * 60).quantize(Decimal(1), ROUND_HALF_UP))
        + 15
    )
    assert q["estimated_minutes"] == eta
    assert q["operating_area_id"] == "hauraki-gulf" and q["operating_area_name"] == "Hauraki Gulf"
    assert q["provider"] == "helm_dash" and q["free_shipping_threshold_cents"] is None


async def test_helm_dash_outside_or_disabled(client, customer, monkeypatch):
    p = await create_product()
    await add(client, customer, p)
    await seed_area(
        "disabled-area", name="Bay of Islands", center_lat=-41.29, center_lng=174.78, enabled=False
    )
    r = await quote(client, customer, "helm_dash", WELLINGTON)
    assert r.status_code == 422 and r.json()["code"] == "outside_operating_area"
    await seed_area()
    r = await quote(client, customer, "helm_dash", WELLINGTON)
    assert r.status_code == 422 and r.json()["code"] == "outside_operating_area"
    monkeypatch.setattr(get_settings(), "helm_dash_enabled", False)
    r = await quote(client, customer, "helm_dash", WAIHEKE)
    assert r.status_code == 503 and r.json()["code"] == "helm_dash_unavailable"


async def test_quote_request_validation(client, customer):
    r = await quote(client, customer)
    assert r.status_code == 422 and r.json()["code"] == "cart_empty"
    p = await create_product()
    await add(client, customer, p)
    r = await quote(client, customer, "courier", WAIHEKE)
    assert r.status_code == 422 and r.json()["code"] == "invalid_destination"
    r = await quote(client, customer, "helm_dash", {"postcode": "1010"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_destination"
    r = await quote(client, customer, "courier", {"postcode": "10"})
    assert r.status_code == 422
    r = await quote(client, customer, "courier", {"postcode": "1010", "price_cents": 1})
    assert r.status_code == 422
    r = await client.post(
        f"{API}/shipping/quotes",
        json={"delivery_type": "courier", "destination": {"postcode": "1010"}},
    )
    assert r.status_code == 401


async def test_delivery_options_report_reasons(client, customer):
    await seed_area()
    plain = await create_product(weight_grams=None, name="Chart Book")
    await add(client, customer, plain)
    options = (await client.get(f"{API}/shipping/options", headers=customer.headers)).json()
    by_type = {o["delivery_type"]: o for o in options["options"]}
    assert (
        by_type["click_and_collect"]["available"]
        and by_type["click_and_collect"]["price_cents"] == 0
    )
    assert (
        by_type["courier"]["available"] is False
        and by_type["courier"]["reason_code"] == "weight_unknown"
    )
    assert by_type["helm_dash"]["available"] and by_type["helm_dash"]["requires_quote"]
    assert by_type["helm_dash"]["operating_areas"][0]["id"] == "hauraki-gulf"
    assert (
        options["total_weight_grams"] is None
        and options["missing_weight_products"][0]["name"] == "Chart Book"
    )

    dg = await create_product(dangerous_goods=True, name="Flare Kit")
    await add(client, customer, dg)
    options = (await client.get(f"{API}/shipping/options", headers=customer.headers)).json()
    by_type = {o["delivery_type"]: o for o in options["options"]}
    assert by_type["courier"]["reason_code"] == "dangerous_goods_restricted"
    assert by_type["helm_dash"]["reason_code"] == "dangerous_goods_restricted"
    assert by_type["click_and_collect"]["available"] is True
    assert options["dangerous_goods_products"][0]["name"] == "Flare Kit"


async def test_delivery_options_courier_price_and_disabled_helm_dash(client, customer):
    p = await create_product(weight_grams=600)
    await add(client, customer, p)
    options = (await client.get(f"{API}/shipping/options", headers=customer.headers)).json()
    by_type = {o["delivery_type"]: o for o in options["options"]}
    assert by_type["courier"]["available"] and by_type["courier"]["price_cents"] == 750
    assert by_type["courier"]["development_rate_card"] is True
    assert by_type["helm_dash"]["available"] is False  # no enabled operating area
    assert (
        options["total_weight_grams"] == 600
        and options["merchandise_subtotal_cents"] == p.price_cents
    )


async def test_public_estimate_is_informational_and_rate_limited(client, monkeypatch):
    await seed_area()
    p = await create_product(weight_grams=4000)
    dg = await create_product(dangerous_goods=True)
    r = await client.post(
        f"{API}/shipping/estimate",
        json={"delivery_type": "courier", "items": [{"product_id": str(p.id), "quantity": 2}]},
    )
    assert r.status_code == 200, r.text
    assert (
        r.json()["price_cents"] == 1850 and r.json()["bindable"] is False and r.json()["available"]
    )
    r = await client.post(
        f"{API}/shipping/estimate",
        json={
            "delivery_type": "helm_dash",
            "destination": WAIHEKE,
            "items": [{"product_id": str(p.id)}],
        },
    )
    assert r.json()["available"] and r.json()["estimated_minutes"] > 15
    r = await client.post(
        f"{API}/shipping/estimate",
        json={"delivery_type": "courier", "items": [{"product_id": str(dg.id)}]},
    )
    assert (
        r.json()["available"] is False and r.json()["reason_code"] == "dangerous_goods_restricted"
    )
    monkeypatch.setattr(get_settings(), "rate_limit_shipping_estimate_per_minute", 3)
    r = await client.post(
        f"{API}/shipping/estimate",
        json={"delivery_type": "courier", "items": [{"product_id": str(p.id)}]},
    )
    assert r.status_code == 429
