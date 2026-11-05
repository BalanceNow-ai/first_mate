#!/usr/bin/env python3
"""Container-level API journey against the local stack (scripts/local_stack.sh up + seed).

Uses the REAL local identity provider (GoTrue) through the reverse proxy — no minted
tokens — and the Mailpit sink for confirmation emails. Exercises: confirmation-required
signup, confirm link, sign-in, provisioning, refresh, cross-account isolation, vessel,
compatible catalogue, grounded First Mate answer + explicit cart action, checklist,
courier quote, checkout, local test payment (signed webhook path), points, order
confirmation email in the sink, logout (refresh token revoked).

Usage: python3 scripts/e2e/api_journey.py [--base http://localhost:18080] [--mailpit http://localhost:18025]
Exit status 0 only if every step passes.
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

import httpx

STEPS: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}", flush=True)
    if not ok:
        raise SystemExit(summary(1))


def summary(code: int) -> int:
    passed = sum(1 for _, ok, _ in STEPS if ok)
    print(f"\n{passed}/{len(STEPS)} steps passed")
    return code


def anon_key(secret: str) -> str:
    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({"role": "anon", "iss": "supabase", "iat": int(time.time()),
                              "exp": int(time.time()) + 3600}).encode())
    sig = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


class Stack:
    def __init__(self, base: str, mailpit: str, anon: str) -> None:
        self.base, self.mailpit = base.rstrip("/"), mailpit.rstrip("/")
        self.http = httpx.Client(timeout=30)
        self.anon = anon

    def auth(self, path: str, body: dict, **params) -> httpx.Response:
        return self.http.post(f"{self.base}/auth/v1/{path}", json=body, params=params,
                              headers={"apikey": self.anon, "Authorization": f"Bearer {self.anon}"})

    def api(self, method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.http.request(method, f"{self.base}/api/v1{path}", headers=headers, **kw)

    def confirmation_link(self, email: str, timeout: float = 30) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            msgs = self.http.get(f"{self.mailpit}/api/v1/search", params={"query": f"to:{email}"}).json()
            for m in msgs.get("messages", []):
                body = self.http.get(f"{self.mailpit}/api/v1/message/{m['ID']}").json()
                link = re.search(r"https?://[^\s\"'<>]+/verify\?[^\s\"'<>]+", body.get("Text", "") + body.get("HTML", ""))
                if link:
                    return link.group(0).replace("&amp;", "&")
            time.sleep(1)
        raise SystemExit(f"no confirmation email for {email}")

    def emails_to(self, email: str) -> list[str]:
        msgs = self.http.get(f"{self.mailpit}/api/v1/search", params={"query": f"to:{email}"}).json()
        return [m.get("Subject", "") for m in msgs.get("messages", [])]


def signup_confirmed(s: Stack, email: str, password: str, name: str) -> dict:
    r = s.auth("signup", {"email": email, "password": password, "data": {"full_name": name}})
    step(f"signup {email} (confirmation required → no session)", r.status_code == 200 and not r.json().get("access_token"))
    r = s.auth("token", {"email": email, "password": password}, grant_type="password")
    step("sign-in refused before confirmation", r.status_code == 400, r.json().get("error_code", ""))
    link = s.confirmation_link(email)
    r = s.http.get(link, follow_redirects=False)
    step("confirmation link accepted", r.status_code in (302, 303), str(r.status_code))
    r = s.auth("token", {"email": email, "password": password}, grant_type="password")
    step("sign-in after confirmation", r.status_code == 200, str(r.status_code))
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("HELM_PUBLIC_URL", "http://localhost:18080"))
    ap.add_argument("--mailpit", default="http://localhost:18025")
    ap.add_argument("--jwt-secret", default=os.environ.get("SUPABASE_JWT_SECRET", ""))
    a = ap.parse_args()
    if not a.jwt_secret:
        print("SUPABASE_JWT_SECRET (local stack .env) is required to derive the public anon key")
        return 2
    s = Stack(a.base, a.mailpit, anon_key(a.jwt_secret))
    run = uuid.uuid4().hex[:8]
    pw = f"Pw-{uuid.uuid4().hex}"

    step("readiness", s.http.get(f"{a.base}/ready").json().get("ready") is True)
    cfg = s.api("GET", "/config/public").json()
    step("public config: local test payments, AI local substitute flagged",
         cfg["payments"]["local_test_mode"] and cfg["ai"]["local_substitute"])

    sess = signup_confirmed(s, f"skipper-{run}@example.test", pw, "Skipper One")
    tok = sess["access_token"]
    step("anon key is not accepted by the API", s.api("GET", "/auth/me", s.anon).status_code == 401)
    step("unprovisioned profile is refused", s.api("GET", "/vessels/", tok).json().get("code") == "profile_not_provisioned")
    r = s.api("POST", "/auth/provision", tok, json={"full_name": "Skipper One"})
    step("provision 201", r.status_code == 201, r.text[:120])
    step("provision idempotent 200", s.api("POST", "/auth/provision", tok, json={}).status_code == 200)
    r = s.auth("token", {"refresh_token": sess["refresh_token"]}, grant_type="refresh_token")
    step("refresh issues a new session", r.status_code == 200)
    sess = r.json(); tok = sess["access_token"]
    step("refreshed token accepted", s.api("GET", "/auth/me", tok).status_code == 200)

    v = s.api("POST", "/vessels/", tok, json={"nickname": "Kahawai", "make": "Stabicraft", "model": "2050 Supercab",
                                               "year": 2021, "engine_make": "Yamaha", "engine_model": "F150",
                                               "engine_year": 2021, "propulsion_type": "outboard"})
    step("vessel created", v.status_code == 201, v.text[:120]); vessel = v.json()
    r = s.api("GET", "/products/", tok, params={"vessel_id": vessel["id"], "compatible_only": "true", "limit": 100})
    items = r.json()["items"]
    plug = next((p for p in items if p["sku"] == "SYN-PLUG-150"), None)
    step("compatible catalogue contains verified F150 plug", plug is not None and plug["fitment"]["status"] == "verified_fit")
    step("compatible catalogue has no unknown/mismatch items",
         all(p["fitment"]["status"] in ("verified_fit", "universal") for p in items))

    chat = s.api("POST", "/ai/chat", tok, json={"message": "Which spark plug does my Yamaha F150 need?",
                                                "vessel_id": vessel["id"]}).json()
    step("First Mate grounded answer with citation", chat["grounding"]["status"] == "grounded" and bool(chat["citations"]))
    act = next((x for x in chat["actions"] if x["product_id"] == plug["id"]), None)
    step("explicit add-to-cart action offered for the verified part", act is not None)
    step("cart untouched until the user acts", s.api("GET", "/cart/", tok).json()["item_count"] == 0)
    r = s.api("POST", "/cart/items", tok, json={"product_id": act["product_id"], "quantity": act["quantity"]})
    step("action added via normal cart API", r.status_code == 201)

    g = s.api("POST", f"/checklists/vessel/{vessel['id']}/generate", tok)
    step("checklists generated", g.status_code == 201)
    m1 = s.api("POST", f"/checklists/vessel/{vessel['id']}/add-missing-to-cart", tok, json={"tier": "grab_and_go"}).json()
    m2 = s.api("POST", f"/checklists/vessel/{vessel['id']}/add-missing-to-cart", tok, json={"tier": "grab_and_go"}).json()
    step("add-missing repeated adds nothing the second time", m2["added_count"] == 0, f"first={m1['added_count']}")
    exp = s.api("GET", f"/checklists/vessel/{vessel['id']}/export", tok, params={"tier": "grab_and_go", "format": "html"})
    step("printable export with compliance disclaimer", exp.status_code == 200 and "NOT a certified" in exp.text)

    cart = s.api("GET", "/cart/", tok).json()
    q = s.api("POST", "/shipping/quotes", tok, json={"delivery_type": "courier", "destination": {"postcode": "1010"}})
    step("courier quote (development rate card labelled)", q.status_code == 201 and q.json()["development_rate_card"], q.text[:120])
    quote = q.json()
    key = f"e2e-{run}"
    body = {"delivery_type": "courier", "quote_id": quote["id"],
            "shipping_address": {"name": "Skipper One", "line1": "1 Quay St", "city": "Auckland",
                                 "postcode": "1010", "phone": "021 000 000"}}
    o1 = s.api("POST", "/orders/checkout", tok, json=body, headers={"Idempotency-Key": key})
    o2 = s.api("POST", "/orders/checkout", tok, json=body, headers={"Idempotency-Key": key})
    step("checkout 201 then idempotent 200 (double tap)", o1.status_code == 201 and o2.status_code == 200
         and o1.json()["id"] == o2.json()["id"], o1.text[:160])
    order = o1.json()
    expected_ship = 0 if cart["subtotal_cents"] >= cfg["delivery"]["free_shipping_threshold_cents"] else quote["price_cents"]
    step("order total = cart subtotal + server shipping",
         order["total_cents"] == cart["subtotal_cents"] + expected_ship, f"{order['total_cents']}")
    pi = s.api("POST", f"/payments/orders/{order['id']}/intent", tok).json()
    step("payment intent amount equals order total", pi["amount_cents"] == order["total_cents"] and pi["test_mode"])
    d = s.api("POST", f"/payments/local/{pi['payment_intent_id']}/confirm", tok, json={"outcome": "decline"}).json()
    step("declined card leaves order payable", d["order_status"] == "pending_payment" and d["payment_status"] == "failed")
    ok = s.api("POST", f"/payments/local/{pi['payment_intent_id']}/confirm", tok, json={"outcome": "succeed"}).json()
    step("retry succeeds via signed webhook path", ok["order_status"] == "paid")
    bad = s.http.post(f"{a.base}/api/v1/payments/webhook", content=b'{"type":"payment_intent.succeeded"}')
    step("unsigned webhook rejected", bad.status_code == 400)
    pts = s.api("GET", "/loyalty/points", tok).json()
    step("points awarded on paid merchandise", pts["points_balance"] == order["subtotal_cents"] // 100, str(pts["points_balance"]))

    # Second account: confirmation-required signup again; sees none of account 1's data.
    sess2 = signup_confirmed(s, f"mate-{run}@example.test", pw, "Mate Two")
    tok2 = sess2["access_token"]
    s.api("POST", "/auth/provision", tok2, json={"full_name": "Mate Two"})
    step("second account: no vessels, empty cart, no orders",
         s.api("GET", "/vessels/", tok2).json() == [] and s.api("GET", "/cart/", tok2).json()["item_count"] == 0
         and s.api("GET", "/orders/", tok2).json()["total"] == 0)
    step("second account cannot read first account's vessel/order",
         s.api("GET", f"/vessels/{vessel['id']}", tok2).status_code == 404
         and s.api("GET", f"/orders/{order['id']}", tok2).status_code == 404)

    time.sleep(40)  # notification dispatcher runs every 30 s
    subjects = s.emails_to(f"skipper-{run}@example.test")
    step("order confirmation delivered to local mail sink", any("order" in x.lower() for x in subjects), "; ".join(subjects))

    r = s.http.post(f"{a.base}/auth/v1/logout", headers={"apikey": s.anon, "Authorization": f"Bearer {tok}"})
    step("logout", r.status_code in (200, 204))
    r = s.auth("token", {"refresh_token": sess["refresh_token"]}, grant_type="refresh_token")
    step("refresh token revoked after logout", r.status_code != 200, str(r.status_code))
    return summary(0)


if __name__ == "__main__":
    sys.exit(main())
