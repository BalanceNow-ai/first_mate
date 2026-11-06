"""Scope revisions and the owner's explicit decisions (SJ-10, SJ-21; decision SJ-D8).

* The assigned contractor proposes a revision: tasks, estimate lines in integer minor units
  with one currency, exclusions and assumptions. The server computes the total and checks
  line arithmetic deterministically, and stores a content digest.
* Any later proposal is a new revision (``is_change``) that names the revision it
  supersedes; proposals never fork. An undecided superseded revision can no longer be
  decided; an accepted one stays accepted as history, and the change needs its own decision.
* Only the job owner decides — accepted / rejected / change_requested — on one exact
  revision, quoting its digest, with an ``Idempotency-Key``. The job row is locked first and
  a unique constraint backs it, so concurrent decisions yield exactly one; the loser gets
  409. Nothing derived from OCR, photos, documents or the model can reach this code.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.models.service_jobs import ScopeDecision, ScopeRevision, ServiceJob
from app.services import audit
from app.services.service_jobs import runs
from app.services.service_jobs.access import JobActor, Visibility
from app.services.service_jobs.observations import notify_counterparty

LINE_KINDS = ("labour", "parts", "travel", "call_out", "consumables", "other")
DECISIONS = ("accepted", "rejected", "change_requested")
MAX_TOTAL_MINOR = 2**31 - 1


@dataclass
class ScopeInput:
    summary: str
    tasks: list[dict] = field(default_factory=list)
    estimate_lines: list[dict] = field(default_factory=list)
    currency: str | None = None
    exclusions: str | None = None
    assumptions: str | None = None
    supersedes_id: uuid.UUID | None = None


def _lines(lines: list[dict], currency: str | None) -> tuple[list[dict], int | None, str | None]:
    if not lines:
        return [], None, currency.upper() if currency else None
    if not currency or not re.fullmatch(r"[A-Za-z]{3}", currency):
        raise AppError(422, "currency_required", "Estimate lines need a three-letter currency code (e.g. NZD)")
    out: list[dict] = []
    total = 0
    for i, line in enumerate(lines):
        amount = line.get("amount_minor")
        unit_price = line.get("unit_price_minor")
        qty_text = line.get("quantity")
        quantity = None
        if qty_text is not None:
            try:
                quantity = Decimal(str(qty_text))
            except InvalidOperation:
                raise AppError(422, "invalid_quantity", f"Line {i + 1}: quantity is not a number") from None
            if not quantity.is_finite() or quantity <= 0:
                raise AppError(422, "invalid_quantity", f"Line {i + 1}: quantity must be positive")
        if quantity is not None and unit_price is not None:
            product = quantity * Decimal(unit_price)
            if amount is None and product == product.to_integral_value():
                amount = int(product)
            elif amount is None or Decimal(amount) != product:
                raise AppError(
                    422,
                    "line_arithmetic",
                    f"Line {i + 1}: quantity × unit price does not equal the amount (amounts are in minor units)",
                )
        if amount is None:
            raise AppError(422, "amount_required", f"Line {i + 1}: an amount (minor units) is required")
        total += amount
        out.append(
            {
                "description": line["description"],
                "kind": line.get("kind") or "other",
                "quantity": format(quantity.normalize(), "f") if quantity is not None else None,
                "unit": line.get("unit"),
                "unit_price_minor": unit_price,
                "amount_minor": amount,
            }
        )
    if total > MAX_TOTAL_MINOR:
        raise AppError(422, "estimate_too_large", "The estimate total is too large")
    return out, total, currency.upper()


def _digest(rev: ScopeRevision) -> str:
    return runs.digest(
        {
            "job": str(rev.job_id),
            "revision_number": rev.revision_number,
            "is_change": rev.is_change,
            "supersedes": str(rev.supersedes_id) if rev.supersedes_id else None,
            "summary": rev.summary,
            "tasks": rev.tasks,
            "estimate_lines": rev.estimate_lines,
            "estimate_total_minor": rev.estimate_total_minor,
            "currency": rev.currency,
            "exclusions": rev.exclusions,
            "assumptions": rev.assumptions,
        }
    )


async def _latest(db: AsyncSession, job_id: uuid.UUID) -> ScopeRevision | None:
    return (
        await db.execute(
            select(ScopeRevision)
            .where(ScopeRevision.job_id == job_id)
            .order_by(ScopeRevision.revision_number.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()


async def propose(db: AsyncSession, actor: JobActor, data: ScopeInput) -> ScopeRevision:
    """Contractor proposal (job row locked by the caller)."""
    actor.require_contractor()
    latest = await _latest(db, actor.job.id)
    # Each organization proposes on its own chain: a previous organization's revisions
    # (and prices) are neither shown to nor superseded "by name" by the next one.
    own = latest
    if latest is not None and latest.organization_id != actor.organization_id:
        own = (
            await db.execute(
                select(ScopeRevision)
                .where(ScopeRevision.job_id == actor.job.id, ScopeRevision.organization_id == actor.organization_id)
                .order_by(ScopeRevision.revision_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if own is not None and data.supersedes_id != own.id:
        raise AppError(
            409,
            "scope_conflict",
            "A newer scope revision exists; propose a change that supersedes the current revision",
            extra={"current_revision_id": str(own.id)},
        )
    if own is None and data.supersedes_id is not None:
        raise not_found("Scope revision")
    lines, total, currency = _lines(data.estimate_lines, data.currency)
    rev = ScopeRevision(
        job_id=actor.job.id,
        revision_number=(latest.revision_number + 1) if latest else 1,
        is_change=own is not None,
        supersedes_id=own.id if own else None,
        proposed_by=actor.user_id,
        organization_id=actor.organization_id,
        summary=data.summary,
        tasks=[{k: v for k, v in t.items() if v is not None} for t in data.tasks],
        estimate_lines=lines,
        estimate_total_minor=total,
        currency=currency,
        exclusions=data.exclusions,
        assumptions=data.assumptions,
        status="proposed",
        content_digest="",
    )
    rev.content_digest = _digest(rev)
    for previous in {r.id: r for r in (latest, own) if r is not None}.values():
        if previous.status in ("proposed", "change_requested", "rejected", "draft"):
            previous.status = "superseded"
    db.add(rev)
    await db.flush()
    await notify_counterparty(db, actor, "scope_proposed", f"scope:{rev.id}")
    return rev


async def list_revisions(db: AsyncSession, job_id: uuid.UUID) -> list[ScopeRevision]:
    q = select(ScopeRevision).where(ScopeRevision.job_id == job_id).order_by(ScopeRevision.revision_number)
    return list((await db.execute(q)).scalars())


async def get_revision(db: AsyncSession, job_id: uuid.UUID, scope_id: uuid.UUID) -> ScopeRevision:
    rev = (
        await db.execute(select(ScopeRevision).where(ScopeRevision.id == scope_id, ScopeRevision.job_id == job_id))
    ).scalar_one_or_none()
    if rev is None:
        raise not_found("Scope revision")
    return rev


async def decisions_for(db: AsyncSession, job_id: uuid.UUID) -> dict[uuid.UUID, ScopeDecision]:
    rows = (await db.execute(select(ScopeDecision).where(ScopeDecision.job_id == job_id))).scalars()
    return {d.scope_revision_id: d for d in rows}


def decision_view(d: ScopeDecision | None) -> dict | None:
    if d is None:
        return None
    return {
        "id": d.id,
        "scope_revision_id": d.scope_revision_id,
        "decision": d.decision,
        "revision_digest": d.revision_digest,
        "decided_by": d.decided_by,
        "note": d.note,
        "decided_at": d.decided_at,
    }


def view(rev: ScopeRevision, decision: ScopeDecision | None, latest_number: int | None) -> dict:
    return {
        "id": rev.id,
        "job_id": rev.job_id,
        "revision_number": rev.revision_number,
        "is_change": rev.is_change,
        "supersedes_id": rev.supersedes_id,
        "proposed_by": rev.proposed_by,
        "organization_id": rev.organization_id,
        "summary": rev.summary,
        "tasks": rev.tasks,
        "estimate_lines": rev.estimate_lines,
        "estimate_total_minor": rev.estimate_total_minor,
        "currency": rev.currency,
        "exclusions": rev.exclusions,
        "assumptions": rev.assumptions,
        "status": rev.status,
        "content_digest": rev.content_digest,
        "is_current": latest_number is not None and rev.revision_number == latest_number,
        "decision": decision_view(decision),
        "created_at": rev.created_at,
    }


async def views(db: AsyncSession, job_id: uuid.UUID, vis: Visibility | None = None) -> list[dict]:
    """Every revision with its decision; with ``vis``, only the reader organization's own
    (a previous organization's prices and decisions are not shown to the next one)."""
    revs = await list_revisions(db, job_id)
    latest = revs[-1].revision_number if revs else None
    if vis is not None:
        revs = [r for r in revs if vis.organization_record(r.organization_id)]
    decisions = await decisions_for(db, job_id)
    return [view(r, decisions.get(r.id), latest) for r in revs]


async def decide(
    db: AsyncSession,
    actor: JobActor,
    scope_id: uuid.UUID,
    *,
    decision: str,
    revision_digest: str,
    note: str | None,
    idempotency_key: str,
) -> tuple[ScopeDecision, bool]:
    """The owner's decision on one exact revision (job row locked by the caller)."""
    actor.require_owner()
    if decision not in DECISIONS:
        raise AppError(422, "invalid_decision", "Decide accepted, rejected or change_requested")
    prior = (
        await db.execute(
            select(ScopeDecision).where(
                ScopeDecision.decided_by == actor.user_id, ScopeDecision.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if prior is not None:
        if prior.scope_revision_id != scope_id or prior.decision != decision:
            raise AppError(409, "idempotency_key_reused", "This Idempotency-Key was used for a different decision")
        return prior, False
    rev = (
        await db.execute(
            select(ScopeRevision)
            .where(ScopeRevision.id == scope_id, ScopeRevision.job_id == actor.job.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if rev is None:
        raise not_found("Scope revision")
    latest = (
        await db.execute(select(func.max(ScopeRevision.revision_number)).where(ScopeRevision.job_id == actor.job.id))
    ).scalar_one()
    existing = (
        await db.execute(select(ScopeDecision).where(ScopeDecision.scope_revision_id == rev.id))
    ).scalar_one_or_none()
    if existing is not None:
        raise AppError(409, "scope_already_decided", "This scope revision already has a decision")
    if rev.status == "superseded" or rev.revision_number != latest:
        raise AppError(409, "scope_superseded", "This scope revision has been superseded; review the current one")
    if rev.status != "proposed":
        raise AppError(409, "scope_not_open", "This scope revision is not awaiting a decision")
    if revision_digest != rev.content_digest:
        raise AppError(
            409, "digest_mismatch", "The scope you reviewed is not this revision's content; reload and review again"
        )
    row = ScopeDecision(
        job_id=actor.job.id,
        scope_revision_id=rev.id,
        revision_digest=rev.content_digest,
        decision=decision,
        decided_by=actor.user_id,
        note=note,
        idempotency_key=idempotency_key,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise AppError(409, "scope_already_decided", "This scope revision already has a decision") from None
    rev.status = decision
    await audit.record(
        db,
        actor.user_id,
        f"service_scope.{decision}",
        "service_scope_revision",
        rev.id,
        {
            "job_id": str(actor.job.id),
            "revision_number": rev.revision_number,
            "revision_digest": rev.content_digest,
            "is_change": rev.is_change,
            "estimate_total_minor": rev.estimate_total_minor,
            "currency": rev.currency,
        },
    )
    await notify_counterparty(db, actor, "scope_decided", f"scope_decision:{row.id}")
    return row, True


async def current_view(db: AsyncSession, job: ServiceJob, vis: Visibility | None = None) -> dict:
    items = await views(db, job.id, vis)
    accepted = [i for i in items if i["decision"] and i["decision"]["decision"] == "accepted"]
    return {
        "current": items[-1] if items else None,
        "latest_accepted": accepted[-1] if accepted else None,
        "history": items,
    }
