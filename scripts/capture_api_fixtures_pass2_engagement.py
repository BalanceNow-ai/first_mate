#!/usr/bin/env python3
"""Capture REAL API payloads for the engagement client (First Mate, Crew Rewards,
content, admin curation) as Flutter contract-test fixtures.

Drives the running local stack (``scripts/local_stack.sh up`` + seed) through the
reverse proxy with REAL GoTrue accounts (confirmation-required signup, confirmation
link from the Mailpit sink, password sign-in) — no minted tokens. Points are earned
only by paying for orders through the local TEST MODE payment flow; the admin role is
granted with the ``grant-role`` CLI. Every response body is saved verbatim into
``frontend/test/fixtures/api/engagement/<name>.json``; nothing is hand-written.

Side effects on the shared development stack (all through public/admin APIs):
* four throwaway accounts ``eng-*-<run>@example.test``;
* one paid order of ``SYN-OIL-150``; the stock it consumed is restored afterwards by the
  admin stock-adjust endpoint (audited);
* fitment rules created for a fictional engine (``Fixturesynth``) that no real vessel
  matches, then deleted; a synthetic knowledge source ingested, admitted, revoked and
  deleted.

Usage::

    python3 scripts/capture_api_fixtures_pass2_engagement.py \
        [--base http://localhost:18080] [--mailpit http://localhost:18025] \
        [--stack-root /path/to/checkout/with/.env]

``SUPABASE_JWT_SECRET`` is read from the environment or ``<stack-root>/.env`` (used only
to derive the public anon key GoTrue expects as ``apikey``).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "test" / "fixtures" / "api" / "engagement"


def anon_key(secret: str) -> str:
    def b64(d: bytes) -> str:
        return base64.urlsafe_b64encode(d).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({"role": "anon", "iss": "supabase", "iat": now, "exp": now + 3600}).encode())
    sig = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def read_secret(stack_root: Path) -> str:
    if os.environ.get("SUPABASE_JWT_SECRET"):
        return os.environ["SUPABASE_JWT_SECRET"]
    env = stack_root / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            m = re.match(r"^\s*SUPABASE_JWT_SECRET=(.*)$", line)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    raise SystemExit("SUPABASE_JWT_SECRET not found (env or <stack-root>/.env)")


class Stack:
    def __init__(self, base: str, mailpit: str, anon: str, out: Path) -> None:
        self.base, self.mailpit, self.anon, self.out = base.rstrip("/"), mailpit.rstrip("/"), anon, out
        self.http = httpx.Client(timeout=60)
        self.written: list[str] = []

    # ------------------------------------------------------------------ transport
    def auth(self, path: str, body: dict, **params) -> httpx.Response:
        return self.http.post(
            f"{self.base}/auth/v1/{path}", json=body, params=params,
            headers={"apikey": self.anon, "Authorization": f"Bearer {self.anon}"},
        )

    def api(self, method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for _ in range(30):
            try:
                resp = self.http.request(method, f"{self.base}/api/v1{path}", headers=headers, **kw)
            except httpx.TransportError:
                time.sleep(2)
                continue
            # The shared stack's API container may be restarting (proxy 502 HTML page).
            if resp.status_code == 502 and "json" not in resp.headers.get("content-type", ""):
                time.sleep(2)
                continue
            return resp
        raise SystemExit(f"{method} {path}: API unreachable")

    # -------------------------------------------------------------------- capture
    def save(self, name: str, resp: httpx.Response, expect: int) -> dict | list | None:
        if resp.status_code != expect:
            raise SystemExit(
                f"{resp.request.method} {resp.request.url} -> {resp.status_code}, expected {expect}: {resp.text[:800]}"
            )
        body = resp.json() if resp.content else None
        if name:
            self.out.mkdir(parents=True, exist_ok=True)
            path = self.out / f"{name}.json"
            path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
            self.written.append(f"{name}.json  ({resp.request.method} {resp.request.url.path} {resp.status_code})")
        return body

    def ok(self, resp: httpx.Response, expect: int) -> dict | list | None:
        return self.save("", resp, expect)

    # --------------------------------------------------------------------- people
    def confirmation_link(self, email: str, timeout: float = 45) -> str:
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

    def account(self, email: str, password: str, name: str) -> str:
        r = self.auth("signup", {"email": email, "password": password, "data": {"full_name": name}})
        if r.status_code != 200:
            raise SystemExit(f"signup failed: {r.status_code} {r.text}")
        self.http.get(self.confirmation_link(email), follow_redirects=False)
        r = self.auth("token", {"email": email, "password": password}, grant_type="password")
        if r.status_code != 200:
            raise SystemExit(f"sign-in failed: {r.status_code} {r.text}")
        token = r.json()["access_token"]
        self.ok(self.api("POST", "/auth/provision", token, json={"full_name": name}), 201)
        return token


def pay_order(s: Stack, tok: str, run: str, address_name: str) -> dict:
    """Checkout the current cart by courier and pay through the local TEST MODE flow."""
    q = s.ok(s.api("POST", "/shipping/quotes", tok, json={"delivery_type": "courier", "destination": {"postcode": "1010"}}), 201)
    body = {
        "delivery_type": "courier", "quote_id": q["id"],
        "shipping_address": {"name": address_name, "line1": "1 Quay St", "city": "Auckland",
                             "postcode": "1010", "phone": "021 000 000"},
    }
    order = s.ok(s.api("POST", "/orders/checkout", tok, json=body, headers={"Idempotency-Key": f"eng-{run}-{uuid.uuid4().hex[:6]}"}), 201)
    r = s.api("POST", f"/payments/orders/{order['id']}/intent", tok)
    if r.status_code not in (200, 201):
        raise SystemExit(f"intent failed {r.status_code} {r.text}")
    pi = r.json()
    paid = s.api("POST", f"/payments/local/{pi['payment_intent_id']}/confirm", tok, json={"outcome": "succeed"}).json()
    if paid.get("order_status") != "paid":
        raise SystemExit(f"payment did not succeed: {paid}")
    return order


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("HELM_PUBLIC_URL", "http://localhost:18080"))
    ap.add_argument("--mailpit", default="http://localhost:18025")
    ap.add_argument("--stack-root", default=str(REPO), help="checkout whose .env and scripts/local_stack.sh run the stack")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    stack_root = Path(a.stack_root)
    s = Stack(a.base, a.mailpit, anon_key(read_secret(stack_root)), Path(a.out))
    run = uuid.uuid4().hex[:8]
    pw = f"Pw-{uuid.uuid4().hex}"

    def grant(email: str, role: str) -> None:
        subprocess.run([str(stack_root / "scripts" / "local_stack.sh"), "cli", "grant-role", email, role],
                       check=True, cwd=stack_root, stdout=subprocess.DEVNULL)

    # ------------------------------------------------------------------ accounts
    email_a, email_b = f"eng-skipper-{run}@example.test", f"eng-mate-{run}@example.test"
    email_c, email_d = f"eng-admin-{run}@example.test", f"eng-chatty-{run}@example.test"
    tok_a = s.account(email_a, pw, "Fixture Skipper")
    tok_b = s.account(email_b, pw, "Fixture Mate")
    tok_c = s.account(email_c, pw, "Fixture Admin")
    tok_d = s.account(email_d, pw, "Fixture Chatty")
    grant(email_c, "admin")
    print(f"accounts ready ({run})")

    # ---------------------------------------------------------------- First Mate
    f150 = s.ok(s.api("POST", "/vessels/", tok_a, json={
        "nickname": "Kahawai", "make": "Stabicraft", "model": "2050 Supercab", "year": 2021,
        "engine_make": "Yamaha", "engine_model": "F150", "engine_year": 2021, "propulsion_type": "outboard"}), 201)
    hx90 = s.ok(s.api("POST", "/vessels/", tok_a, json={
        "nickname": "Synth Test", "make": "Testcraft", "model": "T5", "year": 2020,
        "engine_make": "Helmsynth", "engine_model": "HX90", "propulsion_type": "outboard"}), 201)
    grounded = s.save("ai_chat_grounded", s.api("POST", "/ai/chat", tok_a, json={
        "message": "Which spark plug does my Yamaha F150 need?", "vessel_id": f150["id"]}), 200)
    assert grounded["grounding"]["status"] == "grounded", grounded["grounding"]
    assert grounded["citations"] and grounded["actions"], "grounded answer needs citations and actions"
    follow = s.save("ai_chat_followup", s.api("POST", "/ai/chat", tok_a, json={
        "message": "How often should I change the oil filter?", "conversation_id": grounded["conversation_id"]}), 200)
    assert follow["conversation_id"] == grounded["conversation_id"]

    insufficient = None
    for q in ("What colour should I paint my anchor locker?",
              "How do I tune a ukulele on board?",
              "Which teak oil is best for a cockpit table?"):
        r = s.api("POST", "/ai/chat", tok_a, json={"message": q, "vessel_id": f150["id"]})
        if r.status_code == 200 and r.json()["grounding"]["status"] == "insufficient_evidence":
            insufficient = s.save("ai_chat_insufficient_evidence", r, 200)
            break
    if insufficient is None:
        raise SystemExit("could not obtain an insufficient_evidence answer")
    conflicting = s.save("ai_chat_conflicting", s.api("POST", "/ai/chat", tok_a, json={
        "message": "Which spark plug does my Helmsynth HX90 need?", "vessel_id": hx90["id"]}), 200)
    assert conflicting["grounding"]["status"] == "conflicting", conflicting["grounding"]

    s.save("ai_conversations", s.api("GET", "/ai/conversations", tok_a), 200)
    s.save("ai_conversation_detail", s.api("GET", f"/ai/conversations/{grounded['conversation_id']}", tok_a), 200)
    s.ok(s.api("DELETE", f"/ai/conversations/{conflicting['conversation_id']}", tok_a), 204)
    s.save("error_conversation_not_found", s.api("GET", f"/ai/conversations/{conflicting['conversation_id']}", tok_a), 404)
    s.save("error_message_too_long", s.api("POST", "/ai/chat", tok_a, json={"message": "x" * 2001}), 422)
    s.save("ai_specialists", s.api("GET", "/ai/specialists"), 200)
    # Rate limit (per user per minute) on a throwaway account.
    for _ in range(30):
        r = s.api("POST", "/ai/chat", tok_d, json={"message": "Hi"})
        if r.status_code == 429:
            s.save("error_rate_limited", r, 429)
            break
    else:
        raise SystemExit("rate limit not reached")
    print("First Mate captured")

    # ------------------------------------------------------------------- content
    articles = s.save("content_articles", s.api("GET", "/content/articles"), 200)
    s.save("content_article_detail", s.api("GET", f"/content/articles/{articles['items'][0]['slug']}"), 200)
    s.save("error_article_not_found", s.api("GET", "/content/articles/no-such-article"), 404)

    # ------------------------------------------------------------- Crew Rewards
    s.save("loyalty_points_empty", s.api("GET", "/loyalty/points", tok_a), 200)
    s.save("loyalty_transactions_empty", s.api("GET", "/loyalty/transactions", tok_a), 200)
    s.save("loyalty_multiplier_no_crew", s.api("GET", "/loyalty/multiplier", tok_a), 200)
    s.save("error_not_in_crew", s.api("GET", "/loyalty/crews/mine", tok_a), 404)
    s.save("loyalty_entitlements_empty", s.api("GET", "/loyalty/entitlements", tok_a), 200)
    s.save("loyalty_redemptions_empty", s.api("GET", "/loyalty/redemptions", tok_a), 200)
    s.save("loyalty_experiences", s.api("GET", "/loyalty/experiences", tok_a), 200)
    s.save("loyalty_invites_empty", s.api("GET", "/loyalty/invites", tok_b), 200)

    # Earn points: pay for 25 x SYN-OIL-150 through the TEST MODE flow.
    products = s.ok(s.api("GET", "/products/", tok_a, params={"search": "SYN-OIL-150", "limit": 50}), 200)["items"]
    oil = next(p for p in products if p["sku"] == "SYN-OIL-150")
    qty = 25
    s.ok(s.api("POST", "/cart/items", tok_a, json={"product_id": oil["id"], "quantity": qty}), 201)
    order = pay_order(s, tok_a, run, "Fixture Skipper")
    s.ok(s.api("POST", f"/products/{oil['id']}/stock", tok_c, json={"delta": qty, "reason": f"fixture capture {run}: restore"}), 200)

    s.save("loyalty_points", s.api("GET", "/loyalty/points", tok_a), 200)
    s.save("error_invalid_points", s.api("POST", "/loyalty/redeem/discount", tok_a, json={"points": 150}), 422)
    s.save("error_insufficient_points", s.api("POST", "/loyalty/redeem/discount", tok_a, json={"points": 1_000_000}), 409)
    first = s.save("loyalty_discount_redeemed", s.api("POST", "/loyalty/redeem/discount", tok_a, json={"points": 100},
                                                      headers={"Idempotency-Key": f"eng-{run}-d1"}), 201)
    s.save("loyalty_entitlement_voided", s.api("POST", f"/loyalty/entitlements/{first['id']}/void", tok_a), 200)
    s.save("error_entitlement_not_voidable", s.api("POST", f"/loyalty/entitlements/{first['id']}/void", tok_a), 409)
    s.ok(s.api("POST", "/loyalty/redeem/discount", tok_a, json={"points": 100}, headers={"Idempotency-Key": f"eng-{run}-d2"}), 201)
    s.save("loyalty_entitlements", s.api("GET", "/loyalty/entitlements", tok_a), 200)

    s.save("error_experience_unavailable", s.api("POST", "/loyalty/redeem/experience", tok_a,
                                                  json={"experience_id": "synthetic-sold-out"}), 409)
    red = s.save("loyalty_experience_redeemed", s.api("POST", "/loyalty/redeem/experience", tok_a, json={
        "experience_id": "synthetic-test-day-trip", "note": "Two people, any Saturday"}), 201)

    # Crew: A creates and invites B; B accepts.
    s.save("error_validation_crew_name", s.api("POST", "/loyalty/crews", tok_a, json={"name": "X"}), 422)
    s.save("loyalty_crew_created", s.api("POST", "/loyalty/crews", tok_a, json={"name": f"Fixture Crew {run}"}), 201)
    inv_b = s.save("loyalty_crew_invite_created", s.api("POST", "/loyalty/crews/mine/invites", tok_a, json={"email": email_b}), 201)
    inv_d = s.ok(s.api("POST", "/loyalty/crews/mine/invites", tok_a, json={"email": email_d}), 201)
    s.save("loyalty_crew_invites", s.api("GET", "/loyalty/crews/mine/invites", tok_a), 200)
    s.save("loyalty_crew_invite_revoked", s.api("DELETE", f"/loyalty/crews/mine/invites/{inv_d['id']}", tok_a), 200)
    s.save("error_not_in_crew_invite", s.api("POST", "/loyalty/crews/mine/invites", tok_b, json={"email": email_d}), 404)
    s.save("loyalty_invites", s.api("GET", "/loyalty/invites", tok_b), 200)
    s.save("loyalty_invite_accepted", s.api("POST", f"/loyalty/invites/{inv_b['id']}/accept", tok_b), 200)
    s.save("loyalty_crew_member_view", s.api("GET", "/loyalty/crews/mine", tok_b), 200)
    s.save("error_captain_only", s.api("POST", "/loyalty/crews/mine/invites", tok_b, json={"email": email_d}), 403)
    s.save("loyalty_crew_captain_view", s.api("GET", "/loyalty/crews/mine", tok_a), 200)
    s.save("loyalty_points_in_crew", s.api("GET", "/loyalty/points", tok_a), 200)
    s.save("loyalty_multiplier", s.api("GET", "/loyalty/multiplier", tok_a), 200)
    # D: invite then decline.
    inv_d2 = s.ok(s.api("POST", "/loyalty/crews/mine/invites", tok_a, json={"email": email_d}), 201)
    s.save("loyalty_invite_declined", s.api("POST", f"/loyalty/invites/{inv_d2['id']}/decline", tok_d), 200)

    # Ledger (paginated).
    s.save("loyalty_transactions", s.api("GET", "/loyalty/transactions", tok_a, params={"limit": 3, "offset": 0}), 200)
    s.save("loyalty_transactions_page2", s.api("GET", "/loyalty/transactions", tok_a, params={"limit": 3, "offset": 3}), 200)

    # Equipment profile verification: B submits twice; admin rejects, then approves.
    cats = s.ok(s.api("GET", "/boat-db/equipment-categories", tok_b), 200)
    cat = cats[0]["slug"]
    vb = s.ok(s.api("POST", "/vessels/", tok_b, json={"nickname": "Mate's Tinny", "make": "Quintrex", "model": "420",
                                                       "year": 2015, "engine_make": "Suzuki", "engine_model": "DF140"}), 201)
    s.ok(s.api("POST", f"/vessels/{vb['id']}/equipment", tok_b, json={"category": cat, "make": "Fixturemake", "model": "FM-1"}), 201)
    s.ok(s.api("POST", f"/vessels/{vb['id']}/equipment/verification-requests", tok_b, json={"note": "Photos of the plate available"}), 201)
    queue = s.save("admin_verification_requests", s.api("GET", "/boat-db/verification-requests", tok_c), 200)
    mine = [q for q in queue if q["vessel_id"] == vb["id"]]
    s.save("admin_verification_rejected", s.api("POST", f"/boat-db/verification-requests/{mine[0]['id']}/reject", tok_c,
                                                json={"review_note": "Serial plate photo unreadable"}), 200)
    s.ok(s.api("POST", f"/vessels/{vb['id']}/equipment/verification-requests", tok_b, json={"note": "Clearer photo attached"}), 201)
    queue = s.ok(s.api("GET", "/boat-db/verification-requests", tok_c), 200)
    mine = [q for q in queue if q["vessel_id"] == vb["id"]]
    s.save("admin_verification_approved", s.api("POST", f"/boat-db/verification-requests/{mine[0]['id']}/approve", tok_c,
                                                json={"review_note": "Matches the builder's plate"}), 200)

    # Admin: experience redemptions — A's is confirmed then fulfilled; B's is cancelled.
    red_b = s.ok(s.api("POST", "/loyalty/redeem/experience", tok_b, json={"experience_id": "synthetic-test-day-trip"}), 201)
    s.save("loyalty_redemptions", s.api("GET", "/loyalty/redemptions", tok_a), 200)
    s.save("admin_redemptions", s.api("GET", "/loyalty/admin/redemptions", tok_c, params={"status": "requested"}), 200)
    s.save("admin_redemption_confirmed", s.api("POST", f"/loyalty/admin/redemptions/{red['id']}/confirm", tok_c,
                                               json={"staff_note": "Booked for Saturday"}), 200)
    s.save("admin_redemption_fulfilled", s.api("POST", f"/loyalty/admin/redemptions/{red['id']}/fulfil", tok_c), 200)
    s.save("error_invalid_transition", s.api("POST", f"/loyalty/admin/redemptions/{red['id']}/confirm", tok_c), 409)
    s.save("admin_redemption_cancelled", s.api("POST", f"/loyalty/admin/redemptions/{red_b['id']}/cancel", tok_c,
                                               json={"staff_note": "Date unavailable"}), 200)
    s.save("loyalty_transactions_member", s.api("GET", "/loyalty/transactions", tok_b), 200)

    # Crew membership changes: captain removes D? (D declined) — A removes B, B rejoins, A leaves (hand-over).
    s.save("error_use_leave", s.api("DELETE", f"/loyalty/crews/mine/members/{s.api('GET', '/auth/me', tok_a).json()['id']}", tok_a), 409)
    b_id = s.ok(s.api("GET", "/auth/me", tok_b), 200)["id"]
    s.ok(s.api("DELETE", f"/loyalty/crews/mine/members/{b_id}", tok_a), 204)
    inv_b2 = s.ok(s.api("POST", "/loyalty/crews/mine/invites", tok_a, json={"email": email_b}), 201)
    s.ok(s.api("POST", f"/loyalty/invites/{inv_b2['id']}/accept", tok_b), 200)
    s.save("loyalty_leave_handover", s.api("POST", "/loyalty/crews/mine/leave", tok_a), 200)
    s.save("loyalty_leave_disbanded", s.api("POST", "/loyalty/crews/mine/leave", tok_b), 200)
    print("Crew Rewards captured")

    # ------------------------------------------------------------ admin curation
    s.save("error_forbidden", s.api("GET", "/admin/users", tok_a), 403)
    belt = next(p for p in s.ok(s.api("GET", "/products/", tok_c, params={"search": "SYN-BELT-UNI"}), 200)["items"]
                if p["sku"] == "SYN-BELT-UNI")
    rule_body = {"engine_make": "Fixturesynth", "engine_model": f"FX-{run}", "fitment_type": "service_part",
                 "data_source": "fixture_capture", "confidence_score": 0.3, "notes": "Fixture rule — fictional engine"}
    r1 = s.ok(s.api("POST", f"/products/{belt['id']}/fitment-rules", tok_c, json=rule_body), 201)
    r2 = s.ok(s.api("POST", f"/products/{belt['id']}/fitment-rules", tok_c,
                    json={**rule_body, "engine_model": f"FY-{run}"}), 201)
    queue = s.ok(s.api("GET", "/products/fitment-rules", tok_c, params={"verification_status": "unverified", "limit": 500}), 200)
    mine = [r for r in queue if r["id"] in (r1["id"], r2["id"])]
    (s.out / "admin_fitment_rules_unverified.json").write_text(json.dumps(mine, indent=2, ensure_ascii=False) + "\n")
    s.written.append("admin_fitment_rules_unverified.json  (GET /products/fitment-rules?verification_status=unverified 200; "
                     "filtered to this run's rules)")
    s.save("error_confidence_too_low", s.api("POST", f"/products/fitment-rules/{r1['id']}/verify", tok_c,
                                             json={"confidence_score": 0.5}), 422)
    s.save("admin_fitment_rule_verified", s.api("POST", f"/products/fitment-rules/{r1['id']}/verify", tok_c,
                                                json={"confidence_score": 0.8, "notes": "Checked against the parts list"}), 200)
    s.save("admin_fitment_rule_rejected", s.api("POST", f"/products/fitment-rules/{r2['id']}/reject", tok_c,
                                                json={"notes": "Wrong engine family"}), 200)
    for rid in (r1["id"], r2["id"]):
        s.ok(s.api("DELETE", f"/products/fitment-rules/{rid}", tok_c), 204)

    s.save("admin_knowledge_sources", s.api("GET", "/knowledge/sources", tok_c, params={"limit": 5}), 200)
    doc = (f"# Fixture anchoring note {run}\n\nSynthetic fixture used only to capture the admin contract. "
           "Not real guidance.\n\n## Scope\n\nThis note exists to exercise ingest, admit, revoke and delete.\n")
    ingest = {"title": f"[SYNTHETIC] Fixture anchoring note {run}", "publisher": "Helm fixture capture",
              "licence": "Synthetic test fixture (no licence required)", "licence_verified": False,
              "domain": "anchoring", "is_synthetic": True, "format": "markdown", "content": doc}
    created = s.save("admin_knowledge_ingested", s.api("POST", "/knowledge/sources", tok_c, json=ingest), 201)
    s.save("admin_knowledge_ingest_unchanged", s.api("POST", "/knowledge/sources", tok_c, json=ingest), 200)
    real = {**ingest, "title": f"Fixture licensed note {run}", "is_synthetic": False,
            "licence": "CC BY 4.0 (unverified)", "content": doc + "\nLicensed variant.\n", "url": "https://example.test/note"}
    real_src = s.ok(s.api("POST", "/knowledge/sources", tok_c, json=real), 201)["source"]
    s.save("error_licence_not_verified", s.api("POST", f"/knowledge/sources/{real_src['id']}/admit", tok_c), 409)
    sid = created["source"]["id"]
    s.save("admin_knowledge_admitted", s.api("POST", f"/knowledge/sources/{sid}/admit", tok_c, json={"licence_verified": True}), 200)
    s.save("admin_knowledge_reembedded", s.api("POST", f"/knowledge/sources/{sid}/reembed", tok_c), 200)
    s.save("admin_knowledge_revoked", s.api("POST", f"/knowledge/sources/{sid}/revoke", tok_c), 200)
    for x in (sid, real_src["id"]):
        s.ok(s.api("DELETE", f"/knowledge/sources/{x}", tok_c), 204)

    s.save("admin_users", s.api("GET", "/admin/users", tok_c, params={"email": run}), 200)
    d_id = s.ok(s.api("GET", "/auth/me", tok_d), 200)["id"]
    s.save("admin_user_role_updated", s.api("PUT", f"/admin/users/{d_id}/role", tok_c, json={"role": "operator"}), 200)
    s.save("error_validation_role", s.api("PUT", f"/admin/users/{d_id}/role", tok_c, json={"role": "pirate"}), 422)
    s.ok(s.api("PUT", f"/admin/users/{d_id}/role", tok_c, json={"role": "customer"}), 200)
    s.save("admin_audit", s.api("GET", "/admin/audit", tok_c, params={"limit": 25}), 200)
    s.save("helm_dash_deliveries_empty", s.api("GET", "/helm-dash/deliveries", tok_a), 200)
    print(f"order {order['order_number'] if 'order_number' in order else order['id']} paid; admin captured")

    print("\nWrote:")
    for w in s.written:
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
