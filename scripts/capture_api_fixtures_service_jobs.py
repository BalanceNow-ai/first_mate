#!/usr/bin/env python3
"""Capture REAL API payloads for the Flutter service-jobs client (owner + contractor
journeys) as contract-test fixtures.

Drives the running local stack (``scripts/local_stack.sh up``) through the reverse proxy
with REAL GoTrue accounts (confirmation-required signup, confirmation link from the
Mailpit sink, password sign-in) — no minted tokens. Contractor organizations and their
verified memberships are provisioned with the audited CLI
(``local_stack.sh cli create-contractor-org`` / ``add-contractor-member``). Photos are
small synthetic PNG/JPEG images uploaded through the real upload-intent → PUT content →
scan/decode processing path. Every response body is saved verbatim into
``frontend/test/fixtures/api/service_jobs/<name>.json``; nothing is hand-written.

Side effects on the shared development stack: throwaway accounts ``sj-*-<run>@example.test``,
two synthetic contractor organizations ``Fixture Marine <run>`` / ``Fixture Other <run>``,
their vessels/jobs/uploads (private object store) and feedback.

Usage::

    python3 scripts/capture_api_fixtures_service_jobs.py \
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
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "test" / "fixtures" / "api" / "service_jobs"


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


def synthetic_image(fmt: str, seed: int, size=(480, 360)) -> bytes:
    """A small synthetic picture (gradient + blocks + 'label' text) — no real boat."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, (30 + seed * 20 % 200, 90, 140))
    d = ImageDraw.Draw(img)
    for i in range(0, size[0], 24):
        d.line([(i, 0), (size[0] - i, size[1])], fill=(200, 200 - i % 120, 80), width=3)
    d.rectangle([60, 60, 260, 140], fill=(240, 240, 230), outline=(10, 10, 10), width=4)
    d.text((76, 88), f"SYNTH {seed} 25MM ID", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=88) if fmt == "JPEG" else img.save(buf, format=fmt)
    return buf.getvalue()


def synthetic_pdf(lines: list[str], *, active: bool = False) -> bytes:
    """A minimal one-page text PDF (a synthetic service document). ``active`` adds an
    /OpenAction JavaScript action, which the server must refuse (active content)."""
    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    stream = "".join(f"BT /F1 11 Tf 1 0 0 1 50 {780 - 18 * i} Tm ({esc(t)}) Tj ET\n" for i, t in enumerate(lines))
    data = stream.encode("latin-1")
    catalog = b"<< /Type /Catalog /Pages 2 0 R" + (b" /OpenAction 6 0 R" if active else b"") + b" >>"
    objs = [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
        b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 1 0 R >> >> "
        b"/Contents 3 0 R >>",
        catalog,
    ]
    if active:
        objs.append(b"<< /S /JavaScript /JS (app.alert\\(1\\)) >>")
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
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


class Stack:
    def __init__(self, base: str, mailpit: str, anon: str, out: Path) -> None:
        self.base, self.mailpit, self.anon, self.out = base.rstrip("/"), mailpit.rstrip("/"), anon, out
        self.http = httpx.Client(timeout=60)
        self.written: list[str] = []

    def auth(self, path: str, body: dict, **params) -> httpx.Response:
        return self.http.post(
            f"{self.base}/auth/v1/{path}", json=body, params=params,
            headers={"apikey": self.anon, "Authorization": f"Bearer {self.anon}"},
        )

    def api(self, method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
        headers = kw.pop("headers", {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = path if path.startswith("http") else f"{self.base}/api/v1{path}"
        for _ in range(30):
            try:
                resp = self.http.request(method, url, headers=headers, **kw)
            except httpx.TransportError:
                time.sleep(2)
                continue
            if resp.status_code == 502 and "json" not in resp.headers.get("content-type", ""):
                time.sleep(2)
                continue
            return resp
        raise SystemExit(f"{method} {path}: API unreachable")

    def save(self, name: str, resp: httpx.Response, expect: int | tuple[int, ...]):
        expected = expect if isinstance(expect, tuple) else (expect,)
        if resp.status_code not in expected:
            raise SystemExit(
                f"{resp.request.method} {resp.request.url} -> {resp.status_code}, expected {expect}: {resp.text[:1200]}"
            )
        body = resp.json() if resp.content else None
        if name:
            self.out.mkdir(parents=True, exist_ok=True)
            (self.out / f"{name}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")
            self.written.append(f"{name}.json  ({resp.request.method} {resp.request.url.path} {resp.status_code})")
        return body

    def ok(self, resp: httpx.Response, expect: int | tuple[int, ...]):
        return self.save("", resp, expect)

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

    def account(self, email: str, password: str, name: str) -> tuple[str, str]:
        r = self.auth("signup", {"email": email, "password": password, "data": {"full_name": name}})
        if r.status_code != 200:
            raise SystemExit(f"signup failed: {r.status_code} {r.text}")
        self.http.get(self.confirmation_link(email), follow_redirects=False)
        r = self.auth("token", {"email": email, "password": password}, grant_type="password")
        if r.status_code != 200:
            raise SystemExit(f"sign-in failed: {r.status_code} {r.text}")
        token = r.json()["access_token"]
        me = self.ok(self.api("POST", "/auth/provision", token, json={"full_name": name}), 201)
        return token, me["id"] if "id" in me else me["user"]["id"]

    def upload(self, tok: str, job_id: str, data: bytes, name: str, *, request_id: str | None = None,
               caption: str | None = None, capture: str = "") -> dict:
        """Intent → PUT bytes → poll until processed. Captures each stage when ``capture`` is set."""
        content_type = {".png": "image/png", ".pdf": "application/pdf"}.get(Path(name).suffix, "image/jpeg")
        body = {"purpose": "job_document" if name.endswith(".pdf") else "job_photo", "filename": name,
                "content_type": content_type, "size_bytes": len(data)}
        if request_id:
            body["evidence_request_id"] = request_id
        if caption:
            body["caption"] = caption
        intent = self.save(f"{capture}_intent" if capture else "", self.api(
            "POST", f"/service-jobs/{job_id}/assets/intents", tok, json=body,
            headers={"Idempotency-Key": f"sj-up-{uuid.uuid4().hex[:12]}"}), 201)
        url = intent["upload"]["url"]
        put = self.save(f"{capture}_received" if capture else "", self.api(
            "PUT", f"{self.base}{url}", tok, content=data, headers={"Content-Type": "application/octet-stream"}), 202)
        asset = put
        deadline = time.time() + 90
        while asset["status"] in ("upload_pending", "quarantined", "processing") and time.time() < deadline:
            time.sleep(1)
            asset = self.ok(self.api("GET", f"/service-assets/{intent['asset']['id']}", tok), 200)
        if capture:
            self.save(f"{capture}_processed", self.api("GET", f"/service-assets/{intent['asset']['id']}", tok), 200)
        return asset


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

    def cli(*args: str) -> str:
        return subprocess.run([str(stack_root / "scripts" / "local_stack.sh"), "cli", *args],
                              check=True, cwd=stack_root, capture_output=True, text=True).stdout

    def idem(tag: str) -> dict:
        return {"Idempotency-Key": f"sj-{run}-{tag}-{uuid.uuid4().hex[:6]}"}

    # ------------------------------------------------------------------ people + orgs
    tok_o, owner_id = s.account(f"sj-owner-{run}@example.test", pw, "Fixture Owner")
    tok_ca, ca_id = s.account(f"sj-cadmin-{run}@example.test", pw, "Fixture Contractor Admin")
    tok_cm, cm_id = s.account(f"sj-cmember-{run}@example.test", pw, "Fixture Technician")
    tok_x, _ = s.account(f"sj-other-{run}@example.test", pw, "Fixture Outsider")
    org_name = f"Fixture Marine {run}"
    org_id = cli("create-contractor-org", org_name, "--trading-name", "Fixture Marine Services").strip().split("\t")[0]
    other_org = cli("create-contractor-org", f"Fixture Other {run}").strip().split("\t")[0]
    cli("add-contractor-member", org_id, f"sj-cadmin-{run}@example.test", "--role", "admin")
    cli("add-contractor-member", org_id, f"sj-cmember-{run}@example.test", "--role", "member")
    cli("add-contractor-member", other_org, f"sj-cadmin-{run}@example.test", "--role", "admin")
    print(f"accounts and organizations ready ({run})")

    # ------------------------------------------------------------------ owner: job
    vessel = s.ok(s.api("POST", "/vessels/", tok_o, json={
        "nickname": "Kahawai", "make": "Stabicraft", "model": "2050 Supercab", "year": 2021,
        "engine_make": "Yamaha", "engine_model": "F150", "engine_year": 2021, "propulsion_type": "outboard"}), 201)
    job = s.save("job_created", s.api("POST", "/service-jobs/", tok_o, json={
        "vessel_id": vessel["id"], "entry_point": "vessel", "title": "Water under the sink when the pump runs",
        "issue_description": "There is water under the galley sink whenever the freshwater pump runs.",
        "affected_system": "Freshwater", "affected_equipment": "Freshwater pump", "occurs_when": "When the pump runs",
        "already_tried": "Tightened the visible hose clamp", "urgency": "soon"}), 201)
    jid = job["id"]
    s.save("error_validation_job", s.api("POST", "/service-jobs/", tok_o, json={"vessel_id": vessel["id"], "title": ""}), 422)
    job = s.save("job_updated", s.api("PATCH", f"/service-jobs/{jid}", tok_o, json={
        "expected_version": job["version"], "urgency": "routine"}), 200)
    s.save("error_version_conflict", s.api("PATCH", f"/service-jobs/{jid}", tok_o, json={
        "expected_version": 1, "title": "Stale edit"}), 409)
    job = s.save("job_context_corrected", s.api("PUT", f"/service-jobs/{jid}/vessel-context", tok_o, json={
        "expected_version": job["version"], "engine": {"make": "Yamaha", "model": "F150", "year": 2020},
        "note": "Engine is the 2020 model"}), 200)
    job = s.ok(s.api("POST", f"/service-jobs/{jid}/transition", tok_o, json={
        "expected_version": job["version"], "to": "evidence_collection"}), 200)

    # ------------------------------------------------------------------ guided capture
    s.save("analysis_status_empty", s.api("GET", f"/service-jobs/{jid}/analysis", tok_o), 200)
    s.save("next_proposal", s.api("GET", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)
    nxt = s.save("next_accepted", s.api("POST", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)
    r1 = nxt["request"]
    s.upload(tok_o, jid, synthetic_image("PNG", 1), "overview.png", request_id=r1["id"],
             caption="Locker under the galley sink", capture="asset_png")
    s.upload(tok_o, jid, synthetic_image("JPEG", 2), "label.jpg", caption="Pump label", capture="asset_jpeg")
    # A spoofed "image" (text bytes) is rejected by content checks.
    s.upload(tok_o, jid, b"this is not an image, just text pretending\n" * 20, "fake.png", capture="asset_rejected")
    # Documents (purpose job_document): a plain PDF is accepted (metadata-stripped copy); one
    # with an /OpenAction JavaScript action is refused as active content.
    s.upload(tok_o, jid, synthetic_pdf(["Freshwater pump service record", "Outlet hose 25 mm ID"]),
             "pump-service.pdf", caption="Pump service record", capture="asset_pdf")
    s.upload(tok_o, jid, synthetic_pdf(["Pump manual"], active=True), "manual.pdf", capture="asset_pdf_rejected")
    s.save("assets_list", s.api("GET", f"/service-jobs/{jid}/assets", tok_o), 200)
    assets = s.ok(s.api("GET", f"/service-jobs/{jid}/assets", tok_o), 200)["items"]
    available = [x for x in assets if x["status"] == "available"]
    s.save("download_url", s.api("POST", f"/service-assets/{available[0]['id']}/download-url", tok_o,
                                 json={"variant": "derivative"}), 200)
    s.save("job_after_upload", s.api("GET", f"/service-jobs/{jid}", tok_o), 200)

    nxt = s.save("next_after_upload", s.api("GET", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)
    r2 = s.ok(s.api("POST", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)["request"]
    s.save("request_unavailable", s.api("POST", f"/service-jobs/{jid}/evidence-requests/{r2['id']}/unavailable", tok_o,
                                        json={"reason": "cannot_safely_access",
                                              "note": "The far end is behind the hot water cylinder",
                                              "expected_version": r2["version"]}), 200)
    r3 = s.ok(s.api("POST", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)["request"]
    s.save("request_answered", s.api("POST", f"/service-jobs/{jid}/evidence-requests/{r3['id']}/answer", tok_o,
                                     json={"note": "The hose is marked 25 mm ID", "expected_version": r3["version"]}), 200)
    own = s.save("request_created", s.api("POST", f"/service-jobs/{jid}/evidence-requests", tok_o, json={
        "category": "document", "prompt": "Previous service invoice for the pump",
        "reason": "Shows what was replaced last time", "priority": "low"}), 201)
    s.save("request_waived", s.api("POST", f"/service-jobs/{jid}/evidence-requests/{own['id']}/waive", tok_o,
                                   json={"note": "Not available"}), 200)
    s.save("requests_list", s.api("GET", f"/service-jobs/{jid}/evidence-requests", tok_o), 200)

    run_resp = s.api("POST", f"/service-jobs/{jid}/analysis", tok_o, json={}, headers=idem("an"))
    if run_resp.status_code == 503:
        s.save("error_analysis_unavailable", run_resp, 503)
    else:
        an = s.save("analysis_queued", run_resp, (202, 200))
        deadline = time.time() + 60
        while an["status"] in ("pending", "running") and time.time() < deadline:
            time.sleep(1)
            an = s.ok(s.api("GET", f"/service-jobs/{jid}/analysis/{an['id']}", tok_o), 200)
        s.save("analysis_run", s.api("GET", f"/service-jobs/{jid}/analysis/{an['id']}", tok_o), 200)
    s.save("analysis_status", s.api("GET", f"/service-jobs/{jid}/analysis", tok_o), 200)
    s.save("observation_note", s.api("POST", f"/service-jobs/{jid}/observations", tok_o, json={
        "text": "Drip forms at the lower hose connection", "asset_id": available[0]["id"],
        "region": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.2}}), 201)
    s.save("observations", s.api("GET", f"/service-jobs/{jid}/observations", tok_o), 200)

    # ------------------------------------------------------------------ measurements + preparation
    m_id = s.save("measurement_marking", s.api("POST", f"/service-jobs/{jid}/measurements", tok_o, json={
        "dimension": "hose_internal_diameter", "component": "Pump outlet hose", "value_text": "25", "unit": "mm",
        "method": "marking_read", "source_asset_id": available[0]["id"],
        "notes": "Printed on the hose"}), 201)
    m_od = s.save("measurement_owner", s.api("POST", f"/service-jobs/{jid}/measurements", tok_o, json={
        "dimension": "hose_external_diameter", "component": "Pump outlet hose", "value_text": "32", "unit": "mm",
        "precision": "±1 mm", "method": "owner_caliper", "tool": "Vernier caliper"}), 201)
    s.save("measurement_revised", s.api("POST", f"/service-jobs/{jid}/measurements/{m_od['id']}/revise", tok_o, json={
        "dimension": "hose_external_diameter", "component": "Pump outlet hose", "value_text": "32.5", "unit": "mm",
        "precision": "±0.5 mm", "method": "owner_caliper", "tool": "Vernier caliper"}), 201)
    s.ok(s.api("POST", f"/service-jobs/{jid}/measurements", tok_o, json={
        "dimension": "clamp_range", "component": "Outlet clamp", "value_text": "20-32", "unit": "mm",
        "method": "owner_tape"}), 201)
    s.save("measurements", s.api("GET", f"/service-jobs/{jid}/measurements", tok_o), 200)
    s.save("preparation_suggested", s.api("POST", f"/service-jobs/{jid}/preparation-items/suggest", tok_o), 200)
    s.save("preparation_item_created", s.api("POST", f"/service-jobs/{jid}/preparation-items", tok_o, json={
        "category": "consumable", "name": "Thread seal tape", "purpose": "Re-seal the pump outlet fitting",
        "open_requirements": ["Fitting thread not confirmed"], "source_note": "Owner suggestion"}), 201)
    s.save("preparation_items", s.api("GET", f"/service-jobs/{jid}/preparation-items", tok_o), 200)

    # ------------------------------------------------------------------ access details
    gen = s.save("access_general", s.api("PUT", f"/service-jobs/{jid}/access/general", tok_o, json={
        "expected_version": 1, "general": {"marina": "Westhaven Marina", "access_hours": "8am-5pm weekdays",
                                           "owner_attendance": "Owner on board", "known_hazards": "Low deckhead"}}), 200)
    s.save("access_restricted", s.api("PUT", f"/service-jobs/{jid}/access/restricted", tok_o, json={
        "expected_version": gen["version"], "restricted": {"gate_code": "4321", "berth": "Pier F 12",
                                              "contact_name": "Fixture Owner", "contact_phone": "021 000 000"}}), 200)
    s.save("access_general_get", s.api("GET", f"/service-jobs/{jid}/access/general", tok_o), 200)

    # ------------------------------------------------------------------ sharing
    s.save("directory", s.api("GET", "/contractors/directory", tok_o, params={"q": run}), 200)
    sections = ["summary", "evidence", "measurements", "preparation", "access_general", "access_restricted", "scope"]
    s.save("sharing_preview", s.api("POST", f"/service-jobs/{jid}/assignments/preview", tok_o, json={
        "organization_id": org_id, "sections": sections, "live_updates": True}), 200)
    s.save("error_idempotency_key_required", s.api("POST", f"/service-jobs/{jid}/assignments", tok_o, json={
        "organization_id": org_id, "sections": sections}), 400)
    asg = s.save("assignment_invited", s.api("POST", f"/service-jobs/{jid}/assignments", tok_o, json={
        "organization_id": org_id, "sections": sections, "live_updates": True}, headers=idem("inv")), 201)
    s.save("assignments", s.api("GET", f"/service-jobs/{jid}/assignments", tok_o), 200)
    s.save("jobs_list", s.api("GET", "/service-jobs/", tok_o), 200)

    # ------------------------------------------------------------------ contractor admin
    s.save("contractor_me", s.api("GET", "/contractors/me", tok_ca), 200)
    s.save("contractor_me_empty", s.api("GET", "/contractors/me", tok_x), 200)
    s.save("contractor_inbox_invited", s.api("GET", "/contractors/me/jobs", tok_ca), 200)
    s.save("contractor_inbox_empty", s.api("GET", "/contractors/me/jobs", tok_x), 200)
    s.save("org_invitations", s.api("GET", f"/contractors/organizations/{org_id}/invitations", tok_ca), 200)
    s.save("org_members", s.api("GET", f"/contractors/organizations/{org_id}/members", tok_ca), 200)
    s.save("error_job_not_found", s.api("GET", f"/service-jobs/{jid}", tok_ca), 404)
    s.save("invitation_accepted", s.api("POST", f"/contractors/assignments/{asg['id']}/accept", tok_ca,
                                        json={"member_user_ids": [cm_id]}), 200)
    s.save("contractor_inbox_assigned", s.api("GET", "/contractors/me/jobs", tok_cm), 200)
    s.save("error_outsider_job", s.api("GET", f"/service-jobs/{jid}", tok_x), 404)

    asg = s.ok(s.api("GET", f"/service-jobs/{jid}/assignments", tok_o), 200)[0]
    s.save("error_section_forbidden", s.api("GET", f"/service-jobs/{jid}/access/restricted", tok_cm), 403)
    s.save("assignment_member_restricted", s.api(
        "PUT", f"/service-jobs/{jid}/assignments/{asg['id']}/members/{cm_id}", tok_o,
        json={"restricted_access": True, "expected_version": asg["version"]}), 200)
    s.save("access_restricted_contractor", s.api("GET", f"/service-jobs/{jid}/access/restricted", tok_cm), 200)

    job = s.ok(s.api("GET", f"/service-jobs/{jid}", tok_o), 200)
    s.save("job_transitioned", s.api("POST", f"/service-jobs/{jid}/transition", tok_o, json={
        "expected_version": job["version"], "to": "contractor_review"}), 200)

    # ------------------------------------------------------------------ brief
    brief = s.save("brief_preview", s.api("POST", f"/service-jobs/{jid}/briefs/preview", tok_o), 201)
    brief = s.save("brief_published", s.api("POST", f"/service-jobs/{jid}/briefs/{brief['id']}/publish", tok_o,
                                            json={"content_digest": brief["content_digest"]}), 200)
    s.save("briefs", s.api("GET", f"/service-jobs/{jid}/briefs", tok_o), 200)
    s.save("job_contractor_view", s.api("GET", f"/service-jobs/{jid}", tok_cm), 200)
    s.save("briefs_contractor", s.api("GET", f"/service-jobs/{jid}/briefs", tok_cm), 200)
    s.save("brief_contractor", s.api("GET", f"/service-jobs/{jid}/briefs/{brief['id']}", tok_cm), 200)
    s.save("brief_ack_requested_view", s.api("POST", f"/service-jobs/{jid}/briefs/{brief['id']}/acknowledgements", tok_cm,
                                             json={"kind": "incomplete", "note": "Need the pump label",
                                                   "requested_view": {"category": "label",
                                                                      "prompt": "Photograph the pump label without moving the pump",
                                                                      "reason": "Confirms the pump model and outlet size",
                                                                      "component": "Freshwater pump"}}), 201)
    s.save("assets_contractor", s.api("GET", f"/service-jobs/{jid}/assets", tok_cm), 200)
    s.save("next_contractor_request", s.api("GET", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)
    creq = s.ok(s.api("GET", f"/service-jobs/{jid}/evidence-requests/next", tok_o), 200)["request"]
    s.upload(tok_o, jid, synthetic_image("PNG", 3), "pump-label.png", request_id=creq["id"], caption="Pump label")
    s.save("requests_contractor", s.api("GET", f"/service-jobs/{jid}/evidence-requests", tok_cm), 200)
    s.save("contractor_request_created", s.api("POST", f"/service-jobs/{jid}/evidence-requests", tok_cm, json={
        "category": "connections", "prompt": "Show both ends of the outlet hose",
        "reason": "Check the fitting type at each end", "component": "Outlet hose"}), 201)

    # ------------------------------------------------------------------ contractor confirms
    s.save("measurement_confirmed", s.api("POST", f"/service-jobs/{jid}/measurements/{m_id['id']}/confirm", tok_cm,
                                          json={"method": "marking_read", "note": "Marking legible on the photo"}), 200)
    s.save("measurements_contractor", s.api("GET", f"/service-jobs/{jid}/measurements", tok_cm), 200)
    items = s.ok(s.api("GET", f"/service-jobs/{jid}/preparation-items", tok_cm, params={"include_inactive": "false"}), 200)
    if len(items) < 3:
        raise SystemExit(f"expected at least three preparation items, got {len(items)}")
    first, second, third = items[0], items[1], items[2]
    q = {"quantity": "2", "unit": "each", "quantity_basis": "One at each hose end"} if first["category"] != "tool" else {}
    s.save("preparation_item_confirmed", s.api("POST", f"/service-jobs/{jid}/preparation-items/{first['id']}/confirm",
                                               tok_cm, json={"expected_version": first["version"], **q,
                                                             "note": "Requirement confirmed"}), 200)
    s.save("preparation_item_evidence", s.api(
        "POST", f"/service-jobs/{jid}/preparation-items/{second['id']}/request-evidence", tok_cm,
        json={"expected_version": second["version"], "category": "markings",
              "prompt": "Photograph any printing on the clamp band", "reason": "Shows the clamp range"}), 201)
    s.save("preparation_item_rejected", s.api("POST", f"/service-jobs/{jid}/preparation-items/{third['id']}/reject",
                                              tok_cm, json={"expected_version": third["version"],
                                                            "note": "Not needed for this repair"}), 200)
    s.save("preparation_items_contractor", s.api("GET", f"/service-jobs/{jid}/preparation-items", tok_cm), 200)

    # ------------------------------------------------------------------ scope
    scope = s.save("scope_proposed", s.api("POST", f"/service-jobs/{jid}/scopes", tok_cm, json={
        "summary": "Replace the pump outlet hose and both clamps",
        "tasks": [{"description": "Replace outlet hose (approx. 0.8 m)"},
                  {"description": "Inspect far-end fitting", "needs_site_inspection": True}],
        "estimate_lines": [
            {"description": "Labour", "kind": "labour", "quantity": "1.5", "unit": "hour", "unit_price_minor": 9500},
            {"description": "Hose and clamps", "kind": "parts", "amount_minor": 4250}],
        "currency": "NZD", "exclusions": "Pump replacement", "assumptions": "Far-end fitting is serviceable"}), 201)
    s.save("error_owner_cannot_propose", s.api("POST", f"/service-jobs/{jid}/scopes", tok_o, json={
        "summary": "Owner proposal"}), (403, 409))
    s.save("scope_decision_accepted", s.api("POST", f"/service-jobs/{jid}/scopes/{scope['id']}/decision", tok_o, json={
        "decision": "accepted", "revision_digest": scope["content_digest"], "note": "Go ahead"},
        headers={"Idempotency-Key": f"sj-{run}-scope1"}), 201)
    s.save("scope_decision_repeat", s.api("POST", f"/service-jobs/{jid}/scopes/{scope['id']}/decision", tok_o, json={
        "decision": "accepted", "revision_digest": scope["content_digest"], "note": "Go ahead"},
        headers={"Idempotency-Key": f"sj-{run}-scope1"}), 200)
    change = s.save("scope_change_proposed", s.api("POST", f"/service-jobs/{jid}/scopes", tok_cm, json={
        "summary": "Also replace the outlet fitting", "supersedes_id": scope["id"],
        "tasks": [{"description": "Replace outlet hose"}, {"description": "Replace corroded outlet fitting"}],
        "estimate_lines": [
            {"description": "Labour", "kind": "labour", "quantity": "2", "unit": "hour", "unit_price_minor": 9500},
            {"description": "Hose, clamps and fitting", "kind": "parts", "amount_minor": 6800}],
        "currency": "NZD"}), 201)
    s.save("error_digest_mismatch", s.api("POST", f"/service-jobs/{jid}/scopes/{change['id']}/decision", tok_o, json={
        "decision": "accepted", "revision_digest": scope["content_digest"]}, headers=idem("bad")), (409, 422))
    s.save("scope_decision_change_requested", s.api(
        "POST", f"/service-jobs/{jid}/scopes/{change['id']}/decision", tok_o,
        json={"decision": "change_requested", "revision_digest": change["content_digest"],
              "note": "Please quote the fitting separately"}, headers=idem("chg")), 201)
    s.save("scopes", s.api("GET", f"/service-jobs/{jid}/scopes", tok_o), 200)

    # ------------------------------------------------------------------ visits + feedback
    s.save("feedback_not_eligible", s.api("GET", f"/service-jobs/{jid}/feedback", tok_o), 200)
    now = datetime.now(timezone.utc)
    s.save("visit_attended", s.api("POST", f"/service-jobs/{jid}/visits", tok_cm, json={
        "kind": "attended", "occurred_at": (now - timedelta(hours=3)).isoformat(), "note": "On board at 9am"},
        headers=idem("att")), 201)
    done = s.save("visit_completed", s.api("POST", f"/service-jobs/{jid}/visits", tok_cm, json={
        "kind": "completed", "occurred_at": (now - timedelta(hours=1)).isoformat(), "note": "Hose replaced"},
        headers=idem("cmp")), 201)
    s.save("visits", s.api("GET", f"/service-jobs/{jid}/visits", tok_o), 200)
    s.save("feedback_owner_open", s.api("GET", f"/service-jobs/{jid}/feedback", tok_o), 200)
    s.save("feedback_owner_draft", s.api("PUT", f"/service-jobs/{jid}/feedback/owner_to_contractor", tok_o, json={
        "ratings": {"communication_clarity": 5, "arrival_access_coordination": 4,
                    "explanation_of_work_and_changes": 4, "care_and_agreed_work_delivery": 5,
                    "invoice_clarity_and_scope_relationship": "not_applicable"},
        "narrative": "Arrived on time and explained the change to the fitting clearly."}), 200)
    s.save("feedback_owner_submitted", s.api("POST", f"/service-jobs/{jid}/feedback/owner_to_contractor/submit", tok_o,
                                             json={}, headers=idem("fbo")), 201)
    s.save("feedback_contractor_blind", s.api("GET", f"/service-jobs/{jid}/feedback", tok_cm), 200)
    s.ok(s.api("PUT", f"/service-jobs/{jid}/feedback/contractor_to_owner", tok_cm, json={
        "ratings": {"problem_description_accuracy": 5, "access_arrival_accuracy": 4, "equipment_site_prepared": 4,
                    "availability_for_decisions": 5, "communication_and_scope_changes": 5},
        "narrative": "Photos and measurements made preparation easy."}), 200)
    s.save("feedback_contractor_revealed", s.api(
        "POST", f"/service-jobs/{jid}/feedback/contractor_to_owner/submit", tok_cm, json={}, headers=idem("fbc")), 201)
    rev = s.save("feedback_owner_revealed", s.api("GET", f"/service-jobs/{jid}/feedback", tok_o), 200)
    s.save("feedback_response", s.api("POST", f"/service-feedback/{rev['theirs']['id']}/responses", tok_o, json={
        "kind": "response", "text": "Thanks — the boat was ready as agreed."}), 201)
    s.save("feedback_report", s.api("POST", f"/service-feedback/{rev['mine']['id']}/reports", tok_cm, json={
        "category": "factual_dispute", "reason": "The visit time is recorded incorrectly"}), 201)
    s.save("feedback_owner_final", s.api("GET", f"/service-jobs/{jid}/feedback", tok_o), 200)
    s.save("visit_contested", s.api("POST", f"/service-jobs/{jid}/visits/{done['event']['id']}/contest", tok_o, json={
        "reason": "The hose was replaced but the fitting still drips"}, headers=idem("con")), 201)
    s.save("job_completed_owner", s.api("GET", f"/service-jobs/{jid}", tok_o), 200)

    # ------------------------------------------------------------------ second job: decline/revoke/cancel
    j2 = s.ok(s.api("POST", "/service-jobs/", tok_o, json={
        "vessel_id": vessel["id"], "entry_point": "first_mate", "title": "Bilge pump cycling"}), 201)
    a2 = s.ok(s.api("POST", f"/service-jobs/{j2['id']}/assignments", tok_o, json={
        "organization_id": other_org, "sections": ["summary"]}, headers=idem("inv2")), 201)
    s.save("invitation_declined", s.api("POST", f"/contractors/assignments/{a2['id']}/decline", tok_ca), 200)
    a3 = s.ok(s.api("POST", f"/service-jobs/{j2['id']}/assignments", tok_o, json={
        "organization_id": org_id, "sections": ["summary", "evidence"]}, headers=idem("inv3")), 201)
    s.save("assignment_revoked", s.api("POST", f"/service-jobs/{j2['id']}/assignments/{a3['id']}/revoke", tok_o,
                                       json={"reason": "Chose another contractor"}), 200)
    j2 = s.ok(s.api("GET", f"/service-jobs/{j2['id']}", tok_o), 200)
    s.save("job_cancelled", s.api("POST", f"/service-jobs/{j2['id']}/transition", tok_o, json={
        "expected_version": j2["version"], "to": "cancelled"}), 200)
    s.save("feedback_cancelled_ineligible", s.api("GET", f"/service-jobs/{j2['id']}/feedback", tok_o), 200)
    j3 = s.ok(s.api("POST", "/service-jobs/", tok_o, json={"vessel_id": vessel["id"], "title": "Draft to delete"}), 201)
    s.ok(s.api("DELETE", f"/service-jobs/{j3['id']}", tok_o), 204)
    s.save("jobs_list_final", s.api("GET", "/service-jobs/", tok_o), 200)

    # ------------------------------------------------------------------ live updates off (the default)
    j4 = s.ok(s.api("POST", "/service-jobs/", tok_o, json={
        "vessel_id": vessel["id"], "entry_point": "vessel", "title": "Navigation lights flicker",
        "issue_description": "The port navigation light flickers when the engine starts.",
        "affected_system": "Electrical", "affected_equipment": "Navigation lights", "urgency": "soon"}), 201)
    p4 = f"/service-jobs/{j4['id']}"
    j4 = s.ok(s.api("POST", f"{p4}/transition", tok_o, json={"expected_version": j4["version"],
                                                              "to": "evidence_collection"}), 200)
    m4 = s.ok(s.api("POST", f"{p4}/measurements", tok_o, json={
        "dimension": "route_length", "component": "Port light cable run", "value_text": "3.2", "unit": "m",
        "method": "owner_tape"}), 201)
    s.ok(s.api("POST", f"{p4}/preparation-items", tok_o, json={
        "category": "part", "name": "Heat-shrink butt connectors", "purpose": "Re-terminate the light cable",
        "open_requirements": ["Cable gauge not confirmed"]}), 201)
    snap_sections = ["summary", "evidence", "measurements", "preparation"]
    s.save("sharing_preview_snapshot", s.api("POST", f"{p4}/assignments/preview", tok_o, json={
        "organization_id": org_id, "sections": snap_sections}), 200)
    a4 = s.save("assignment_invited_snapshot", s.api("POST", f"{p4}/assignments", tok_o, json={
        "organization_id": org_id, "sections": snap_sections}, headers=idem("inv4")), 201)
    s.ok(s.api("POST", f"/contractors/assignments/{a4['id']}/accept", tok_ca, json={"member_user_ids": [cm_id]}), 200)
    s.save("job_contractor_no_brief", s.api("GET", p4, tok_cm), 200)
    s.save("measurements_contractor_no_brief", s.api("GET", f"{p4}/measurements", tok_cm), 200)
    b4 = s.ok(s.api("POST", f"{p4}/briefs/preview", tok_o), 201)
    b4 = s.ok(s.api("POST", f"{p4}/briefs/{b4['id']}/publish", tok_o, json={"content_digest": b4["content_digest"]}), 200)
    s.save("job_contractor_brief_snapshot", s.api("GET", p4, tok_cm), 200)
    export = s.api("GET", f"{p4}/briefs/{b4['id']}/export", tok_cm)
    if export.status_code != 200 or "text/html" not in export.headers.get("content-type", ""):
        raise SystemExit(f"brief export: {export.status_code} {export.headers.get('content-type')}")
    later = s.ok(s.api("POST", f"{p4}/measurements", tok_o, json={
        "dimension": "other", "component": "Light fitting screws", "value_text": "M4", "method": "owner_other"}), 201)
    s.save("error_live_updates_not_shared", s.api("POST", f"{p4}/measurements/{later['id']}/confirm", tok_cm,
                                                  json={"method": "contractor_site"}), 403)
    # The first organisation confirms and records; the job is then reassigned (live updates on).
    s.ok(s.api("POST", f"{p4}/measurements/{m4['id']}/confirm", tok_cm,
               json={"method": "contractor_site", "note": "Measured on site"}), 200)
    s.ok(s.api("POST", f"{p4}/measurements", tok_cm, json={
        "dimension": "other", "component": "Cable gauge", "value_text": "1.5 mm²", "method": "contractor_site",
        "notes": "Tinned marine cable"}), 201)
    item4 = s.ok(s.api("GET", f"{p4}/preparation-items", tok_cm), 200)[0]
    s.ok(s.api("POST", f"{p4}/preparation-items/{item4['id']}/confirm", tok_cm,
               json={"expected_version": item4["version"], "quantity": "4", "unit": "each",
                     "quantity_basis": "Two at each end of the cable run", "note": "Requirement confirmed"}), 200)
    a4 = s.ok(s.api("GET", f"{p4}/assignments", tok_o), 200)[0]
    s.ok(s.api("POST", f"{p4}/assignments/{a4['id']}/reassign", tok_o, json={
        "organization_id": other_org, "sections": snap_sections, "live_updates": True}, headers=idem("re4")), 201)
    a5 = next(a for a in s.ok(s.api("GET", f"{p4}/assignments", tok_o), 200) if a["status"] == "invited")
    s.ok(s.api("POST", f"/contractors/assignments/{a5['id']}/accept", tok_ca, json={"member_user_ids": [ca_id]}), 200)
    s.save("job_contractor_live", s.api("GET", p4, tok_ca), 200)
    s.save("measurements_other_org", s.api("GET", f"{p4}/measurements", tok_ca), 200)
    s.save("preparation_items_other_org", s.api("GET", f"{p4}/preparation-items", tok_ca), 200)

    print("\nWrote:")
    for w in s.written:
        print("  " + w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
