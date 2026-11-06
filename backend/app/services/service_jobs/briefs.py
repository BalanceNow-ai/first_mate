"""Contractor-ready preparation briefs: preview, publish, acknowledge, export (SJ-08).

A brief is an immutable snapshot (``PreparationBrief.content``) of exactly what the live
assignment's sections expose — never ``access_restricted`` — built for one assignment:

1. symptoms and history with attribution, vessel/equipment identity (summary);
2. evidence with observations and unresolved/unavailable requests (gaps) (evidence);
3. general access/logistics (access_general);
4. measurements with provenance badges (measurements);
5. preparation items with statuses, assumptions, items needing site inspection (preparation);
6. current scope and change history, exclusions (scope).

The owner previews (a ``preview`` row the owner sees verbatim, with its recipients), then
publishes that exact preview. Publication supersedes the previous brief and points the
assignment at it. A brief whose supporting material changed afterwards is *outdated*.
Contractors read only published briefs made for their assignment, filtered to the
sections they hold now. "Ready for contractor review" means enough to review, not that
the diagnosis or parts are correct.
"""

from __future__ import annotations

import html
import uuid
from datetime import datetime

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    BriefAcknowledgement,
    ContractorOrganization,
    EvidenceAsset,
    EvidenceRequest,
    JobAccessDetails,
    JobAssignment,
    JobAssignmentMember,
    Observation,
    PreparationBrief,
    PreparationItem,
    ScopeDecision,
    ScopeRevision,
    ServiceJob,
)
from app.models.user import User
from app.models.vessel import Vessel
from app.services import audit
from app.services.service_jobs import access, runs
from app.services.service_jobs import measurements as msvc
from app.services.service_jobs import observations as osvc
from app.services.service_jobs import preparation as psvc
from app.services.service_jobs import scope as ssvc
from app.services.service_jobs.access import JobActor
from app.services.service_jobs.notify import notify

BRIEF_FORMAT = 1
CONTENT_SECTIONS = ("summary", "evidence", "access_general", "measurements", "preparation", "scope")
ACK_KINDS = ("reviewed", "incomplete", "limitations_acknowledged", "confirmed")
LIMITATIONS = [
    "Ready for contractor review means there is enough information to review — not that the diagnosis, "
    "dimensions or parts are correct.",
    "Photos show only what is visible. They do not prove a diagnosis, material grade, dimension, hidden condition "
    "or suitability, and they do not show that the boat is safe.",
    "Suggested items are provisional. A preparation item is not a purchase, quote, work instruction or approval.",
    "Text read from photos or documents is reported as it appears; it is not a measurement.",
]


# ---------------------------------------------------------------------- snapshot
async def _recipient(db: AsyncSession, assignment: JobAssignment) -> dict:
    org = await db.get(ContractorOrganization, assignment.organization_id)
    members = (
        await db.execute(
            select(JobAssignmentMember, User.full_name)
            .join(User, User.id == JobAssignmentMember.user_id)
            .where(JobAssignmentMember.assignment_id == assignment.id, JobAssignmentMember.removed_at.is_(None))
            .order_by(JobAssignmentMember.created_at)
        )
    ).all()
    return {
        "assignment_id": str(assignment.id),
        "assignment_status": assignment.status,
        "organization_id": str(assignment.organization_id),
        "organization_name": org.name if org else None,
        "members": [{"user_id": str(m.user_id), "name": name} for m, name in members],
    }


def _request_json(r: EvidenceRequest) -> dict:
    return {
        "id": r.id,
        "category": r.category,
        "component": r.component,
        "prompt": r.prompt,
        "reason": r.reason,
        "requester_role": r.requester_role,
        "priority": r.priority,
        "status": r.status,
        "unavailable_reason": r.unavailable_reason,
        "technician_inspection_required": r.technician_inspection_required,
        "answer_note": r.answer_note,
    }


async def build_content(db: AsyncSession, job: ServiceJob, assignment: JobAssignment) -> dict:
    sections = [s for s in CONTENT_SECTIONS if s in (assignment.sections or [])]
    content: dict = {
        "brief_format": BRIEF_FORMAT,
        "job": {"id": job.id, "title": job.title, "status": job.status, "evidence_revision": job.evidence_revision},
        "recipient": await _recipient(db, assignment),
        "sections": sections,
        "limitations": LIMITATIONS,
    }
    requests = list(
        (
            await db.execute(
                select(EvidenceRequest).where(EvidenceRequest.job_id == job.id).order_by(EvidenceRequest.created_at)
            )
        ).scalars()
    )
    if "summary" in sections:
        vessel = await db.get(Vessel, job.vessel_id) if job.vessel_id else None
        content["summary"] = {
            "attribution": "owner_declared",
            "issue_description": job.issue_description,
            "occurs_when": job.occurs_when,
            "already_tried": job.already_tried,
            "urgency": job.urgency,
            "affected_system": job.affected_system,
            "affected_equipment": job.affected_equipment,
            "vessel": (
                {
                    "make": vessel.make,
                    "model": vessel.model,
                    "year": vessel.year,
                    "engine_make": vessel.engine_make,
                    "engine_model": vessel.engine_model,
                    "engine_year": vessel.engine_year,
                    "attribution": "vessel_record",
                }
                if vessel
                else None
            ),
            "vessel_context": job.vessel_context or {},
            "vessel_context_attribution": "owner_declared",
        }
    if "evidence" in sections:
        assets = list(
            (
                await db.execute(
                    select(EvidenceAsset)
                    .where(EvidenceAsset.job_id == job.id, EvidenceAsset.deleted_at.is_(None))
                    .order_by(EvidenceAsset.created_at, EvidenceAsset.id)
                )
            ).scalars()
        )
        obs = list(
            (
                await db.execute(
                    select(Observation)
                    .where(Observation.job_id == job.id, Observation.state.notin_(osvc.INACTIVE_STATES))
                    .order_by(Observation.created_at, Observation.id)
                )
            ).scalars()
        )
        content["evidence"] = {
            "assets": [
                {
                    "id": a.id,
                    "purpose": a.purpose,
                    "caption": a.caption,
                    "detected_type": a.detected_type,
                    "status": a.status,
                    "captured_at": a.captured_at,
                    "evidence_request_id": a.evidence_request_id,
                    "duplicate_of_id": a.duplicate_of_id,
                }
                for a in assets
            ],
            "observations": await osvc.views(db, job, obs),
            "requests": [_request_json(r) for r in requests],
            "gaps": [_request_json(r) for r in requests if r.status in ("outstanding", "unavailable")],
        }
    if "access_general" in sections:
        details = await db.get(JobAccessDetails, job.id)
        content["access_general"] = dict(details.general) if details else {}
    if "measurements" in sections:
        rows = await msvc.list_for_job(db, job.id)
        content["measurements"] = {
            "current": [v for v in msvc.views(rows, job) if v["is_current"]],
            "superseded_count": sum(1 for m in rows if m.state in msvc.INACTIVE),
        }
    if "preparation" in sections:
        items = await psvc.list_items(db, job, include_inactive=False)
        item_views = await psvc.views(db, job, items)
        site = [
            {"item_id": v["id"], "item": v["name"], "requirement": r}
            for v in item_views
            for r in v["open_requirements"]
            if "inspection" in r.lower() or "not visible" in r.lower() or "not confirmed" in r.lower()
        ]
        site += [
            {"evidence_request_id": r.id, "item": r.component, "requirement": r.prompt}
            for r in requests
            if r.technician_inspection_required or r.status == "unavailable"
        ]
        content["preparation"] = {
            "items": item_views,
            "assumptions": [
                {"item_id": v["id"], "item": v["name"], "basis": v["quantity_basis"]}
                for v in item_views
                if v["quantity_basis"]
            ],
            "needs_site_inspection": site,
        }
    if "scope" in sections:
        content["scope"] = await ssvc.current_view(db, job)
        current = content["scope"]["current"]
        content["scope"]["exclusions"] = current["exclusions"] if current else None
    return jsonable_encoder(content)


def filtered(content: dict, actor: JobActor) -> dict:
    """What this actor may read of a snapshot now (a section later withdrawn is hidden)."""
    if actor.is_owner:
        return content
    out = {k: v for k, v in content.items() if k not in CONTENT_SECTIONS}
    allowed = [s for s in content.get("sections", []) if actor.can(s)]
    out["sections"] = allowed
    for s in allowed:
        if s in content:
            out[s] = content[s]
    return out


# ---------------------------------------------------------------------- state
async def _changed_since(db: AsyncSession, job: ServiceJob, when: datetime) -> list[str]:
    reasons = []
    prep = (
        await db.execute(select(func.max(PreparationItem.updated_at)).where(PreparationItem.job_id == job.id))
    ).scalar_one()
    if prep is not None and prep > when:
        reasons.append("preparation_changed")
    scope_at = (
        await db.execute(select(func.max(ScopeRevision.created_at)).where(ScopeRevision.job_id == job.id))
    ).scalar_one()
    decided_at = (
        await db.execute(select(func.max(ScopeDecision.decided_at)).where(ScopeDecision.job_id == job.id))
    ).scalar_one()
    if any(t is not None and t > when for t in (scope_at, decided_at)):
        reasons.append("scope_changed")
    return reasons


async def outdated_reasons(db: AsyncSession, job: ServiceJob, brief: PreparationBrief) -> list[str]:
    reasons = ["evidence_changed"] if job.evidence_revision != brief.job_revision else []
    return reasons + await _changed_since(db, job, brief.created_at)


async def _acks(db: AsyncSession, brief_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(BriefAcknowledgement)
            .where(BriefAcknowledgement.brief_id == brief_id)
            .order_by(BriefAcknowledgement.created_at)
        )
    ).scalars()
    return [
        {
            "id": a.id,
            "kind": a.kind,
            "note": a.note,
            "user_id": a.user_id,
            "organization_id": a.organization_id,
            "created_at": a.created_at,
        }
        for a in rows
    ]


async def view(db: AsyncSession, actor: JobActor, brief: PreparationBrief, *, with_content: bool = True) -> dict:
    assignment = await access.live_assignment(db, actor.job.id)
    reasons = await outdated_reasons(db, actor.job, brief)
    return {
        "id": brief.id,
        "job_id": brief.job_id,
        "revision_number": brief.revision_number,
        "status": brief.status,
        "sections": filtered(brief.content, actor).get("sections", []),
        "recipient": brief.content.get("recipient"),
        "content": filtered(brief.content, actor) if with_content else None,
        "job_revision": brief.job_revision,
        "current_job_revision": actor.job.evidence_revision,
        "content_digest": brief.content_digest,
        "created_by": brief.created_by,
        "created_at": brief.created_at,
        "published_at": brief.published_at,
        "is_current": bool(assignment and assignment.shared_brief_id == brief.id and brief.status == "published"),
        "outdated": bool(reasons),
        "outdated_reasons": reasons,
        "acknowledgements": await _acks(db, brief.id),
    }


def _visible_to(actor: JobActor, brief: PreparationBrief) -> bool:
    if actor.is_owner:
        return True
    if brief.published_at is None or brief.status not in ("published", "superseded"):
        return False
    recipient = (brief.content or {}).get("recipient") or {}
    return actor.assignment is not None and recipient.get("assignment_id") == str(actor.assignment.id)


async def list_briefs(db: AsyncSession, actor: JobActor) -> list[PreparationBrief]:
    rows = (
        await db.execute(
            select(PreparationBrief)
            .where(PreparationBrief.job_id == actor.job.id)
            .order_by(PreparationBrief.revision_number.desc())
        )
    ).scalars()
    return [b for b in rows if _visible_to(actor, b)]


async def get_brief(db: AsyncSession, actor: JobActor, brief_id: uuid.UUID, *, lock: bool = False) -> PreparationBrief:
    q = select(PreparationBrief).where(PreparationBrief.id == brief_id, PreparationBrief.job_id == actor.job.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    brief = (await db.execute(q)).scalar_one_or_none()
    if brief is None or not _visible_to(actor, brief):
        raise not_found("Brief")
    return brief


# ---------------------------------------------------------------------- owner actions
async def preview(db: AsyncSession, actor: JobActor) -> PreparationBrief:
    """Snapshot what the live assignment would receive now (job row locked by the caller)."""
    actor.require_owner()
    assignment = await access.live_assignment(db, actor.job.id, lock=True)
    if assignment is None:
        raise AppError(409, "no_live_assignment", "Invite a contractor before preparing a brief")
    content = await build_content(db, actor.job, assignment)
    last = (
        await db.execute(
            select(func.max(PreparationBrief.revision_number)).where(PreparationBrief.job_id == actor.job.id)
        )
    ).scalar_one()
    for old in (
        await db.execute(
            select(PreparationBrief)
            .where(PreparationBrief.job_id == actor.job.id, PreparationBrief.status == "preview")
            .with_for_update()
        )
    ).scalars():
        old.status = "superseded"
    brief = PreparationBrief(
        job_id=actor.job.id,
        revision_number=(last or 0) + 1,
        status="preview",
        sections=content["sections"],
        content=content,
        job_revision=actor.job.evidence_revision,
        content_digest=runs.digest(content),
        created_by=actor.user_id,
    )
    db.add(brief)
    await db.flush()
    return brief


async def publish(
    db: AsyncSession, actor: JobActor, brief_id: uuid.UUID, expected_digest: str | None
) -> PreparationBrief:
    """Publish exactly the preview the owner saw (job row locked by the caller)."""
    actor.require_owner()
    assignment = await access.live_assignment(db, actor.job.id, lock=True)
    brief = await get_brief(db, actor, brief_id, lock=True)
    if brief.status != "preview":
        raise AppError(409, "not_a_preview", "Only the current preview can be published")
    if expected_digest is not None and expected_digest != brief.content_digest:
        raise AppError(409, "digest_mismatch", "This is not the preview you reviewed; preview again")
    if assignment is None or (brief.content.get("recipient") or {}).get("assignment_id") != str(assignment.id):
        raise AppError(409, "recipient_changed", "The contractor assignment changed; preview again")
    if sorted(brief.sections) != sorted(s for s in CONTENT_SECTIONS if s in (assignment.sections or [])):
        raise AppError(409, "sections_changed", "The shared sections changed; preview again")
    if await outdated_reasons(db, actor.job, brief):
        raise AppError(409, "preview_outdated", "The job changed since this preview; preview again")
    for old in (
        await db.execute(
            select(PreparationBrief)
            .where(PreparationBrief.job_id == actor.job.id, PreparationBrief.status == "published")
            .with_for_update()
        )
    ).scalars():
        old.status = "superseded"
    brief.status = "published"
    brief.published_at = utcnow()
    assignment.shared_brief_id = brief.id
    assignment.version += 1
    await audit.record(
        db,
        actor.user_id,
        "service_brief.published",
        "service_brief",
        brief.id,
        {
            "job_id": str(actor.job.id),
            "assignment_id": str(assignment.id),
            "revision_number": brief.revision_number,
            "content_digest": brief.content_digest,
            "sections": brief.sections,
        },
    )
    if assignment.status == "accepted":
        await osvc.notify_counterparty(db, actor, "brief_published", f"brief:{brief.id}")
    return brief


async def acknowledge(
    db: AsyncSession,
    actor: JobActor,
    brief_id: uuid.UUID,
    *,
    kind: str,
    note: str | None,
    requested_view: dict | None,
) -> tuple[BriefAcknowledgement, EvidenceRequest | None]:
    actor.require_contractor()
    if kind not in ACK_KINDS:
        raise AppError(422, "invalid_acknowledgement", "Unknown acknowledgement")
    brief = await get_brief(db, actor, brief_id, lock=True)
    if brief.status != "published" or actor.assignment.shared_brief_id != brief.id:
        raise AppError(409, "brief_superseded", "A newer brief has been shared; review the current one")
    request = None
    if kind == "incomplete":
        if not requested_view:
            raise AppError(422, "requested_view_required", "Say which view or measurement is missing")
        request = await osvc.create_evidence_request(db, actor, **requested_view)
    if kind == "confirmed" and await outdated_reasons(db, actor.job, brief):
        raise AppError(409, "brief_outdated", "The job changed after this brief was shared; ask for a new brief")
    ack = BriefAcknowledgement(
        brief_id=brief.id,
        organization_id=actor.organization_id,
        user_id=actor.user_id,
        kind=kind,
        note=note,
    )
    db.add(ack)
    await db.flush()
    await audit.record(
        db,
        actor.user_id,
        f"service_brief.{kind}",
        "service_brief",
        brief.id,
        {
            "job_id": str(actor.job.id),
            "revision_number": brief.revision_number,
            "content_digest": brief.content_digest,
            "evidence_request_id": str(request.id) if request else None,
        },
    )
    await notify(db, actor.job.owner_id, "brief_acknowledged", job_id=actor.job.id, key=f"brief_ack:{ack.id}")
    return ack, request


# ---------------------------------------------------------------------- export
def _render(value, depth: int = 0) -> str:
    if depth > 8:
        return "…"
    if isinstance(value, dict):
        if not value:
            return "<em>none</em>"
        rows = "".join(
            f"<dt>{html.escape(str(k).replace('_', ' '))}</dt><dd>{_render(v, depth + 1)}</dd>"
            for k, v in value.items()
        )
        return f"<dl>{rows}</dl>"
    if isinstance(value, list):
        if not value:
            return "<em>none</em>"
        return "<ul>" + "".join(f"<li>{_render(v, depth + 1)}</li>" for v in value) + "</ul>"
    if value is None:
        return "<em>not recorded</em>"
    return html.escape(str(value), quote=True)


SECTION_TITLES = {
    "summary": "1. Symptoms, history and vessel",
    "evidence": "2. Evidence, observations and gaps",
    "access_general": "3. Access and logistics",
    "measurements": "4. Measurements",
    "preparation": "5. Parts, consumables and tools (provisional unless confirmed)",
    "scope": "6. Scope and change history",
}


def export_html(view_data: dict) -> str:
    content = view_data["content"] or {}
    job = content.get("job", {})
    parts = [
        "<!doctype html><html lang='en-NZ'><head><meta charset='utf-8'>",
        "<meta name='robots' content='noindex'>",
        f"<title>Service brief r{int(view_data['revision_number'])}</title>",
        "<style>body{font-family:sans-serif;max-width:60em;margin:2em auto;padding:0 1em}"
        "dt{font-weight:bold}dd{margin:0 0 .5em 1em}</style></head><body>",
        f"<h1>Service brief — {html.escape(str(job.get('title', '')))}</h1>",
        f"<p>Revision {int(view_data['revision_number'])} · status {html.escape(view_data['status'])}"
        f" · digest <code>{html.escape(view_data['content_digest'])}</code>"
        + (" · <strong>OUTDATED: the job has changed since this brief</strong>" if view_data["outdated"] else "")
        + "</p>",
        "<h2>Limitations</h2>",
        _render(content.get("limitations", [])),
    ]
    for section in CONTENT_SECTIONS:
        if section in content:
            parts.append(f"<h2>{html.escape(SECTION_TITLES[section])}</h2>")
            parts.append(_render(content[section]))
    parts.append("</body></html>")
    return "".join(parts)
