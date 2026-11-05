#!/usr/bin/env python3
"""Capture REAL API responses for the catalogue / vessel garage / checklist client.

Runs against the local acceptance stack (``scripts/local_stack.sh up`` + seed) through
the public reverse proxy, using the REAL local identity provider: a fresh account signs
up with GoTrue, confirms through the Mailpit sink, signs in, and is provisioned. Every
fixture is the verbatim body of an HTTP response from the running API — nothing here is
hand-written JSON. Fixtures are written to ``frontend/test/fixtures/api/catalogue/``.

Usage (from the repository root)::

    SUPABASE_JWT_SECRET=... python3 scripts/capture_api_fixtures_pass2_catalogue.py \
        [--base http://localhost:18080] [--mailpit http://localhost:18025]

The anon key is derived from the local stack's ``SUPABASE_JWT_SECRET`` (read from the
environment or ``.env``), exactly as ``scripts/e2e/api_journey.py`` does.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "test" / "fixtures" / "api" / "catalogue"


def anon_key(secret: str) -> str:
    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"role": "anon", "iss": "supabase", "iat": int(time.time()),
                              "exp": int(time.time()) + 3600}).encode())
    sig = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def secret_from_env_file() -> str:
    env = REPO / ".env"
    if not env.exists():
        return ""
    for line in env.read_text().splitlines():
        m = re.match(r"\s*SUPABASE_JWT_SECRET=(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ""


class Capture:
    def __init__(self, base: str, mailpit: str, anon: str, out: Path) -> None:
        self.base, self.mailpit, self.anon, self.out = base.rstrip("/"), mailpit.rstrip("/"), anon, out
        self.http = httpx.Client(timeout=30)
        self.token: str | None = None
        self.written: list[str] = []

    # ------------------------------------------------------------------ transport
    def auth(self, path: str, body: dict, **params) -> httpx.Response:
        return self.http.post(f"{self.base}/auth/v1/{path}", json=body, params=params,
                              headers={"apikey": self.anon, "Authorization": f"Bearer {self.anon}"})

    def api(self, method: str, path: str, *, auth: bool = True, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return self.http.request(method, f"{self.base}/api/v1{path}", headers=headers, **kw)

    # ------------------------------------------------------------------ saving
    def _write(self, name: str, text: str, note: str) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / name
        path.write_text(text)
        self.written.append(f"{path.relative_to(REPO)}  ({note})")

    def save(self, name: str, resp: httpx.Response, expect: int):
        """Save the verbatim JSON body of a response that had the expected status."""
        if resp.status_code != expect:
            raise SystemExit(f"{resp.request.method} {resp.request.url} -> {resp.status_code}, "
                             f"expected {expect}: {resp.text[:400]}")
        body = resp.json()
        self._write(f"{name}.json", json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                    f"{resp.request.method} {resp.request.url.path} {resp.status_code}")
        return body

    def save_text(self, name: str, resp: httpx.Response, expect: int) -> str:
        if resp.status_code != expect:
            raise SystemExit(f"{resp.request.url} -> {resp.status_code}: {resp.text[:400]}")
        self._write(name, resp.text, f"{resp.request.method} {resp.request.url.path} "
                                     f"{resp.status_code} {resp.headers.get('content-type')}")
        return resp.text

    def expect(self, resp: httpx.Response, status: int):
        if resp.status_code != status:
            raise SystemExit(f"{resp.request.method} {resp.request.url} -> {resp.status_code}, "
                             f"expected {status}: {resp.text[:400]}")
        return resp.json() if resp.content else None

    # ------------------------------------------------------------------ identity
    def confirmation_link(self, email: str, timeout: float = 30) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = self.http.get(f"{self.mailpit}/api/v1/search", params={"query": f"to:{email}"}).json()
            for m in msgs.get("messages", []):
                body = self.http.get(f"{self.mailpit}/api/v1/message/{m['ID']}").json()
                link = re.search(r"https?://[^\s\"'<>]+/verify\?[^\s\"'<>]+",
                                 body.get("Text", "") + body.get("HTML", ""))
                if link:
                    return link.group(0).replace("&amp;", "&")
            time.sleep(1)
        raise SystemExit(f"no confirmation email for {email}")

    def sign_up_and_provision(self, email: str, password: str, name: str) -> None:
        r = self.auth("signup", {"email": email, "password": password, "data": {"full_name": name}})
        if r.status_code != 200:
            raise SystemExit(f"signup failed: {r.status_code} {r.text[:200]}")
        r = self.http.get(self.confirmation_link(email), follow_redirects=False)
        if r.status_code not in (302, 303):
            raise SystemExit(f"confirmation failed: {r.status_code}")
        r = self.auth("token", {"email": email, "password": password}, grant_type="password")
        if r.status_code != 200:
            raise SystemExit(f"sign-in failed: {r.status_code} {r.text[:200]}")
        self.token = r.json()["access_token"]
        self.expect(self.api("POST", "/auth/provision", json={"full_name": name}), 201)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=os.environ.get("HELM_PUBLIC_URL", "http://localhost:18080"))
    ap.add_argument("--mailpit", default="http://localhost:18025")
    ap.add_argument("--jwt-secret", default=os.environ.get("SUPABASE_JWT_SECRET") or secret_from_env_file())
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    if not a.jwt_secret:
        print("SUPABASE_JWT_SECRET (local stack .env) is required to derive the public anon key")
        return 2
    c = Capture(a.base, a.mailpit, anon_key(a.jwt_secret), Path(a.out_dir))
    run = uuid.uuid4().hex[:8]
    c.sign_up_and_provision(f"catalogue-{run}@example.test", f"Pw-{uuid.uuid4().hex}", "Catalogue Fixture")

    # ---------------------------------------------------------------- boat DB / HIN
    c.save("hin_decode_valid", c.api("POST", "/boat-db/hin/decode", json={"hin": "nz-z9x12345c121"}), 200)
    c.save("hin_decode_unrecognised_mic", c.api("POST", "/boat-db/hin/decode", json={"hin": "SYN12345F121"}), 200)
    c.save("hin_decode_invalid", c.api("POST", "/boat-db/hin/decode", json={"hin": "not-a-hin"}), 200)
    makers = c.save("boat_manufacturers_search", c.api("GET", "/boat-db/manufacturers", params={"q": "fixture"}), 200)
    maker = next(m for m in makers if m["is_synthetic"])
    models = c.save("boat_models", c.api("GET", f"/boat-db/manufacturers/{maker['id']}/models"), 200)
    model = next(m for m in models if m["name"] == "Fixture 600 Runabout")
    c.save("boat_model_years", c.api("GET", f"/boat-db/models/{model['id']}/years"), 200)
    c.save("boat_lookup", c.api("GET", "/boat-db/lookup",
                                 params={"make": maker["name"], "model": model["name"], "year": 2021}), 200)
    c.save("equipment_categories", c.api("GET", "/boat-db/equipment-categories"), 200)

    # ---------------------------------------------------------------- vessel
    vessel = c.save("vessel_linked", c.api("POST", "/vessels/", json={
        "nickname": "Kahawai", "make": maker["name"], "model": model["name"], "year": 2021,
        "hin": "nz-z9x12345c121", "propulsion_type": "outboard", "hull_type": "aluminium",
        "engine_make": "Yamaha", "engine_model": "F150", "engine_year": 2021, "engine_hours": 120,
    }), 201)
    vid = vessel["id"]
    c.save("boat_model_year_detail", c.api("GET", f"/boat-db/model-years/{vessel['model_year_id']}"), 200)
    c.save("vessel_unlinked", c.api("POST", "/vessels/", json={
        "nickname": "Dinghy", "make": "Homebuilt", "model": "Pram", "year": 1998, "hin": "SYN12345F121"}), 201)

    # ---------------------------------------------------------------- products
    c.save("products_page", c.api("GET", "/products/", params={"limit": 6}), 200)
    page = c.save("products_page_vessel", c.api("GET", "/products/",
                                                params={"vessel_id": vid, "limit": 100, "sort": "name"}), 200)
    c.save("products_compatible", c.api("GET", "/products/", params={
        "vessel_id": vid, "compatible_only": "true", "limit": 100}), 200)
    c.save("products_filtered", c.api("GET", "/products/", params={
        "vessel_id": vid, "part_role": "spark_plug", "in_stock": "true", "sort": "price_asc",
        "min_price_cents": 0, "max_price_cents": 100000, "offset": 0, "limit": 20}), 200)
    c.save("products_page2", c.api("GET", "/products/", params={"limit": 5, "offset": 5}), 200)
    c.save("product_categories", c.api("GET", "/products/categories"), 200)
    c.save("product_brands", c.api("GET", "/products/brands"), 200)
    c.save("search_products", c.api("GET", "/search/products", params={"q": "plug", "vessel_id": vid}), 200)
    c.save("error_vessel_required", c.api("GET", "/products/", params={"compatible_only": "true"}), 422)
    by_sku = {p["sku"]: p for p in page["items"]}
    plug = by_sku["SYN-PLUG-150"]
    mismatch = by_sku["SYN-PLUG-140"]
    c.save("product_detail_vessel", c.api("GET", f"/products/{plug['id']}", params={"vessel_id": vid}), 200)
    c.save("product_detail_mismatch", c.api("GET", f"/products/{mismatch['id']}", params={"vessel_id": vid}), 200)
    c.save("product_compatibility", c.api("GET", f"/products/{plug['id']}/compatibility"), 200)
    universal = next(p for p in page["items"] if p["fitment_scope"] == "universal")
    c.save("product_compatibility_universal", c.api("GET", f"/products/{universal['id']}/compatibility"), 200)
    unknown = next((p for p in page["items"] if p["fitment"]["status"] == "unknown"), None)
    dangerous = next((p for p in page["items"] if p["dangerous_goods"]), None)
    if dangerous:
        c.save("product_detail_dangerous", c.api("GET", f"/products/{dangerous['id']}", params={"vessel_id": vid}), 200)

    # ---------------------------------------------------------------- equipment
    c.save("equipment_list_factory", c.api("GET", f"/vessels/{vid}/equipment"), 200)
    owner = c.save("equipment_added", c.api("POST", f"/vessels/{vid}/equipment", json={
        "category": "chartplotter", "make": "Garmin", "model": "echoMAP UHD 93sv",
        "serial_number": "GAR-001", "year": 2022, "installed_on": "2022-10-01", "notes": "Fitted by owner"}), 201)
    c.save("equipment_updated", c.api("PATCH", f"/vessels/{vid}/equipment/{owner['id']}",
                                      json={"model": "echoMAP UHD 95sv", "notes": None}), 200)
    c.save("equipment_apply_oem", c.api("POST", f"/vessels/{vid}/equipment/apply-oem", json={}), 200)
    c.save("equipment_list_applied", c.api("GET", f"/vessels/{vid}/equipment"), 200)
    c.save("verification_request", c.api("POST", f"/vessels/{vid}/equipment/verification-requests",
                                         json={"note": "Fitted at purchase"}), 201)
    c.save("verification_requests", c.api("GET", f"/vessels/{vid}/equipment/verification-requests"), 200)
    c.save("error_verification_pending", c.api("POST", f"/vessels/{vid}/equipment/verification-requests",
                                               json={}), 409)
    extra = c.expect(c.api("POST", f"/vessels/{vid}/equipment", json={"category": "vhf_radio", "make": "Icom"}), 201)
    c.expect(c.api("DELETE", f"/vessels/{vid}/equipment/{extra['id']}"), 204)
    c.save("equipment_list_with_removed", c.api("GET", f"/vessels/{vid}/equipment",
                                                params={"include_removed": "true"}), 200)

    # ---------------------------------------------------------------- service history
    rec = c.save("service_record_created", c.api("POST", f"/vessels/{vid}/service-records", json={
        "service_type": "100-hour service", "performed_on": "2026-09-14", "engine_hours": 100,
        "provider_name": "Gulf Marine", "cost_cents": 45000, "notes": "Plugs and impeller"}), 201)
    c.save("service_record_updated", c.api("PATCH", f"/vessels/{vid}/service-records/{rec['id']}",
                                           json={"cost_cents": 46500}), 200)
    c.save("service_records", c.api("GET", f"/vessels/{vid}/service-records"), 200)
    rem = c.save("reminder_created", c.api("POST", f"/vessels/{vid}/service-reminders", json={
        "title": "Replace impeller", "due_on": "2026-10-01", "due_engine_hours": 200,
        "interval_months": 12, "interval_hours": 100}), 201)
    c.save("reminder_updated", c.api("PATCH", f"/vessels/{vid}/service-reminders/{rem['id']}",
                                     json={"title": "Replace water pump impeller"}), 200)
    c.save("reminders_active", c.api("GET", f"/vessels/{vid}/service-reminders"), 200)
    c.save("error_reminder_needs_due", c.api("POST", f"/vessels/{vid}/service-reminders",
                                             json={"title": "No due point"}), 422)
    c.save("reminder_completed", c.api("POST", f"/vessels/{vid}/service-reminders/{rem['id']}/complete",
                                       json={"engine_hours": 130, "notes": "Done at the ramp"}), 200)
    c.save("reminders_all", c.api("GET", f"/vessels/{vid}/service-reminders", params={"status": "all"}), 200)

    # ---------------------------------------------------------------- checklists
    c.save("checklists_not_generated", c.api("GET", f"/checklists/vessel/{vid}"), 200)
    c.save("error_checklists_not_generated", c.api("GET", f"/checklists/vessel/{vid}/tiers/grab_and_go"), 404)
    checklist = c.save("checklists_generated", c.api("POST", f"/checklists/vessel/{vid}/generate"), 201)
    c.save("error_checklists_exist", c.api("POST", f"/checklists/vessel/{vid}/generate"), 409)
    day = checklist["tiers"][0]
    linked = next(i for i in day["items"] if i["product"] is not None)
    c.save("checklist_item_checked", c.api("PATCH", f"/checklists/items/{linked['id']}", json={"is_checked": True}), 200)
    c.save("checklist_item_toggled", c.api("POST", f"/checklists/items/{linked['id']}/toggle"), 200)
    plug_item = next((i for t in checklist["tiers"] for i in t["items"] if i["part_role"] == "spark_plug"), linked)
    c.save("error_link_mismatch", c.api("PUT", f"/checklists/items/{plug_item['id']}/link",
                                        json={"product_id": mismatch["id"]}), 409)
    if unknown:
        c.save("checklist_item_linked_unverified", c.api("PUT", f"/checklists/items/{plug_item['id']}/link",
                                                         json={"product_id": unknown["id"]}), 200)
    c.save("checklist_item_linked", c.api("PUT", f"/checklists/items/{plug_item['id']}/link",
                                          json={"product_id": plug["id"]}), 200)
    c.save("checklist_add_missing_first", c.api("POST", f"/checklists/vessel/{vid}/add-missing-to-cart",
                                                json={"tier": "grab_and_go"}), 200)
    c.save("checklist_add_missing_second", c.api("POST", f"/checklists/vessel/{vid}/add-missing-to-cart",
                                                 json={"tier": "grab_and_go"}), 200)
    c.save("checklist_tier_offshore", c.api("GET", f"/checklists/vessel/{vid}/tiers/offshore_passage"), 200)
    c.save("checklists_regenerated", c.api("POST", f"/checklists/vessel/{vid}/generate",
                                           params={"regenerate": "true"}), 201)
    c.save_text("checklist_export.html", c.api("GET", f"/checklists/vessel/{vid}/export",
                                               params={"tier": "coastal_cruising", "format": "html"}), 200)
    c.save_text("checklist_export.csv", c.api("GET", f"/checklists/vessel/{vid}/export",
                                              params={"tier": "coastal_cruising", "format": "csv"}), 200)
    c.expect(c.api("DELETE", f"/checklists/vessel/{vid}"), 204)

    # ---------------------------------------------------------------- notifications
    c.save("notification_preferences", c.api("GET", "/notifications/preferences"), 200)
    c.save("notification_preferences_updated", c.api("PUT", "/notifications/preferences",
                                                      json={"marketing": True, "push_enabled": False}), 200)
    c.save("error_preferences_unknown_field", c.api("PUT", "/notifications/preferences",
                                                    json={"transactional": False}), 422)

    print("Captured fixtures:")
    for line in c.written:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
