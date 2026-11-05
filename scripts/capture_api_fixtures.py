#!/usr/bin/env python3
"""Capture REAL API payloads as Flutter contract-test fixtures.

Run against a locally running Helm API that verifies HS256 tokens with a development
secret. Every fixture is produced by server code: HTTP responses are saved verbatim,
and ``ProductResponse`` payloads (whose router is not yet public in this revision) are
produced by ``app.services.catalogue.product_response`` on real database rows with the
central fitment service. Nothing here is hand-written JSON.

Usage (from the repository root, with the backend virtualenv's python)::

    python scripts/capture_api_fixtures.py \
        --base-url http://localhost:18000 \
        --jwt-secret "$SUPABASE_JWT_SECRET" \
        --supabase-url http://localhost:19999 \
        --database-url postgresql+asyncpg://helm:helm@localhost:5432/helm_dev_frontend

The API must run with ``APP_ENV=development AUTH_MODE=hs256`` and the same
``SUPABASE_URL`` / ``SUPABASE_JWT_SECRET``. Use a disposable development database:
the script inserts products and fitment rules into it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import jwt

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "test" / "fixtures" / "api"


def mint_token(secret: str, issuer: str, sub: str, email: str) -> str:
    """A Supabase-shaped access token (same claims GoTrue issues)."""
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": "authenticated",
        "iss": issuer,
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
        "aal": "aal1",
        "email": email,
        "session_id": str(uuid.uuid4()),
        "is_anonymous": False,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


class Capture:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.written: list[str] = []

    def save(self, name: str, payload, *, status: int | None = None, source: str = "") -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        self.written.append(f"{path.relative_to(REPO)}  ({source}{' ' + str(status) if status else ''})")

    def response(self, name: str, resp: httpx.Response, expect: int) -> dict | list:
        if resp.status_code != expect:
            raise SystemExit(
                f"{resp.request.method} {resp.request.url} -> {resp.status_code}, expected {expect}: {resp.text}"
            )
        body = resp.json()
        self.save(name, body, status=resp.status_code, source=f"{resp.request.method} {resp.request.url.path}")
        return body


async def insert_products_and_serialise(database_url: str, vessel_id: str) -> dict:
    """Insert catalogue rows via the ORM and serialise them with the server's own code."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.database import async_session, engine  # noqa: PLC0415
    from app.models.product import Product, ProductCompatibility  # noqa: PLC0415
    from app.models.vessel import Vessel  # noqa: PLC0415
    from app.services.catalogue import product_response  # noqa: PLC0415
    from app.services.fitment import evaluate_products, load_vessel_profile  # noqa: PLC0415

    tag = uuid.uuid4().hex[:8].upper()
    async with async_session() as db:
        vessel = (await db.execute(select(Vessel).where(Vessel.id == uuid.UUID(vessel_id)))).scalar_one()
        fits = Product(
            sku=f"FX-IMP-{tag}", name="Water Pump Impeller Kit", description="OEM-equivalent impeller kit.",
            brand="Sierra", category="engine_parts", sub_category="cooling", price_cents=8990,
            sale_price_cents=7490, cost_price_cents=4000, stock_quantity=12, weight_grams=180,
            images=["https://cdn.example.invalid/impeller.jpg"], specifications={"vanes": 6},
            oem_part_numbers=["47-43026Q06"], part_role="impeller", fitment_scope="specific",
        )
        mismatch = Product(
            sku=f"FX-FLT-{tag}", name="Fuel Filter Element", brand="Racor", category="engine_parts",
            sub_category="fuel", price_cents=3450, stock_quantity=4, weight_grams=250, images=[],
            oem_part_numbers=["S3213"], part_role="fuel_filter", fitment_scope="specific",
        )
        universal = Product(
            sku=f"FX-TIE-{tag}", name="UV Stabilised Cable Ties (100)", brand="Helm", category="hardware",
            price_cents=1299, stock_quantity=0, weight_grams=300, images=[], fitment_scope="universal",
        )
        unknown = Product(
            sku=f"FX-FLR-{tag}", name="Marine Distress Flares (pack of 3)", brand="Pains Wessex",
            category="safety", price_cents=14900, stock_quantity=6, weight_grams=900, images=[],
            fitment_scope="unspecified", dangerous_goods=True,
        )
        db.add_all([fits, mismatch, universal, unknown])
        await db.flush()
        db.add_all([
            ProductCompatibility(
                product_id=fits.id, engine_make=vessel.engine_make, engine_model=vessel.engine_model,
                engine_year_from=2010, engine_year_to=2030, verification_status="verified",
                confidence_score=0.95, data_source="fixture_capture",
            ),
            ProductCompatibility(
                product_id=mismatch.id, engine_make="Yamaha", engine_model="F150",
                verification_status="verified", confidence_score=0.95, data_source="fixture_capture",
            ),
        ])
        await db.commit()
        products = [fits, mismatch, universal, unknown]
        for p in products:
            await db.refresh(p)
        profile = await load_vessel_profile(db, vessel)
        fitments = await evaluate_products(db, products, profile)
        serialised = [product_response(p, fitments[p.id]).model_dump(mode="json") for p in products]
        no_vessel = product_response(fits).model_dump(mode="json")
        ids = {"fits": str(fits.id), "out_of_stock": str(universal.id), "dangerous": str(unknown.id)}
        label = profile.label
    await engine.dispose()
    return {"items": serialised, "no_vessel": no_vessel, "ids": ids, "label": label}


async def set_stock(database_url: str, product_id: str, qty: int) -> None:
    from sqlalchemy import update  # noqa: PLC0415

    from app.database import async_session, engine  # noqa: PLC0415
    from app.models.product import Product  # noqa: PLC0415

    async with async_session() as db:
        await db.execute(update(Product).where(Product.id == uuid.UUID(product_id)).values(stock_quantity=qty))
        await db.commit()
    await engine.dispose()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:18000", help="API origin (without /api/v1)")
    ap.add_argument("--jwt-secret", default=os.environ.get("SUPABASE_JWT_SECRET"), help="HS256 dev secret")
    ap.add_argument("--supabase-url", default=os.environ.get("SUPABASE_URL", "http://localhost:19999"))
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"),
                    help="Async SQLAlchemy URL of the API's development database")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    if not args.jwt_secret or not args.database_url:
        ap.error("--jwt-secret and --database-url are required (or SUPABASE_JWT_SECRET / DATABASE_URL)")

    # The backend modules read their settings from the environment at import time.
    os.environ.update({
        "APP_ENV": "development", "AUTH_MODE": "hs256", "DATABASE_URL": args.database_url,
        "SUPABASE_URL": args.supabase_url, "SUPABASE_JWT_SECRET": args.jwt_secret,
    })
    sys.path.insert(0, str(REPO / "backend"))

    issuer = f"{args.supabase_url.rstrip('/')}/auth/v1"
    api = f"{args.base_url.rstrip('/')}/api/v1"
    cap = Capture(Path(args.out_dir))
    sub, email = str(uuid.uuid4()), f"fixture.{uuid.uuid4().hex[:8]}@example.test"
    token = mint_token(args.jwt_secret, issuer, sub, email)
    auth = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=15) as http:
        cap.response("config_public", http.get(f"{api}/config/public"), 200)
        cap.response("error_unauthenticated", http.get(f"{api}/auth/me"), 401)
        cap.response("error_profile_not_provisioned", http.get(f"{api}/auth/me", headers=auth), 403)
        cap.response("provision_created", http.post(f"{api}/auth/provision", json={"full_name": "Fixture Skipper"}, headers=auth), 201)
        cap.response("provision_existing", http.post(f"{api}/auth/provision", json={"full_name": "Fixture Skipper"}, headers=auth), 200)
        cap.response("error_validation", http.post(f"{api}/auth/provision", json={"full_name": "X", "role": "admin"}, headers=auth), 422)
        cap.response("auth_me", http.get(f"{api}/auth/me", headers=auth), 200)
        cap.response("vessels_empty", http.get(f"{api}/vessels/", headers=auth), 200)
        vessel = cap.response("vessel_create", http.post(f"{api}/vessels/", headers=auth, json={
            "nickname": "Sea Biscuit", "make": "Haines Hunter", "model": "SF600", "year": 2018,
            "hull_type": "fibreglass", "length_ft": 19.5, "primary_use": "fishing",
            "propulsion_type": "outboard", "engine_make": "Mercury", "engine_model": "F150",
            "engine_year": 2018, "engine_serial": "1B123456", "engine_hours": 420, "hin": "NZ-HHB12345C818",
        }), 201)
        cap.response("vessel_create_minimal", http.post(f"{api}/vessels/", headers=auth, json={
            "nickname": "Tender", "make": "Quintrex", "model": "350 Dory", "year": 2005,
        }), 201)
        cap.response("vessels_list", http.get(f"{api}/vessels/", headers=auth), 200)
        cap.response("error_not_found", http.get(f"{api}/vessels/{uuid.uuid4()}", headers=auth), 404)

        catalogue = asyncio.run(insert_products_and_serialise(args.database_url, vessel["id"]))
        cap.save("product_detail_fit", catalogue["items"][0], source="catalogue.product_response + fitment.evaluate_products")
        cap.save("product_detail_no_vessel", catalogue["no_vessel"], source="catalogue.product_response")
        cap.save("products_list", {
            "items": catalogue["items"], "total": len(catalogue["items"]), "offset": 0, "limit": 20,
            "vessel": {"id": vessel["id"], "label": catalogue["label"]},
        }, source="list envelope (catalogue workstream contract) around catalogue.product_response items")

        cap.response("cart_empty", http.get(f"{api}/cart/", headers=auth), 200)
        cap.response("cart_with_item", http.post(f"{api}/cart/items", headers=auth, json={
            "product_id": catalogue["ids"]["fits"], "quantity": 2}), 201)
        cap.response("error_insufficient_stock", http.post(f"{api}/cart/items", headers=auth, json={
            "product_id": catalogue["ids"]["fits"], "quantity": 50}), 409)
        asyncio.run(set_stock(args.database_url, catalogue["ids"]["fits"], 1))
        cap.response("cart_with_issues", http.get(f"{api}/cart/", headers=auth), 200)
        asyncio.run(set_stock(args.database_url, catalogue["ids"]["fits"], 12))

    print("Captured fixtures:")
    for line in cap.written:
        print("  " + line)


if __name__ == "__main__":
    main()
