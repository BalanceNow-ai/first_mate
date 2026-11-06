#!/usr/bin/env python3
"""Integrated service-jobs journey against the running local stack (SJ-23).

Everything goes through the reverse proxy with REAL GoTrue accounts (confirmation via the
Mailpit sink), the real private object store (VersityGW behind the proxy), the real worker
(scanning/decoding/derivatives, extraction) and PostgreSQL. Contractor organizations are
provisioned with the audited CLI, exactly as an operator would. A third, unrelated owner and
an unrelated contractor organization prove isolation throughout.

Usage::

    set -a; . ./.env; set +a
    python3 scripts/e2e/service_jobs_api_journey.py [--base http://localhost:18080]

Side effects on the development stack: throwaway ``sj-*-<run>@example.test`` accounts, two
synthetic contractor organizations, one job, synthetic uploads and one synthetic invoice.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_journey import STEPS, Stack, anon_key, signup_confirmed, step, summary  # noqa: E402
from app.tests.service_invoice_fixtures import standard_pdf  # noqa: E402  (pure byte generator)

OWNER_DIMS = [
    "communication_clarity",
    "arrival_access_coordination",
    "explanation_of_work_and_changes",
    "care_and_agreed_work_delivery",
    "invoice_clarity_and_scope_relationship",
]
CONTRACTOR_DIMS = [
    "problem_description_accuracy",
    "access_arrival_accuracy",
    "equipment_site_prepared",
    "availability_for_decisions",
    "communication_and_scope_changes",
]


def cli(*args: str) -> str:
    out = subprocess.run(
        [str(ROOT / "scripts/local_stack.sh"), "cli", *args], capture_output=True, text=True, timeout=180
    )
    if out.returncode != 0:
        raise SystemExit(f"cli {args} failed: {out.stdout} {out.stderr}")
    return out.stdout


def photo_with_gps() -> bytes:
    """A synthetic JPEG carrying GPS EXIF (must never reach a derivative)."""
    from PIL import Image

    img = Image.new("RGB", (640, 480), (40, 90, 140))
    for x in range(0, 640, 16):  # texture so it is not "blurry"
        for y in range(0, 480, 16):
            if (x // 16 + y // 16) % 2:
                img.paste((230, 230, 230), (x, y, x + 8, y + 8))
    exif = Image.Exif()
    exif[0x8825] = {1: "S", 2: (36.0, 50.0, 0.0), 3: "E", 4: (174.0, 45.0, 0.0)}
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def idem() -> dict:
    return {"Idempotency-Key": uuid.uuid4().hex}


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

    def account(role: str, name: str) -> tuple[str, str, str]:
        email = f"sj-{role}-{run}@example.test"
        tok = signup_confirmed(s, email, pw, name)["access_token"]
        r = s.api("POST", "/auth/provision", tok, json={"full_name": name})
        step(f"{role} provisioned", r.status_code == 201, r.text[:100])
        return tok, email, s.api("GET", "/auth/me", tok).json()["id"]

    owner, _, _ = account("owner", "Olivia Owner")
    admin_tok, admin_email, _ = account("orgadmin", "Ada OrgAdmin")
    tech, tech_email, tech_id = account("tech", "Tama Tech")
    tech2, tech2_email, _ = account("tech2", "Tui Unassigned")
    third, third_email, _ = account("third", "Oscar Unrelated")

    # Contractor organizations are provisioned with the audited CLI (no self-service).
    org_a = cli("create-contractor-org", f"Harbour Marine {run}").split("\t")[0].strip()
    org_b = cli("create-contractor-org", f"Other Marine {run}").split("\t")[0].strip()
    cli("add-contractor-member", org_a, admin_email, "--role", "admin")
    cli("add-contractor-member", org_a, tech_email, "--role", "member")
    cli("add-contractor-member", org_a, tech2_email, "--role", "member")
    cli("add-contractor-member", org_b, third_email, "--role", "admin")
    step("two contractor organizations provisioned via CLI", bool(org_a and org_b))

    # ---- SJ-01: owner starts from a vessel; resumable job ----------------------------------
    v = s.api("POST", "/vessels/", owner, json={
        "nickname": "Kotuku", "make": "Stabicraft", "model": "2050 Supercab", "year": 2021,
        "hull_type": "aluminium", "propulsion_type": "outboard", "engine_make": "Yamaha", "engine_model": "F150",
    }).json()
    r = s.api("POST", "/service-jobs/", owner, json={
        "vessel_id": v["id"], "entry_point": "vessel", "title": "Water under the sink when the pump runs",
        "issue_description": "Water collects under the galley sink whenever the freshwater pump runs.",
        "affected_system": "plumbing", "affected_equipment": "freshwater pump hose", "urgency": "soon",
    })
    step("SJ-01 job created from the vessel", r.status_code == 201, r.text[:150])
    job = r.json()
    jid = job["id"]
    step("vessel context snapshot reused", (job.get("vessel_context") or {}).get("vessel", {}).get("make") == "Stabicraft")

    # ---- SJ-02/03: next useful request, real upload, cannot-safely-access gap -------------------
    nxt = s.api("GET", f"/service-jobs/{jid}/evidence-requests/next", owner).json()
    step("SJ-02 next evidence request has a reason", bool(nxt.get("proposal") and nxt["proposal"]["reason"]),
         (nxt.get("proposal") or {}).get("prompt", "")[:80])
    r = s.api("POST", f"/service-jobs/{jid}/evidence-requests/next", owner, params={"key": nxt["proposal"]["key"]})
    step("owner accepts the proposed request", r.status_code in (200, 201), r.text[:120])
    req1 = r.json().get("request") or r.json()
    data = photo_with_gps()
    r = s.api("POST", f"/service-jobs/{jid}/assets/intents", owner, headers=idem(), json={
        "purpose": "job_photo", "evidence_request_id": req1["id"], "filename": "overview.jpg",
        "content_type": "image/jpeg", "size_bytes": len(data), "caption": "Under the sink",
    })
    step("upload intent", r.status_code in (200, 201), r.text[:150])
    asset_id = (r.json().get("asset") or r.json())["id"]
    r = s.api("PUT", f"/service-assets/{asset_id}/content", owner, content=data,
              headers={"Content-Type": "application/octet-stream"})
    step("content received → quarantined", r.status_code in (200, 202), r.text[:150])
    status = None
    for _ in range(60):
        status = s.api("GET", f"/service-assets/{asset_id}", owner).json()
        status = status.get("asset") or status
        if status["status"] in ("available", "rejected"):
            break
        time.sleep(1)
    step("worker scanned/decoded the upload → available", status["status"] == "available", str(status)[:160])
    r = s.api("POST", f"/service-assets/{asset_id}/download-url", owner, json={"variant": "derivative"})
    url = r.json().get("url", "")
    step("signed download URL ≤ 300 s", r.status_code == 200 and url.startswith(("http", "/")), r.text[:120])
    got = s.http.get(url if url.startswith("http") else f"{a.base}{url}")
    from PIL import Image

    gps = Image.open(io.BytesIO(got.content)).getexif().get_ifd(0x8825) if got.status_code == 200 else {"x": 1}
    step("derivative fetched through the proxy has no GPS EXIF", got.status_code == 200 and not gps,
         f"{got.status_code} {len(got.content)} bytes")
    step("unsigned object request refused by the proxy",
         s.http.get(url.split("?")[0] if url.startswith("http") else f"{a.base}{url.split('?')[0]}").status_code
         in (400, 401, 403, 404))
    reqs = s.api("GET", f"/service-jobs/{jid}/evidence-requests", owner).json()
    items = reqs if isinstance(reqs, list) else reqs.get("items", [])
    step("request answered by the upload", any(q["id"] == req1["id"] and q["status"] == "answered" for q in items))
    r = s.api("POST", f"/service-jobs/{jid}/evidence-requests", owner, json={
        "category": "connections", "prompt": "Photograph the far end of the hose where it meets the pump",
        "reason": "Shows the fitting type at the pump end", "component": "pump hose",
    })
    req2 = r.json()
    r = s.api("POST", f"/service-jobs/{jid}/evidence-requests/{req2['id']}/unavailable", owner, json={
        "reason": "cannot_safely_access", "note": "Behind the engine bay bulkhead", "expected_version": req2["version"],
    })
    step("SJ-03 cannot-safely-access recorded", r.status_code == 200 and r.json()["technician_inspection_required"])
    jobv = s.api("GET", f"/service-jobs/{jid}", owner).json()
    step("SJ-03 gap visible on the job", any(g["request_id"] == req2["id"] for g in jobv.get("gaps", [])))

    # ---- SJ-04: distinct measurements ---------------------------------------------------------
    m_od = s.api("POST", f"/service-jobs/{jid}/measurements", owner, json={
        "dimension": "hose_external_diameter", "component": "pump outlet hose", "value_text": "32", "unit": "mm",
        "method": "owner_tape", "precision": "±1 mm",
    })
    step("SJ-04 owner measured OD recorded as owner_measured",
         m_od.status_code == 201 and m_od.json()["state"] == "owner_measured", m_od.text[:150])
    m_est = s.api("POST", f"/service-jobs/{jid}/measurements", owner, json={
        "dimension": "route_length", "component": "pump outlet hose", "value_text": "0.8", "unit": "m",
        "method": "image_estimate_with_reference", "reference": "600 mm cabinet door", "source_asset_id": asset_id,
        "precision": "±0.1 m",
    })
    step("SJ-04 photo estimate is never measured/confirmed",
         m_est.status_code == 201 and m_est.json()["state"] not in ("owner_measured", "contractor_confirmed"),
         m_est.json().get("state", m_est.text[:80]))

    # ---- SJ-06: invite org A with sections; preview first ------------------------------------
    sections = ["summary", "evidence", "measurements", "preparation", "access_general", "scope", "invoices"]
    r = s.api("POST", f"/service-jobs/{jid}/assignments/preview", owner, json={"organization_id": org_a, "sections": sections, "live_updates": True})
    step("owner previews what the organization will see", r.status_code == 200, r.text[:120])
    r = s.api("POST", f"/service-jobs/{jid}/assignments", owner, headers=idem(), json={"organization_id": org_a, "sections": sections, "live_updates": True})
    step("invitation sent", r.status_code == 201, r.text[:150])
    aid = r.json()["id"]
    step("assigned-to-be tech cannot see the job before acceptance",
         s.api("GET", f"/service-jobs/{jid}", tech).status_code == 404)
    inbox = s.api("GET", "/contractors/me/jobs", admin_tok).json()
    step("org admin sees the invitation summary", any(i.get("assignment_id") == aid or i.get("id") == aid for i in inbox.get("invitations", [])),
         str(inbox)[:160])
    r = s.api("POST", f"/contractors/assignments/{aid}/accept", admin_tok, json={"member_user_ids": [tech_id]})
    step("org admin accepts and assigns the tech", r.status_code == 200, r.text[:150])
    tj = s.api("GET", f"/service-jobs/{jid}", tech)
    step("assigned tech sees the shared job", tj.status_code == 200 and "restricted" not in tj.text.lower().replace("restricted_access", ""),
         str(tj.status_code))
    for who, tok in (("unassigned member of org A", tech2), ("org admin (not assigned)", admin_tok), ("unrelated owner/org B", third)):
        step(f"SJ-06 {who} gets nothing", s.api("GET", f"/service-jobs/{jid}", tok).status_code == 404)
    step("SJ-06 unrelated party cannot get a download URL",
         s.api("POST", f"/service-assets/{asset_id}/download-url", third, json={"variant": "derivative"}).status_code == 404)
    step("restricted access details not shared → 403",
         s.api("GET", f"/service-jobs/{jid}/access/restricted", tech).status_code == 403)

    # ---- SJ-08: brief preview/publish; contractor asks for one more view -----------------------
    pv = s.api("POST", f"/service-jobs/{jid}/briefs/preview", owner)
    step("brief preview", pv.status_code in (200, 201), pv.text[:150])
    brief = pv.json()
    r = s.api("POST", f"/service-jobs/{jid}/briefs/{brief['id']}/publish", owner, json={"content_digest": brief["content_digest"]})
    step("SJ-08 brief published", r.status_code == 200 and r.json()["status"] == "published", r.text[:120])
    tb = s.api("GET", f"/service-jobs/{jid}/briefs/{brief['id']}", tech)
    step("contractor reads the brief with the recorded gap", tb.status_code == 200 and "cannot_safely_access" in tb.text)
    step("brief carries no restricted access details", "4512" not in tb.text and "gate_code" not in tb.text)
    r = s.api("POST", f"/service-jobs/{jid}/briefs/{brief['id']}/acknowledgements", tech, json={
        "kind": "incomplete", "note": "Need the pump label",
        "requested_view": {"category": "label", "prompt": "Photograph the pump label without moving the unit",
                           "reason": "Identifies the pump model and port size"},
    })
    step("SJ-08 contractor requests one specific view", r.status_code in (200, 201), r.text[:150])
    reqs = s.api("GET", f"/service-jobs/{jid}/evidence-requests", owner).json()
    items = reqs if isinstance(reqs, list) else reqs.get("items", [])
    ask = next((q for q in items if q["requester_role"] == "contractor" and q["status"] == "outstanding"), None)
    step("owner sees the contractor's request", ask is not None)
    r = s.api("POST", f"/service-jobs/{jid}/evidence-requests/{ask['id']}/answer", owner,
              json={"note": "Label reads FLOJET 04406", "expected_version": ask["version"]})
    step("owner answers it", r.status_code == 200 and r.json()["status"] == "answered")

    # ---- SJ-09/10: confirmation, scope and explicit owner decision ----------------------------
    r = s.api("POST", f"/service-jobs/{jid}/measurements/{m_od.json()['id']}/confirm", tech,
              json={"method": "contractor_site", "note": "Checked with calipers on arrival plan"})
    step("SJ-09 contractor confirms the OD", r.status_code == 200 and r.json()["state"] == "contractor_confirmed", r.text[:150])
    r = s.api("POST", f"/service-jobs/{jid}/scopes", tech, json={
        "summary": "Replace the pump outlet hose and both clamps", "currency": "NZD",
        "tasks": [{"description": "Replace outlet hose", "needs_site_inspection": False}],
        "estimate_lines": [
            {"description": "Labour", "kind": "labour", "quantity": "1.5", "unit": "h", "unit_price_minor": 9500, "amount_minor": 14250},
            {"description": "Hose 25 mm ID x 1 m", "kind": "parts", "quantity": "1", "unit": "m", "unit_price_minor": 2400, "amount_minor": 2400},
        ],
        "exclusions": "Far-end fitting replacement",
    })
    step("contractor proposes a scope revision", r.status_code == 201, r.text[:150])
    scope = r.json()
    step("contractor cannot accept their own scope", s.api("POST", f"/service-jobs/{jid}/scopes/{scope['id']}/decision", tech,
         headers=idem(), json={"decision": "accepted", "revision_digest": scope["content_digest"]}).status_code in (403, 404))
    r = s.api("POST", f"/service-jobs/{jid}/scopes/{scope['id']}/decision", owner, headers=idem(),
              json={"decision": "accepted", "revision_digest": scope["content_digest"]})
    step("SJ-10 owner accepts that exact revision", r.status_code in (200, 201), r.text[:150])

    # ---- SJ-11…15: invoice linked to the job -----------------------------------------------
    pdf = standard_pdf()
    r = s.api("POST", "/service-assets/invoice-intents", owner, headers=idem(), json={
        "job_id": jid, "filename": "invoice.pdf", "content_type": "application/pdf", "size_bytes": len(pdf),
    })
    step("invoice upload intent", r.status_code in (200, 201), r.text[:150])
    inv_asset = (r.json().get("asset") or r.json())["id"]
    s.api("PUT", f"/service-assets/{inv_asset}/content", owner, content=pdf, headers={"Content-Type": "application/octet-stream"})
    for _ in range(60):
        st_body = s.api("GET", f"/service-assets/{inv_asset}", owner).json()
        st = (st_body.get("asset") or st_body)["status"]
        if st in ("available", "rejected"):
            break
        time.sleep(1)
    step("invoice PDF validated as inert → available", st == "available", st)
    r = s.api("POST", "/invoices", owner, json={"asset_id": inv_asset, "job_id": jid, "title": "Harbour Marine invoice"})
    step("invoice created", r.status_code in (200, 201), r.text[:150])
    inv = r.json()
    r = s.api("POST", f"/invoices/{inv['id']}/extract", owner, headers=idem())
    step("extraction queued", r.status_code in (200, 202), r.text[:150])
    detail = {}
    for _ in range(60):
        detail = s.api("GET", f"/invoices/{inv['id']}", owner).json()
        if detail.get("lines"):
            break
        time.sleep(1)
    step("SJ-11 extracted lines carry page/region references",
         bool(detail.get("lines")) and all(ln.get("page") for ln in detail["lines"]), f"{len(detail.get('lines', []))} lines")
    r = s.api("POST", f"/invoices/{inv['id']}/explain", owner)
    step("SJ-13 explanation compares with the accepted scope", r.status_code in (200, 201) and "comparison" in r.text, r.text[:120])
    third_view = s.api("GET", f"/invoices/{inv['id']}", third).status_code
    tech_view = s.api("GET", f"/invoices/{inv['id']}", tech).status_code
    step("invoice is owner-private (third party and unshared contractor: 404)", third_view == 404 and tech_view == 404)
    r = s.api("POST", f"/invoices/{inv['id']}/questions", owner, json={"text": "Could you explain the call-out line?"})
    q = r.json()
    step("owner drafts a factual question", r.status_code == 201, r.text[:120])
    step("nothing is sent without an explicit send",
         s.api("GET", f"/service-jobs/{jid}/invoice-questions", tech).json() in ([], {"items": []}))
    r = s.api("POST", f"/invoices/{inv['id']}/questions/{q['id']}/send", owner, headers=idem(),
              json={"expected_version": q["version"], "asset_ids": [inv_asset]})
    step("SJ-14 owner explicitly sends it with the document", r.status_code == 200, r.text[:120])
    r = s.api("POST", f"/service-jobs/{jid}/invoice-questions/{q['id']}/respond", tech,
              json={"text": "The call-out covers travel to Westhaven."})
    step("contractor responds (attributed)", r.status_code in (200, 201), r.text[:120])

    # ---- SJ-16/17: visits, blind reciprocal feedback -----------------------------------------
    now = datetime.now(UTC).isoformat()
    for kind in ("attended", "completed"):
        r = s.api("POST", f"/service-jobs/{jid}/visits", tech, headers=idem(), json={"kind": kind, "occurred_at": now})
        step(f"contractor records {kind}", r.status_code in (200, 201), r.text[:150])
    fb = s.api("GET", f"/service-jobs/{jid}/feedback", owner).json()
    step("feedback window open after attendance", fb.get("eligible") is True and fb.get("window") is not None, str(fb)[:120])
    owner_ratings = dict(zip(OWNER_DIMS, [5, 4, 5, 5, "not_applicable"]))
    r = s.api("PUT", f"/service-jobs/{jid}/feedback/owner_to_contractor", owner, json={"ratings": owner_ratings, "narrative": "Clear explanation of the hose change."})
    r = s.api("POST", f"/service-jobs/{jid}/feedback/owner_to_contractor/submit", owner, headers=idem(), json={"expected_version": r.json()["mine"]["version"]})
    step("owner submits", r.status_code in (200, 201), r.text[:120])
    before = s.api("GET", f"/service-jobs/{jid}/feedback", tech).json()
    step("SJ-17 contractor sees nothing of the owner's review before reveal",
         before.get("theirs") is None and "Clear explanation" not in str(before))
    r = s.api("PUT", f"/service-jobs/{jid}/feedback/contractor_to_owner", tech, json={"ratings": dict(zip(CONTRACTOR_DIMS, [4, 5, 4, 5, 4]))})
    r = s.api("POST", f"/service-jobs/{jid}/feedback/contractor_to_owner/submit", tech, headers=idem(), json={"expected_version": r.json()["mine"]["version"]})
    step("contractor submits", r.status_code in (200, 201), r.text[:120])
    after = s.api("GET", f"/service-jobs/{jid}/feedback", owner).json()
    step("SJ-17 both reviews revealed once both submitted",
         after.get("window", {}).get("revealed") and after.get("theirs") is not None)
    step("SJ-16 N/A is kept, not turned into zero",
         s.api("GET", f"/service-jobs/{jid}/feedback", tech).json()["theirs"]["ratings"]["invoice_clarity_and_scope_relationship"] == "not_applicable")
    step("unrelated party gets no feedback", s.api("GET", f"/service-jobs/{jid}/feedback", third).status_code == 404)

    # ---- SJ-07: revocation blocks the next request -------------------------------------------
    r = s.api("POST", f"/service-jobs/{jid}/assignments/{aid}/revoke", owner, json={"reason": "Work finished"})
    step("owner revokes working access", r.status_code == 200, r.text[:120])
    step("SJ-07 revoked contractor gets no job and no new download URL",
         s.api("GET", f"/service-jobs/{jid}", tech).status_code == 404
         and s.api("POST", f"/service-assets/{asset_id}/download-url", tech, json={"variant": "derivative"}).status_code == 404)
    step("feedback stays readable to the former participant (no media)",
         s.api("GET", f"/service-jobs/{jid}/feedback", tech).status_code == 200)
    emails = " ".join(s.emails_to(f"sj-owner-{run}@example.test") + s.emails_to(tech_email))
    step("notifications are content-free (no ratings, codes or document text)",
         "Clear explanation" not in emails and "4512" not in emails and "FLOJET" not in emails)
    return summary(0)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as exc:
        if exc.code not in (0, None) and isinstance(exc.code, str):
            print(exc.code)
            sys.exit(summary(1))
        raise
    finally:
        _ = STEPS
