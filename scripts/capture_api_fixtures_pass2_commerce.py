#!/usr/bin/env python3
"""Capture REAL commerce / Helm Dash / dispatch payloads as Flutter contract fixtures.

Drives the running local stack (``scripts/local_stack.sh up`` + ``seed``) through the
reverse proxy with REAL GoTrue accounts: confirmation-required sign-up, the confirm link
from the Mailpit sink, password sign-in and provisioning. Staff roles are granted with
the audited ``grant-role`` CLI. Every fixture is a verbatim HTTP response body from the
server — nothing is hand-written.

Captured (``frontend/test/fixtures/api/``): public config with Helm Dash enabled, operating
areas, delivery options (normal and dangerous-goods carts), courier and Helm Dash quotes,
checkout previews (courier / Helm Dash / click & collect / with a discount), checkout 201
and the idempotent 200 repeat, the local test-mode payment intent and confirmations
(decline, requires_action, authenticate, succeed), order detail in each payment state,
the order list, cancellation, the customer's Helm Dash tracking (awaiting dispatch,
awaiting first position, simulated position, delivered), the dispatcher console
(deliveries, detail, operators, areas, assignment), the operator job flow, payouts and
reconciliation, staff orders (list, detail, fulfilment, test courier label), a refund
and the error payloads the client handles.

Positions: the "with location" tracking fixture uses the ``simulate-delivery`` CLI, which
stores positions labelled ``simulated``. One operator-API position is posted to capture
the ``LocationOut`` contract; it is a capture-only reading on a synthetic fixture order
(the app itself only ever posts readings from the device geolocation API).

Usage (from the repository root)::

    python3 scripts/capture_api_fixtures_pass2_commerce.py \
        [--base http://localhost:18080] [--mailpit http://localhost:18025] \
        [--stack-root /path/to/checkout/with/.env]

``--stack-root`` is the checkout whose ``.env`` / ``scripts/local_stack.sh`` run the
stack (default: this repository); ``SUPABASE_JWT_SECRET`` is read from its ``.env`` only
to derive the public anon key, exactly as ``scripts/e2e/api_journey.py`` does.

Side effects on the local development database: four new ``@example.test`` accounts,
a few synthetic orders (some paid, consuming a little SYN- stock), one Helm Dash
operator profile and delivery. Development stack only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "test" / "fixtures" / "api"

# Helm Dash destinations inside / outside the seeded Hauraki Gulf area.
INSIDE = {"lat": -36.80, "lng": 174.85, "location_name": "Motuihe Channel anchorage"}
OUTSIDE = {"lat": -41.29, "lng": 174.78, "location_name": "Wellington Harbour"}
ADDRESS = {
    "name": "Fixture Shopper",
    "line1": "1 Quay Street",
    "suburb": "Auckland Central",
    "city": "Auckland",
    "postcode": "1010",
    "phone": "021 555 0101",
}


def anon_key(secret: str) -> str:
    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({"role": "anon", "iss": "supabase", "iat": now, "exp": now + 3600}).encode())
    sig = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def read_env(path: Path, key: str) -> str:
    for line in path.read_text().splitlines():
        m = re.match(rf"^\s*{key}=(.*)$", line)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ""


class Capture:
    def __init__(self, base: str, mailpit: str, anon: str, out: Path, stack_root: Path) -> None:
        self.base, self.mailpit = base.rstrip("/"), mailpit.rstrip("/")
        self.anon, self.out, self.stack_root = anon, out, stack_root
        self.http = httpx.Client(timeout=60)
        self.written: list[str] = []

    # ------------------------------------------------------------------ plumbing
    def api(self, method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for _ in range(8):
            r = self.http.request(method, f"{self.base}/api/v1{path}", headers=headers, **kw)
            if r.status_code != 429:
                return r
            wait = int(r.headers.get("Retry-After", "10") or 10)
            print(f"   (rate limited on {method} {path}; waiting {wait}s)", flush=True)
            time.sleep(min(max(wait, 1), 65))
        return r

    def save(self, name: str, resp: httpx.Response, expect: int) -> dict | list:
        if resp.status_code != expect:
            raise SystemExit(
                f"{resp.request.method} {resp.request.url} -> {resp.status_code}, expected {expect}: {resp.text[:400]}"
            )
        body = resp.json()
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f"{name}.json").write_text(json.dumps(body, indent=2) + "\n")
        self.written.append(f"{name}.json  ({resp.request.method} {resp.request.url.path} {resp.status_code})")
        print(f"   captured {name} ({resp.status_code})", flush=True)
        return body

    def ok(self, resp: httpx.Response, expect: int) -> dict | list:
        if resp.status_code != expect:
            raise SystemExit(
                f"{resp.request.method} {resp.request.url} -> {resp.status_code}, expected {expect}: {resp.text[:400]}"
            )
        return resp.json() if resp.content else {}

    def cli(self, *args: str) -> str:
        r = subprocess.run(
            [str(self.stack_root / "scripts" / "local_stack.sh"), "cli", *args],
            cwd=self.stack_root,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if r.returncode != 0:
            raise SystemExit(f"local_stack.sh cli {' '.join(args)} failed: {r.stdout}\n{r.stderr}")
        return r.stdout

    # ------------------------------------------------------------------ identity
    def gotrue(self, path: str, body: dict, **params) -> httpx.Response:
        return self.http.post(
            f"{self.base}/auth/v1/{path}",
            json=body,
            params=params,
            headers={"apikey": self.anon, "Authorization": f"Bearer {self.anon}"},
        )

    def confirmation_link(self, email: str, timeout: float = 60) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = self.http.get(f"{self.mailpit}/api/v1/search", params={"query": f"to:{email}"}).json()
            for m in msgs.get("messages", []):
                body = self.http.get(f"{self.mailpit}/api/v1/message/{m['ID']}").json()
                link = re.search(
                    r"https?://[^\s\"'<>]+/verify\?[^\s\"'<>]+", body.get("Text", "") + body.get("HTML", "")
                )
                if link:
                    return link.group(0).replace("&amp;", "&")
            time.sleep(1)
        raise SystemExit(f"no confirmation email for {email}")

    def account(self, email: str, password: str, name: str) -> str:
        r = self.gotrue("signup", {"email": email, "password": password, "data": {"full_name": name}})
        if r.status_code != 200 or r.json().get("access_token"):
            raise SystemExit(f"signup {email}: {r.status_code} {r.text[:200]}")
        r = self.http.get(self.confirmation_link(email), follow_redirects=False)
        if r.status_code not in (302, 303):
            raise SystemExit(f"confirm {email}: {r.status_code}")
        return self.sign_in(email, password, provision_name=name)

    def sign_in(self, email: str, password: str, provision_name: str | None = None) -> str:
        r = self.gotrue("token", {"email": email, "password": password}, grant_type="password")
        if r.status_code != 200:
            raise SystemExit(f"sign-in {email}: {r.status_code} {r.text[:200]}")
        tok = r.json()["access_token"]
        if provision_name is not None:
            self.ok(self.api("POST", "/auth/provision", tok, json={"full_name": provision_name}), 201)
        return tok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:18080")
    ap.add_argument("--mailpit", default="http://localhost:18025")
    ap.add_argument("--stack-root", default=str(REPO))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    stack_root = Path(a.stack_root).resolve()
    secret = read_env(stack_root / ".env", "SUPABASE_JWT_SECRET")
    if not secret:
        print(f"SUPABASE_JWT_SECRET not found in {stack_root / '.env'}")
        return 2
    c = Capture(a.base, a.mailpit, anon_key(secret), Path(a.out), stack_root)
    run = uuid.uuid4().hex[:8]
    pw = f"Pw-{uuid.uuid4().hex}"

    print("== public config and areas")
    c.save("config_public_helm_dash", c.api("GET", "/config/public"), 200)
    areas = c.save("helm_dash_areas", c.api("GET", "/helm-dash/areas"), 200)
    if not areas:
        raise SystemExit("No enabled Helm Dash operating area (seed the stack first)")

    products = c.ok(c.api("GET", "/products/", params={"limit": 100}), 200)["items"]
    by_sku = {p["sku"]: p for p in products}
    for sku in ("SYN-ZIP-TIES", "SYN-DUCT-TAPE", "SYN-FLARE-KIT", "SYN-KILL-LAN"):
        if sku not in by_sku:
            raise SystemExit(f"Seed product {sku} missing")
    zip_ties, duct, flare, lanyard = (by_sku[s] for s in ("SYN-ZIP-TIES", "SYN-DUCT-TAPE", "SYN-FLARE-KIT", "SYN-KILL-LAN"))

    print("== accounts (real GoTrue sign-up + Mailpit confirmation)")
    cust_email = f"commerce-shopper-{run}@example.test"
    cust = c.account(cust_email, pw, "Fixture Shopper")
    other = c.account(f"commerce-other-{run}@example.test", pw, "Fixture Other")
    disp_email = f"commerce-dispatch-{run}@example.test"
    disp = c.account(disp_email, pw, "Fixture Dispatcher")
    op_email = f"commerce-operator-{run}@example.test"
    op = c.account(op_email, pw, "Fixture Skipper Op")
    admin_email = f"commerce-admin-{run}@example.test"
    admin = c.account(admin_email, pw, "Fixture Admin")
    c.cli("grant-role", disp_email, "dispatcher")
    c.cli("grant-role", op_email, "operator")
    c.cli("grant-role", admin_email, "admin")
    me_disp = c.save("auth_me_dispatcher", c.api("GET", "/auth/me", disp), 200)
    c.save("auth_me_operator", c.api("GET", "/auth/me", op), 200)
    c.save("auth_me_admin", c.api("GET", "/auth/me", admin), 200)
    op_user = c.ok(c.api("GET", "/auth/me", op), 200)
    assert me_disp["role"] == "dispatcher"

    def clear_cart(tok: str) -> None:
        c.api("DELETE", "/cart/", tok)

    def add(tok: str, product: dict, qty: int = 1) -> dict:
        return c.ok(c.api("POST", "/cart/items", tok, json={"product_id": product["id"], "quantity": qty}), 201)

    print("== delivery options")
    clear_cart(cust)
    add(cust, zip_ties, 10)
    cart = add(cust, duct, 1)
    c.save("shipping_options", c.api("GET", "/shipping/options", cust), 200)
    cart = add(cust, flare, 1)
    c.save("shipping_options_dangerous_goods", c.api("GET", "/shipping/options", cust), 200)
    c.save(
        "error_dangerous_goods_restricted",
        c.api("POST", "/shipping/quotes", cust, json={"delivery_type": "courier", "destination": {"postcode": "1010"}}),
        422,
    )
    c.save(
        "checkout_preview_click_and_collect",
        c.api("POST", "/orders/checkout/preview", cust, json={"delivery_type": "click_and_collect"}),
        200,
    )
    flare_line = next(i for i in cart["items"] if i["product_id"] == flare["id"])
    c.ok(c.api("DELETE", f"/cart/items/{flare_line['id']}", cust), 200)

    print("== quotes")
    courier_q = c.save(
        "quote_courier",
        c.api(
            "POST",
            "/shipping/quotes",
            cust,
            json={"delivery_type": "courier", "destination": {"postcode": "1010", "city": "Auckland"}},
        ),
        201,
    )
    c.save(
        "error_validation_postcode",
        c.api("POST", "/shipping/quotes", cust, json={"delivery_type": "courier", "destination": {"postcode": "10"}}),
        422,
    )
    c.save("quote_helm_dash", c.api("POST", "/shipping/quotes", cust, json={"delivery_type": "helm_dash", "destination": INSIDE}), 201)
    c.save(
        "error_outside_operating_area",
        c.api("POST", "/shipping/quotes", cust, json={"delivery_type": "helm_dash", "destination": OUTSIDE}),
        422,
    )

    print("== previews and checkout errors")
    courier_body = {"delivery_type": "courier", "quote_id": courier_q["id"], "shipping_address": ADDRESS}
    c.save("checkout_preview_courier", c.api("POST", "/orders/checkout/preview", cust, json=courier_body), 200)
    c.save("error_idempotency_key_required", c.api("POST", "/orders/checkout", cust, json=courier_body), 400)
    c.save(
        "error_payment_method_unavailable",
        c.api("POST", "/orders/checkout/preview", cust, json={**courier_body, "payment_method": "afterpay"}),
        422,
    )
    c.save(
        "error_quote_destination_mismatch",
        c.api(
            "POST",
            "/orders/checkout/preview",
            cust,
            json={**courier_body, "shipping_address": {**ADDRESS, "postcode": "6011"}},
        ),
        422,
    )
    c.save(
        "error_quote_required",
        c.api("POST", "/orders/checkout/preview", cust, json={"delivery_type": "courier", "shipping_address": ADDRESS}),
        422,
    )
    extra = add(cust, lanyard, 1)
    c.save("error_quote_cart_changed", c.api("POST", "/orders/checkout/preview", cust, json=courier_body), 409)
    line = next(i for i in extra["items"] if i["product_id"] == lanyard["id"])
    c.ok(c.api("DELETE", f"/cart/items/{line['id']}", cust), 200)

    # insufficient_stock at checkout: another shopper reserves the last unit.
    stock = c.ok(c.api("GET", f"/products/{lanyard['id']}"), 200)["stock_quantity"]
    if 2 <= stock <= 99:
        cart_line = add(cust, lanyard, stock)  # every unit currently available
        clear_cart(other)
        add(other, lanyard, 1)
        other_order = c.ok(
            c.api(
                "POST",
                "/orders/checkout",
                other,
                json={"delivery_type": "click_and_collect"},
                headers={"Idempotency-Key": f"cap-other-{run}"},
            ),
            201,
        )
        c.save(
            "error_checkout_insufficient_stock",
            c.api("POST", "/orders/checkout/preview", cust, json={"delivery_type": "click_and_collect"}),
            409,
        )
        c.ok(c.api("POST", f"/orders/{other_order['id']}/cancel", other), 200)
        line = next(i for i in cart_line["items"] if i["product_id"] == lanyard["id"])
        c.ok(c.api("DELETE", f"/cart/items/{line['id']}", cust), 200)
    else:
        print("   (skipped checkout insufficient_stock: SYN-KILL-LAN stock too low)")

    print("== courier checkout + local test payments")
    courier_q = c.ok(
        c.api("POST", "/shipping/quotes", cust, json={"delivery_type": "courier", "destination": {"postcode": "1010"}}), 201
    )
    courier_body = {
        "delivery_type": "courier",
        "quote_id": courier_q["id"],
        "shipping_address": ADDRESS,
        "notes": "Leave with the marina office",
    }
    key = f"cap-courier-{run}"
    order = c.save("order_checkout_created", c.api("POST", "/orders/checkout", cust, json=courier_body, headers={"Idempotency-Key": key}), 201)
    c.save("order_checkout_existing", c.api("POST", "/orders/checkout", cust, json=courier_body, headers={"Idempotency-Key": key}), 200)
    c.save("cart_after_checkout", c.api("GET", "/cart/", cust), 200)
    intent = c.save("payment_intent_local", c.api("POST", f"/payments/orders/{order['id']}/intent", cust, json={"payment_method": "card"}), 200)
    pi = intent["payment_intent_id"]
    c.save("payment_local_decline", c.api("POST", f"/payments/local/{pi}/confirm", cust, json={"outcome": "decline"}), 200)
    c.save("order_payment_failed", c.api("GET", f"/orders/{order['id']}", cust), 200)
    c.save("payment_intent_retry", c.api("POST", f"/payments/orders/{order['id']}/intent", cust), 200)
    c.save("payment_local_requires_action", c.api("POST", f"/payments/local/{pi}/confirm", cust, json={"outcome": "requires_action"}), 200)
    c.save("order_requires_action", c.api("GET", f"/orders/{order['id']}", cust), 200)
    c.save("payment_local_authenticate", c.api("POST", f"/payments/local/{pi}/confirm", cust, json={"outcome": "authenticate"}), 200)
    c.save("order_paid", c.api("GET", f"/orders/{order['id']}", cust), 200)
    c.save("error_order_already_paid", c.api("POST", f"/payments/orders/{order['id']}/intent", cust), 409)
    c.save("error_order_not_cancellable", c.api("POST", f"/orders/{order['id']}/cancel", cust), 409)

    print("== discount entitlement")
    pts = c.ok(c.api("GET", "/loyalty/points", cust), 200)
    if pts.get("points_balance", 0) >= 100:
        c.ok(
            c.api("POST", "/loyalty/redeem/discount", cust, json={"points": 100}, headers={"Idempotency-Key": f"cap-redeem-{run}"}),
            201,
        )
    else:
        print(f"   (points balance {pts.get('points_balance')} < 100; entitlement list will be empty)")
    ents = c.save("loyalty_entitlements_issued", c.api("GET", "/loyalty/entitlements", cust, params={"status": "issued"}), 200)

    print("== click & collect checkout, cancel")
    add(cust, duct, 1)
    if ents:
        c.save(
            "checkout_preview_with_discount",
            c.api(
                "POST",
                "/orders/checkout/preview",
                cust,
                json={"delivery_type": "click_and_collect", "discount_entitlement_id": ents[0]["id"]},
            ),
            200,
        )
    cc = c.save(
        "order_click_and_collect_created",
        c.api("POST", "/orders/checkout", cust, json={"delivery_type": "click_and_collect"}, headers={"Idempotency-Key": f"cap-cc-{run}"}),
        201,
    )
    c.save("order_cancelled", c.api("POST", f"/orders/{cc['id']}/cancel", cust), 200)
    c.save("cart_after_cancel", c.api("GET", "/cart/", cust), 200)

    print("== Helm Dash checkout")
    hd_q = c.ok(c.api("POST", "/shipping/quotes", cust, json={"delivery_type": "helm_dash", "destination": INSIDE}), 201)
    hd_body = {
        "delivery_type": "helm_dash",
        "quote_id": hd_q["id"],
        "helm_dash_contact": {"vessel_name": "Sea Biscuit", "phone": "021 555 0102", "note": "Port side, white hull"},
    }
    c.save(
        "error_helm_dash_contact_required",
        c.api("POST", "/orders/checkout/preview", cust, json={"delivery_type": "helm_dash", "quote_id": hd_q["id"]}),
        422,
    )
    c.save("checkout_preview_helm_dash", c.api("POST", "/orders/checkout/preview", cust, json=hd_body), 200)
    hd = c.save("order_helm_dash_created", c.api("POST", "/orders/checkout", cust, json=hd_body, headers={"Idempotency-Key": f"cap-hd-{run}"}), 201)
    hd_pi = c.ok(c.api("POST", f"/payments/orders/{hd['id']}/intent", cust), 200)["payment_intent_id"]
    c.save("payment_local_succeed", c.api("POST", f"/payments/local/{hd_pi}/confirm", cust, json={"outcome": "succeed"}), 200)
    c.save("order_helm_dash_paid", c.api("GET", f"/orders/{hd['id']}", cust), 200)
    c.save("orders_list", c.api("GET", "/orders/", cust, params={"page": 1, "page_size": 20}), 200)
    deliveries = c.save("helm_dash_deliveries", c.api("GET", "/helm-dash/deliveries", cust), 200)
    delivery = next(d for d in deliveries if d["order_id"] == hd["id"])
    did = delivery["id"]
    c.save("helm_dash_delivery_awaiting_dispatch", c.api("GET", f"/helm-dash/deliveries/{did}", cust), 200)
    c.save("error_delivery_not_found", c.api("GET", f"/helm-dash/deliveries/{did}", other), 404)

    print("== admin: areas, operator profile")
    c.save("error_forbidden", c.api("GET", "/dispatch/deliveries", cust), 403)
    c.save("dispatch_areas", c.api("GET", "/dispatch/areas", admin), 200)
    area_id = delivery["area_id"]
    c.save(
        "dispatch_operator_created",
        c.api(
            "POST",
            "/dispatch/operators",
            admin,
            json={
                "user_id": op_user["id"],
                "display_name": f"Skipper Fixture {run[:4]}",
                "vessel_name": "MV Fixture Runner",
                "area_id": area_id,
                "certification_reference": "Unverified test reference",
            },
        ),
        201,
    )
    c.save("error_operator_not_active", c.api("PUT", "/dispatch/me/availability", op, json={"is_online": True}), 403)
    c.save("dispatch_operator_activated", c.api("POST", f"/dispatch/operators/{op_user['id']}/activate", admin), 200)

    print("== dispatcher console")
    c.save("dispatch_deliveries", c.api("GET", "/dispatch/deliveries", disp, params={"active_only": "true"}), 200)
    c.save("dispatch_operators", c.api("GET", "/dispatch/operators", disp, params={"area_id": area_id, "active": "true"}), 200)
    c.save("dispatch_delivery_detail_awaiting", c.api("GET", f"/dispatch/deliveries/{did}", disp), 200)
    c.save(
        "dispatch_delivery_assigned",
        c.api("POST", f"/dispatch/deliveries/{did}/assign", disp, json={"operator_id": op_user["id"], "note": "Nearest skipper"}),
        200,
    )
    c.save(
        "error_already_assigned",
        c.api("POST", f"/dispatch/deliveries/{did}/assign", disp, json={"operator_id": op_user["id"]}),
        409,
    )

    print("== operator jobs")
    c.save("operator_me", c.api("GET", "/dispatch/me", op), 200)
    c.save("operator_availability", c.api("PUT", "/dispatch/me/availability", op, json={"is_online": True}), 200)
    c.save("operator_jobs", c.api("GET", "/dispatch/jobs", op), 200)
    c.save("operator_job_accepted", c.api("POST", f"/dispatch/jobs/{did}/accept", op), 200)
    c.save("helm_dash_delivery_awaiting_position", c.api("GET", f"/helm-dash/deliveries/{did}", cust), 200)
    c.save("operator_job_picked_up", c.api("POST", f"/dispatch/jobs/{did}/status", op, json={"status": "picked_up"}), 200)
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    c.save(
        "error_location_stale",
        c.api("POST", f"/dispatch/jobs/{did}/location", op, json={"lat": -36.84, "lng": 174.76, "recorded_at": stale}),
        422,
    )
    c.save(
        "error_invalid_transition",
        c.api("POST", f"/dispatch/jobs/{did}/status", op, json={"status": "delivered"}),
        409,
    )
    print("   simulate-delivery (labelled simulated):", c.cli("simulate-delivery", did, "--steps", "1", "--interval", "0").strip())
    c.save("helm_dash_delivery_simulated_location", c.api("GET", f"/helm-dash/deliveries/{did}", cust), 200)
    c.save(
        "operator_location_created",
        c.api(
            "POST",
            f"/dispatch/jobs/{did}/location",
            op,
            json={
                "lat": -36.82,
                "lng": 174.80,
                "accuracy_m": 12.0,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
        ),
        201,
    )
    c.save("helm_dash_delivery_device_location", c.api("GET", f"/helm-dash/deliveries/{did}", cust), 200)
    c.save("operator_job_detail", c.api("GET", f"/dispatch/jobs/{did}", op), 200)
    c.save("dispatch_delivery_detail", c.api("GET", f"/dispatch/deliveries/{did}", disp), 200)
    c.ok(c.api("POST", f"/dispatch/jobs/{did}/status", op, json={"status": "en_route"}), 200)
    c.save("operator_job_delivered", c.api("POST", f"/dispatch/jobs/{did}/status", op, json={"status": "delivered"}), 200)
    c.save("helm_dash_delivery_delivered", c.api("GET", f"/helm-dash/deliveries/{did}", cust), 200)
    c.save("operator_jobs_finished", c.api("GET", "/dispatch/jobs", op, params={"include_finished": "true"}), 200)

    print("== payouts and reconciliation")
    payouts = c.save("dispatch_payouts", c.api("GET", "/dispatch/payouts", admin, params={"operator_id": op_user["id"]}), 200)
    if payouts:
        c.save("error_rate_unconfigured", c.api("POST", f"/dispatch/payouts/{payouts[0]['id']}/approve", admin), 409)
    c.save("dispatch_reconciliation", c.api("GET", "/dispatch/reconciliation", admin), 200)

    print("== staff orders")
    c.save(
        "staff_orders_list",
        c.api("GET", "/orders/admin/all", disp, params={"user_id": c.ok(c.api("GET", "/auth/me", cust), 200)["id"]}),
        200,
    )
    c.save("error_invalid_filter", c.api("GET", "/orders/admin/all", disp, params={"status": "bogus"}), 422)
    c.save("staff_order_detail", c.api("GET", f"/orders/admin/{order['id']}", disp), 200)
    c.save(
        "staff_order_fulfilment",
        c.api("PATCH", f"/orders/{order['id']}/fulfilment", disp, json={"status": "ready_for_dispatch"}),
        200,
    )
    c.save("staff_order_shipment", c.api("POST", f"/orders/{order['id']}/shipment", disp), 201)
    c.save("error_not_a_courier_order", c.api("POST", f"/orders/{hd['id']}/shipment", disp), 409)
    c.save("order_with_test_tracking", c.api("GET", f"/orders/{order['id']}", cust), 200)
    c.save(
        "error_refund_forbidden",
        c.api(
            "POST",
            f"/orders/{order['id']}/refund",
            disp,
            json={"amount_cents": 100, "reason": "Fixture partial refund"},
            headers={"Idempotency-Key": f"cap-refund-denied-{run}"},
        ),
        403,
    )
    c.save(
        "order_refund",
        c.api(
            "POST",
            f"/orders/{order['id']}/refund",
            admin,
            json={"amount_cents": 500, "reason": "Fixture partial refund"},
            headers={"Idempotency-Key": f"cap-refund-{run}"},
        ),
        202,
    )
    c.save("order_partially_refunded", c.api("GET", f"/orders/{order['id']}", cust), 200)

    print(f"\nWrote {len(c.written)} fixtures to {c.out}:")
    for w in c.written:
        print("  ", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
