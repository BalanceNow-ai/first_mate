#!/usr/bin/env python3
"""Capture REAL API payloads for the invoice / moderation Flutter client (workstream F2).

Drives the running local stack (``scripts/local_stack.sh up``) through the reverse proxy
with REAL GoTrue accounts (confirmation-required signup, confirmation link from the
Mailpit sink, password sign-in) — no minted tokens. Invoice documents are synthetic
(generated here: a text-layer PDF and a plain PNG) and go through the real private-media
path: upload intent → PUT raw bytes → scanning/processing → ``available``. Extraction runs
on the stack's ``local_fixture`` provider (a development substitute that reads the PDF
text layer; it proves contracts, not visual accuracy). The moderator role is granted with
the ``grant-role`` CLI; the contractor organization is provisioned with
``create-contractor-org`` / ``add-contractor-member``. Every response body is saved
verbatim into ``frontend/test/fixtures/api/invoices/<name>.json``; nothing is hand-written.

Side effects on the shared development stack (all through public/admin APIs and the
audited provisioning CLI): four throwaway accounts ``inv-*-<run>@example.test``; one
contractor organization ``Fixture Harbour Marine <run>``; a vessel, a service job with an
accepted assignment and an accepted scope; synthetic invoice documents; one reported
review and its resolved moderation case.

Usage::

    python3 scripts/capture_api_fixtures_invoices.py \
        [--base http://localhost:18080] [--mailpit http://localhost:18025] \
        [--stack-root /path/to/checkout/with/.env]
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import re
import struct
import subprocess
import time
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "test" / "fixtures" / "api" / "invoices"


# ----------------------------------------------------------------------------- documents
def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(items: list[tuple[str, float, float, float]]) -> bytes:
    """A minimal valid one-page PDF with a Helvetica text layer: (text, x, y, size)."""
    stream = "".join(
        f"BT /F1 {size:g} Tf 1 0 0 1 {x:g} {y:g} Tm ({_esc(t)}) Tj ET\n" for t, x, y, size in items
    ).encode("latin-1")
    objs = [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> >> "
        b"/Contents 3 0 R >>",
        b"<< /Type /Catalog /Pages 2 0 R >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def invoice_pdf(number: str, rows: list[list[str]], footer: list[tuple[str, str]], extra: list[str]) -> bytes:
    """Synthetic supplier invoice laid out like the backend's test fixtures."""
    items: list[tuple[str, float, float, float]] = []
    y = 800.0
    for label, value in [
        ("Supplier", "Fixture Harbour Marine"),
        ("Invoice No", number),
        ("Date", "2026-10-30"),
        ("Currency", "NZD"),
    ]:
        items.append((f"{label}: {value}", 50, y, 10))
        y -= 16
    y -= 14
    xs = [50, 230, 330, 370, 420, 500]
    for col, x in zip(["Description", "Part No", "Qty", "Unit", "Unit Price", "Amount"], xs, strict=True):
        items.append((col, x, y, 10))
    y -= 16
    for row in rows:
        for cell, x in zip(row, xs, strict=False):
            if cell:
                items.append((cell, x, y, 10))
        y -= 16
    y -= 10
    for label, value in footer:
        items.append((f"{label}: {value}", 330, y, 10))
        y -= 16
    y -= 10
    for line in extra:
        items.append((line, 50, y, 9))
        y -= 14
    return make_pdf(items)


STANDARD_ROWS = [
    ["Labour - replace hose and clamps", "", "2.5", "hr", "95.00", "237.50"],
    ["Sanitation hose 25mm ID", "SH-25", "1.5", "m", "18.40", "27.60"],
    ["S/S hose clamp 316", "HC-316-32", "[hw]3", "ea", "6.50", "26.00"],  # handwritten: low certainty
    ["Call-out fee", "", "1", "", "95.00", "95.00"],
    ["Consumables / sundries", "", "", "", "", "12.00"],
]
STANDARD_FOOTER = [("Subtotal", "398.10"), ("GST", "59.72"), ("Total", "458.82")]
STANDARD_EXTRA = ["Warranty: 12 months on parts supplied", "Bank account: 12-3456-7890123-00"]


def make_png(width: int = 320, height: int = 240) -> bytes:
    """A plain synthetic RGB PNG (no text: the image path reads nothing → manual entry)."""
    rows = []
    for y in range(height):
        row = bytearray(b"\x00")
        for x in range(width):
            row += bytes((240 - (y % 40), 236, 220 + (x % 30)))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
    )


# ----------------------------------------------------------------------------- stack
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

    def auth(self, path: str, body: dict, **params) -> httpx.Response:
        return self.http.post(
            f"{self.base}/auth/v1/{path}",
            json=body,
            params=params,
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
            if resp.status_code == 502 and "json" not in resp.headers.get("content-type", ""):
                time.sleep(2)
                continue
            return resp
        raise SystemExit(f"{method} {path}: API unreachable")

    def save(self, name: str, resp: httpx.Response, expect: int) -> dict | list | None:
        if resp.status_code != expect:
            raise SystemExit(
                f"{resp.request.method} {resp.request.url} -> {resp.status_code}, expected {expect}: {resp.text[:800]}"
            )
        body = resp.json() if resp.content else None
        if name:
            self.out.mkdir(parents=True, exist_ok=True)
            (self.out / f"{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
            self.written.append(f"{name}.json  ({resp.request.method} {resp.request.url.path} {resp.status_code})")
        return body

    def ok(self, resp: httpx.Response, expect: int) -> dict | list | None:
        return self.save("", resp, expect)

    def confirmation_link(self, email: str, timeout: float = 45) -> str:
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

    # ------------------------------------------------------------------- media
    def wait_asset(self, token: str, asset_id: str, name: str = "") -> dict:
        deadline = time.time() + 90
        while time.time() < deadline:
            r = self.api("GET", f"/service-assets/{asset_id}", token)
            body = r.json()
            if body.get("status") in ("available", "rejected"):
                return self.save(name, r, 200)
            time.sleep(1)
        raise SystemExit(f"asset {asset_id} never finished processing")

    def wait_run(self, token: str, invoice_id: str, run_id: str, name: str = "") -> dict:
        deadline = time.time() + 90
        while time.time() < deadline:
            r = self.api("GET", f"/invoices/{invoice_id}/extraction-runs/{run_id}", token)
            if r.json().get("status") not in ("pending", "running"):
                return self.save(name, r, 200)
            time.sleep(1)
        raise SystemExit(f"extraction run {run_id} never finished")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("HELM_PUBLIC_URL", "http://localhost:18080"))
    ap.add_argument("--mailpit", default="http://localhost:18025")
    ap.add_argument("--stack-root", default=str(REPO))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    stack_root = Path(a.stack_root)
    s = Stack(a.base, a.mailpit, anon_key(read_secret(stack_root)), Path(a.out))
    run = uuid.uuid4().hex[:8]
    pw = f"Pw-{uuid.uuid4().hex}"

    def cli(*args: str) -> str:
        out = subprocess.run(
            [str(stack_root / "scripts" / "local_stack.sh"), "cli", *args],
            check=True, cwd=stack_root, capture_output=True, text=True,
        )  # fmt: skip
        return out.stdout

    # ---------------------------------------------------------------- accounts
    emails = {k: f"inv-{k}-{run}@example.test" for k in ("owner", "tech", "moderator", "outsider")}
    tok_owner = s.account(emails["owner"], pw, "Fixture Owner")
    tok_tech = s.account(emails["tech"], pw, "Fixture Technician")
    tok_mod = s.account(emails["moderator"], pw, "Fixture Moderator")
    tok_out = s.account(emails["outsider"], pw, "Fixture Outsider")
    cli("grant-role", emails["moderator"], "moderator")
    org_line = cli("create-contractor-org", f"Fixture Harbour Marine {run}").strip().splitlines()[-1]
    org_id = org_line.split("\t")[0]
    cli("add-contractor-member", org_id, emails["tech"], "--role", "admin")
    s.save("auth_me_owner", s.api("GET", "/auth/me", tok_owner), 200)
    tech_me = s.ok(s.api("GET", "/auth/me", tok_tech), 200)
    s.save("auth_me_moderator", s.api("GET", "/auth/me", tok_mod), 200)
    print(f"accounts ready ({run}); org {org_id}")

    def upload(token: str, intent_path: str, intent_body: dict, data: bytes, prefix: str = "") -> dict:
        intent = s.save(
            f"{prefix}asset_intent" if prefix else "",
            s.api("POST", intent_path, token, json=intent_body, headers={"Idempotency-Key": f"inv-{uuid.uuid4().hex}"}),
            201,
        )
        s.save(
            f"{prefix}asset_content_accepted" if prefix else "",
            s.api(
                "PUT",
                f"/service-assets/{intent['asset']['id']}/content",
                token,
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            ),
            202,
        )
        return s.wait_asset(token, intent["asset"]["id"], f"{prefix}asset_available" if prefix else "")

    # ------------------------------------------------------ standalone invoice (PDF)
    pdf = invoice_pdf(f"INV-{run}-S", STANDARD_ROWS, STANDARD_FOOTER, STANDARD_EXTRA)
    asset = upload(
        tok_owner,
        "/service-assets/invoice-intents",
        {"filename": "harbour-invoice.pdf", "content_type": "application/pdf", "size_bytes": len(pdf)},
        pdf,
        prefix="standalone_",
    )
    created = s.save(
        "invoice_created",
        s.api("POST", "/invoices", tok_owner, json={"asset_id": asset["id"], "title": "Harbour Marine invoice"}),
        201,
    )
    inv = created["id"]
    s.save(
        "invoice_create_existing",
        s.api("POST", "/invoices", tok_owner, json={"asset_id": asset["id"], "title": "Harbour Marine invoice"}),
        200,
    )
    run1 = s.save(
        "extraction_run_queued",
        s.api("POST", f"/invoices/{inv}/extract", tok_owner, headers={"Idempotency-Key": f"inv-extract-{run}-s"}),
        202,
    )
    s.save(
        "error_idempotency_key_required", s.api("POST", f"/invoices/{inv}/extract", tok_owner), 400
    )
    s.wait_run(tok_owner, inv, run1["id"], "extraction_run_done")
    detail = s.save("invoice_extracted", s.api("GET", f"/invoices/{inv}", tok_owner), 200)
    s.save(
        "error_already_extracted",
        s.api("POST", f"/invoices/{inv}/extract", tok_owner, headers={"Idempotency-Key": f"inv-extract-{run}-s2"}),
        409,
    )
    s.save(
        "download_url_derivative",
        s.api("POST", f"/service-assets/{asset['id']}/download-url", tok_owner, json={"variant": "derivative"}),
        200,
    )
    clamp = next(ln for ln in detail["lines"] if (ln["description"] or "").startswith("S/S hose clamp"))
    s.save(
        "error_version_conflict",
        s.api(
            "PATCH",
            f"/invoices/{inv}/lines/{clamp['id']}",
            tok_owner,
            json={"expected_version": clamp["version"] + 5, "quantity": "4"},
        ),
        409,
    )
    s.save(
        "error_needs_confirmation",
        s.api("POST", f"/invoices/{inv}/review", tok_owner, json={"expected_version": detail["revision"]["version"]}),
        409,
    )
    s.save(
        "explanation_provisional",
        s.api("POST", f"/invoices/{inv}/explain", tok_owner),
        201,
    )
    detail = s.save(
        "invoice_line_corrected",
        s.api(
            "PATCH",
            f"/invoices/{inv}/lines/{clamp['id']}",
            tok_owner,
            json={"expected_version": clamp["version"], "quantity": "4"},
        ),
        200,
    )
    detail = s.save(
        "invoice_fields_corrected",
        s.api(
            "PATCH",
            f"/invoices/{inv}/fields",
            tok_owner,
            json={"expected_version": detail["revision"]["version"], "invoice_date": "30 October 2026"},
        ),
        200,
    )
    detail = s.save(
        "invoice_reviewed",
        s.api(
            "POST",
            f"/invoices/{inv}/review",
            tok_owner,
            json={"expected_version": detail["revision"]["version"], "confirm": detail["needs_confirmation"]},
        ),
        200,
    )
    exp = s.save("explanation_standalone", s.api("POST", f"/invoices/{inv}/explain", tok_owner), 201)
    s.save("explanation_unchanged", s.api("POST", f"/invoices/{inv}/explain", tok_owner), 200)
    s.save("invoice_standalone_explained", s.api("GET", f"/invoices/{inv}", tok_owner), 200)
    sugg = exp["content"]["suggested_questions"][0]
    q = s.save(
        "question_draft",
        s.api(
            "POST",
            f"/invoices/{inv}/questions",
            tok_owner,
            json={"text": sugg["text"], "line_id": sugg["line_id"], "suggestion_key": sugg["key"]},
        ),
        201,
    )
    s.save(
        "error_standalone_invoice",
        s.api(
            "POST",
            f"/invoices/{inv}/questions/{q['id']}/send",
            tok_owner,
            json={"expected_version": q["version"], "asset_ids": []},
            headers={"Idempotency-Key": f"inv-send-{run}-s"},
        ),
        409,
    )
    s.save("questions_standalone", s.api("GET", f"/invoices/{inv}/questions", tok_owner), 200)
    s.save("error_invoice_not_found", s.api("GET", f"/invoices/{inv}", tok_out), 404)
    print("standalone invoice captured")

    # ------------------------------------------------------ image invoice → unreadable
    png = make_png()
    img = upload(
        tok_owner,
        "/service-assets/invoice-intents",
        {"filename": "photo-of-invoice.png", "content_type": "image/png", "size_bytes": len(png)},
        png,
        prefix="image_",
    )
    img_inv = s.ok(s.api("POST", "/invoices", tok_owner, json={"asset_id": img["id"], "title": "Photo of invoice"}), 201)
    run_img = s.ok(
        s.api("POST", f"/invoices/{img_inv['id']}/extract", tok_owner, headers={"Idempotency-Key": f"inv-x-{run}-i"}),
        202,
    )
    s.wait_run(tok_owner, img_inv["id"], run_img["id"])
    s.save("invoice_image_unreadable", s.api("GET", f"/invoices/{img_inv['id']}", tok_owner), 200)
    s.save(
        "download_url_image",
        s.api("POST", f"/service-assets/{img['id']}/download-url", tok_owner, json={"variant": "derivative"}),
        200,
    )

    # ------------------------------------------------------ manual entry + delete
    manual = s.save("invoice_manual", s.api("POST", "/invoices", tok_owner, json={"title": "Fuel dock receipt"}), 201)
    manual = s.save(
        "invoice_manual_line_added",
        s.api(
            "POST",
            f"/invoices/{manual['id']}/lines",
            tok_owner,
            json={
                "expected_version": manual["revision"]["version"],
                "kind": "other",
                "description": "Diesel",
                "quantity": "40",
                "unit": "L",
                "unit_price": "2.10",
                "line_total": "84.00",
            },
        ),
        201,
    )
    s.save(
        "error_no_document",
        s.api("POST", f"/invoices/{manual['id']}/extract", tok_owner, headers={"Idempotency-Key": f"inv-x-{run}-m"}),
        409,
    )
    line = manual["lines"][0]
    s.save(
        "invoice_manual_line_removed",
        s.api(
            "DELETE",
            f"/invoices/{manual['id']}/lines/{line['id']}",
            tok_owner,
            params={"expected_version": line["version"]},
        ),
        200,
    )
    s.save("", s.api("DELETE", f"/invoices/{manual['id']}", tok_owner), 204)
    print("image/manual invoices captured")

    # ------------------------------------------------------ job with accepted scope
    vessel = s.ok(
        s.api(
            "POST",
            "/vessels/",
            tok_owner,
            json={
                "nickname": "Kotare",
                "make": "Haines Hunter",
                "model": "SF600",
                "year": 2018,
                "engine_make": "Yamaha",
                "engine_model": "F150",
                "propulsion_type": "outboard",
            },
        ),
        201,
    )
    job = s.ok(
        s.api(
            "POST",
            "/service-jobs/",
            tok_owner,
            json={
                "vessel_id": vessel["id"],
                "title": "Water under the sink when the pump runs",
                "issue_description": "There is water under the galley sink whenever the freshwater pump runs.",
                "affected_system": "plumbing",
                "affected_equipment": "freshwater pump",
                "entry_point": "vessel",
            },
        ),
        201,
    )
    job_id = job["id"]
    assignment = s.ok(
        s.api(
            "POST",
            f"/service-jobs/{job_id}/assignments",
            tok_owner,
            json={"organization_id": org_id, "sections": ["summary", "evidence", "scope", "invoices"]},
            headers={"Idempotency-Key": f"inv-assign-{run}"},
        ),
        201,
    )
    s.ok(
        s.api(
            "POST",
            f"/contractors/assignments/{assignment['id']}/accept",
            tok_tech,
            json={"member_user_ids": [tech_me["id"]]},
        ),
        200,
    )
    scope = s.ok(
        s.api(
            "POST",
            f"/service-jobs/{job_id}/scopes",
            tok_tech,
            json={
                "summary": "Replace the leaking sink hose and clamps",
                "currency": "NZD",
                "estimate_lines": [
                    {"description": "Labour - replace hose and clamps", "kind": "labour", "quantity": "2.5",
                     "unit": "hr", "unit_price_minor": 9500, "amount_minor": 23750},
                    {"description": "Sanitation hose 25mm ID", "kind": "parts", "quantity": "1.5", "unit": "m",
                     "unit_price_minor": 1840, "amount_minor": 2760},
                    {"description": "S/S hose clamp 316", "kind": "parts", "quantity": "4", "unit": "ea",
                     "unit_price_minor": 650, "amount_minor": 2600},
                    {"description": "Call-out fee", "kind": "call_out", "quantity": "1",
                     "unit_price_minor": 8500, "amount_minor": 8500},
                ],
            },  # fmt: skip
        ),
        201,
    )
    s.ok(
        s.api(
            "POST",
            f"/service-jobs/{job_id}/scopes/{scope['id']}/decision",
            tok_owner,
            json={"decision": "accepted", "revision_digest": scope["content_digest"]},
            headers={"Idempotency-Key": f"inv-scope-{run}"},
        ),
        201,
    )
    print(f"job {job_id} with accepted scope ready")

    jpdf = invoice_pdf(f"INV-{run}-J", STANDARD_ROWS, STANDARD_FOOTER, STANDARD_EXTRA)
    jasset = upload(
        tok_owner,
        "/service-assets/invoice-intents",
        {"job_id": job_id, "filename": "job-invoice.pdf", "content_type": "application/pdf", "size_bytes": len(jpdf)},
        jpdf,
    )
    jinv = s.save(
        "invoice_job_created",
        s.api("POST", "/invoices", tok_owner, json={"asset_id": jasset["id"], "job_id": job_id, "title": "Sink repair"}),
        201,
    )
    jrun = s.ok(
        s.api("POST", f"/invoices/{jinv['id']}/extract", tok_owner, headers={"Idempotency-Key": f"inv-x-{run}-j"}),
        202,
    )
    s.wait_run(tok_owner, jinv["id"], jrun["id"])
    jdetail = s.ok(s.api("GET", f"/invoices/{jinv['id']}", tok_owner), 200)
    s.save(
        "explanation_job_provisional",
        s.api("POST", f"/invoices/{jinv['id']}/explain", tok_owner),
        201,
    )
    jdetail = s.ok(
        s.api(
            "POST",
            f"/invoices/{jinv['id']}/review",
            tok_owner,
            json={"expected_version": jdetail["revision"]["version"], "confirm": jdetail["needs_confirmation"]},
        ),
        200,
    )
    jexp = s.save("explanation_job_scope", s.api("POST", f"/invoices/{jinv['id']}/explain", tok_owner), 201)
    s.save("invoice_list", s.api("GET", "/invoices", tok_owner), 200)
    s.save("invoice_list_for_job", s.api("GET", "/invoices", tok_owner, params={"job_id": job_id}), 200)
    s.save("invoice_list_empty", s.api("GET", "/invoices", tok_out), 200)

    additional = next(
        q for q in jexp["content"]["suggested_questions"] if q["key"].startswith("scope:additional")
    )
    jq = s.save(
        "question_job_draft",
        s.api(
            "POST",
            f"/invoices/{jinv['id']}/questions",
            tok_owner,
            json={"text": additional["text"], "line_id": additional["line_id"], "suggestion_key": additional["key"]},
        ),
        201,
    )
    jq = s.save(
        "question_updated",
        s.api(
            "PATCH",
            f"/invoices/{jinv['id']}/questions/{jq['id']}",
            tok_owner,
            json={"expected_version": jq["version"], "text": additional["text"] + " Thanks."},
        ),
        200,
    )
    extra_q = s.ok(
        s.api("POST", f"/invoices/{jinv['id']}/questions", tok_owner, json={"text": "Draft I will delete"}), 201
    )
    s.save("", s.api("DELETE", f"/invoices/{jinv['id']}/questions/{extra_q['id']}", tok_owner), 204)
    s.save("invoice_job_with_draft", s.api("GET", f"/invoices/{jinv['id']}", tok_owner), 200)
    send_key = f"inv-send-{run}-j"
    sent = s.save(
        "question_sent",
        s.api(
            "POST",
            f"/invoices/{jinv['id']}/questions/{jq['id']}/send",
            tok_owner,
            json={"expected_version": jq["version"], "asset_ids": [jasset["id"]]},
            headers={"Idempotency-Key": send_key},
        ),
        200,
    )
    s.save(
        "question_send_repeated",
        s.api(
            "POST",
            f"/invoices/{jinv['id']}/questions/{jq['id']}/send",
            tok_owner,
            json={"expected_version": jq["version"], "asset_ids": [jasset["id"]]},
            headers={"Idempotency-Key": send_key},
        ),
        200,
    )
    s.save("invoice_job_question_sent", s.api("GET", f"/invoices/{jinv['id']}", tok_owner), 200)
    s.save(
        "error_contractor_only",
        s.api("GET", f"/service-jobs/{job_id}/invoice-questions", tok_owner),
        403,
    )
    s.save("error_contractor_questions_not_found", s.api("GET", f"/service-jobs/{job_id}/invoice-questions", tok_out), 404)
    shared = s.save("contractor_questions", s.api("GET", f"/service-jobs/{job_id}/invoice-questions", tok_tech), 200)
    s.save(
        "contractor_question",
        s.api("GET", f"/service-jobs/{job_id}/invoice-questions/{sent['id']}", tok_tech),
        200,
    )
    s.save(
        "contractor_shared_asset_url",
        s.api(
            "GET",
            f"/service-jobs/{job_id}/invoice-questions/{sent['id']}/assets/{shared[0]['shared_assets'][0]['id']}/download-url",
            tok_tech,
        ),
        200,
    )
    corrected_pdf = invoice_pdf(
        f"INV-{run}-J2",
        [
            ["Labour - replace hose and clamps", "", "2.5", "hr", "95.00", "237.50"],
            ["Sanitation hose 25mm ID", "SH-25", "1.5", "m", "18.40", "27.60"],
            ["S/S hose clamp 316", "HC-316-32", "4", "ea", "6.50", "26.00"],
            ["Call-out fee", "", "1", "", "85.00", "85.00"],
        ],
        [("Subtotal", "376.10"), ("GST", "56.42"), ("Total", "432.52")],
        ["Corrected invoice: call-out charged at the quoted rate, sundries removed"],
    )
    casset = upload(
        tok_tech,
        f"/service-jobs/{job_id}/assets/intents",
        {"purpose": "job_document", "filename": "corrected-invoice.pdf", "content_type": "application/pdf",
         "size_bytes": len(corrected_pdf), "caption": "Corrected invoice"},
        corrected_pdf,
        prefix="contractor_",
    )  # fmt: skip
    s.save(
        "contractor_response",
        s.api(
            "POST",
            f"/service-jobs/{job_id}/invoice-questions/{sent['id']}/respond",
            tok_tech,
            json={
                "text": "Sorry — the sundries were not agreed and the call-out should be the quoted rate. "
                "A corrected invoice is attached.",
                "corrected_asset_id": casset["id"],
            },
        ),
        201,
    )
    s.save("invoice_with_response", s.api("GET", f"/invoices/{jinv['id']}", tok_owner), 200)
    s.save("questions_answered", s.api("GET", f"/invoices/{jinv['id']}/questions", tok_owner), 200)
    print("job invoice / questions / contractor response captured")

    # ------------------------------------------------------ a line that can't be compared
    # A job-linked manual invoice whose call-out line has no amount: it matches the accepted
    # scope's "Call-out fee" but can't be compared (never a "match").
    unread = s.ok(s.api("POST", "/invoices", tok_owner, json={"job_id": job_id, "title": "Call-out docket"}), 201)
    unread = s.ok(
        s.api("PATCH", f"/invoices/{unread['id']}/fields", tok_owner,
              json={"expected_version": unread["revision"]["version"], "currency": "NZD"}),
        200,
    )  # fmt: skip
    unread = s.ok(
        s.api(
            "POST",
            f"/invoices/{unread['id']}/lines",
            tok_owner,
            json={"expected_version": unread["revision"]["version"], "kind": "call_out", "description": "Call-out fee",
                  "quantity": "1"},
        ),
        201,
    )  # fmt: skip
    uexp = s.save("explanation_comparison_unavailable", s.api("POST", f"/invoices/{unread['id']}/explain", tok_owner), 201)
    statuses = [i["status"] for i in uexp["content"]["comparison"]["items"]]
    if "comparison_unavailable" not in statuses:
        raise SystemExit(f"expected a comparison_unavailable item, got {statuses}")
    if not any(q["key"].startswith("scope:unreadable:") for q in uexp["content"]["suggested_questions"]):
        raise SystemExit("expected a scope:unreadable suggested question")

    # A job-linked manual invoice that states no currency: its call-out line matches the
    # accepted scope but the amounts are incomparable (invoice_currency_unknown) - never a
    # currency "difference" and never a match.
    nocur = s.ok(s.api("POST", "/invoices", tok_owner, json={"job_id": job_id, "title": "Call-out receipt"}), 201)
    nocur = s.ok(
        s.api(
            "POST",
            f"/invoices/{nocur['id']}/lines",
            tok_owner,
            json={"expected_version": nocur["revision"]["version"], "kind": "call_out", "description": "Call-out fee",
                  "quantity": "1", "unit_price": "85.00", "line_total": "85.00"},
        ),
        201,
    )  # fmt: skip
    cexp = s.save("explanation_currency_unknown", s.api("POST", f"/invoices/{nocur['id']}/explain", tok_owner), 201)
    reasons = [r for i in cexp["content"]["comparison"]["items"] for r in i.get("unavailable_reasons") or []]
    if "invoice_currency_unknown" not in reasons:
        raise SystemExit(f"expected invoice_currency_unknown, got {reasons}")

    # ------------------------------------------------------ invoices section not shared
    job2 = s.ok(
        s.api("POST", "/service-jobs/", tok_owner, json={"vessel_id": vessel["id"], "title": "Bilge pump cycling"}), 201
    )
    a2 = s.ok(
        s.api(
            "POST",
            f"/service-jobs/{job2['id']}/assignments",
            tok_owner,
            json={"organization_id": org_id, "sections": ["summary", "scope"]},
            headers={"Idempotency-Key": f"inv-assign2-{run}"},
        ),
        201,
    )
    s.ok(s.api("POST", f"/contractors/assignments/{a2['id']}/accept", tok_tech, json={"member_user_ids": [tech_me["id"]]}), 200)
    inv2 = s.ok(s.api("POST", "/invoices", tok_owner, json={"job_id": job2["id"], "title": "Bilge pump invoice"}), 201)
    q2 = s.ok(s.api("POST", f"/invoices/{inv2['id']}/questions", tok_owner, json={"text": "What was the call-out for?"}), 201)
    s.save(
        "error_invoices_section_not_shared",
        s.api(
            "POST",
            f"/invoices/{inv2['id']}/questions/{q2['id']}/send",
            tok_owner,
            json={"expected_version": q2["version"], "asset_ids": []},
            headers={"Idempotency-Key": f"inv-send2-{run}"},
        ),
        409,
    )
    s.save(
        "error_contractor_section_not_shared",
        s.api("GET", f"/service-jobs/{job2['id']}/invoice-questions", tok_tech),
        403,
    )
    print("comparison-unavailable and section-not-shared captured")

    # ------------------------------------------------------ feedback report → moderation case
    now = datetime.now(UTC) - timedelta(minutes=5)
    s.ok(
        s.api(
            "POST",
            f"/service-jobs/{job_id}/visits",
            tok_owner,
            json={"kind": "attended", "occurred_at": now.isoformat()},
            headers={"Idempotency-Key": f"inv-visit-{run}"},
        ),
        201,
    )
    for tok, direction, ratings, text in (
        (tok_owner, "owner_to_contractor", {"communication_clarity": 4}, "Clear explanation of the work."),
        (tok_tech, "contractor_to_owner", {"problem_description_accuracy": 2},
         "Owner's description was vague; gate code 4512# did not work."),
    ):  # fmt: skip
        draft = s.ok(
            s.api("PUT", f"/service-jobs/{job_id}/feedback/{direction}", tok, json={"ratings": ratings, "narrative": text}),
            200,
        )
        s.ok(
            s.api(
                "POST",
                f"/service-jobs/{job_id}/feedback/{direction}/submit",
                tok,
                json={"expected_version": draft["mine"]["version"]},
                headers={"Idempotency-Key": f"inv-fb-{direction}-{run}"},
            ),
            201,
        )
    overview = s.ok(s.api("GET", f"/service-jobs/{job_id}/feedback", tok_owner), 200)
    theirs = overview["theirs"]
    s.ok(
        s.api(
            "POST",
            f"/service-feedback/{theirs['id']}/reports",
            tok_owner,
            json={
                "category": "personal_or_security_information",
                "reason": "The review includes my marina gate code.",
                "restrict_content": True,
            },
        ),
        201,
    )
    s.save("error_moderation_forbidden", s.api("GET", "/moderation/cases", tok_owner), 403)
    cases = s.save("moderation_cases_active", s.api("GET", "/moderation/cases", tok_mod), 200)
    case = next(c for c in cases if c["feedback_id"] == theirs["id"])
    s.save("moderation_case_detail", s.api("GET", f"/moderation/cases/{case['id']}", tok_mod), 200)
    s.save(
        "moderation_case_assigned",
        s.api(
            "POST",
            f"/moderation/cases/{case['id']}/actions",
            tok_mod,
            json={"action": "assign", "reason": "Taking this case"},
        ),
        200,
    )
    s.save(
        "error_disposition_required",
        s.api(
            "POST",
            f"/moderation/cases/{case['id']}/actions",
            tok_mod,
            json={"action": "resolve", "reason": "Missing disposition"},
        ),
        422,
    )
    s.save(
        "moderation_case_resolved",
        s.api(
            "POST",
            f"/moderation/cases/{case['id']}/actions",
            tok_mod,
            json={
                "action": "resolve",
                "disposition": "content_removed_for_personal_information",
                "reason": "The review contained a gate code; the rest of the review stands.",
            },
        ),
        200,
    )
    s.save(
        "error_case_resolved",
        s.api(
            "POST",
            f"/moderation/cases/{case['id']}/actions",
            tok_mod,
            json={"action": "restrict", "reason": "Too late"},
        ),
        409,
    )
    s.save("moderation_cases_resolved", s.api("GET", "/moderation/cases", tok_mod, params={"status": "resolved"}), 200)
    print("moderation captured")
    print("\nWrote:")
    for w in s.written:
        print("  " + w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
