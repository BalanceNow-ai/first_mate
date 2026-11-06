"""Understand my invoice: revisions, extraction runs, corrections, explanations, questions.

Invoices are owner-private (SJ-15): every owner operation resolves the invoice by
``(id, owner_id)`` and answers 404 otherwise. The only other party who ever sees invoice
material is the job's assigned contractor, and only an explicitly *sent* question plus
the documents the owner selected for it (resolved through ``access.job_for`` on the
linked job). A standalone invoice (no job) can never be shared.

Truth model (SJ-11): ``InvoiceRevision.extracted`` is written once by an extraction run
and never changed; the source document is never overwritten. ``fields`` holds the
reviewed values with their source (``extracted`` | ``owner_corrected`` |
``owner_confirmed`` | ``owner_entered``), who and when, and the earlier values. Lines keep
their original extracted values in ``InvoiceLine.extracted`` (immutable) while the
columns hold the reviewed values; every correction is also written to the audit log. A
contractor's corrected document is a *new* revision that supersedes the old one.

Concurrency: the invoice row is locked first (``owned_invoice(lock=True)``), then its
revision/lines/questions; ``expected_version`` mismatches are 409. Extraction runs follow
``runs.py`` (create → claim → provider outside any transaction → publish with re-check);
publication locks run → invoice, and request paths never lock run rows.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, not_found
from app.database import utcnow
from app.models.service_jobs import (
    AnalysisRun,
    EvidenceAsset,
    Invoice,
    InvoiceExplanation,
    InvoiceLine,
    InvoiceQuestion,
    InvoiceQuestionResponse,
    InvoiceRevision,
    JobAssignmentMember,
    PreparationItem,
    ScopeDecision,
    ScopeRevision,
    ServiceJob,
)
from app.services import audit
from app.services.service_jobs import access, invoice_explain, invoice_math, notify, runs, storage
from app.services.service_jobs import invoice_extraction as extraction

logger = logging.getLogger(__name__)

FIELD_NAMES = extraction.FIELD_NAMES
AMOUNT_FIELDS = extraction.AMOUNT_FIELDS
TEXT_FIELDS = tuple(f for f in FIELD_NAMES if f not in AMOUNT_FIELDS and f != "currency")
LINE_VALUE_COLUMNS = (
    "kind",
    "description",
    "part_number",
    "quantity",
    "unit",
    "unit_price",
    "line_total",
    "tax_printed",
    "currency",
)
LINE_DECIMALS = ("quantity", "unit_price", "line_total", "tax_printed")
OWNER_SOURCES = ("owner_corrected", "owner_confirmed", "owner_entered")
NEEDS_CONFIRMATION_CERTAINTY = ("low", "unknown")
MAX_SHARED_ASSETS = 10
SHAREABLE_ASSET_STATUSES = ("available",)
CORRECTION_ASSET_PURPOSES = ("job_document", "invoice")
MAX_PLACES = 4  # Numeric(14, 4)


def _now() -> str:
    return utcnow().isoformat()


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _within_precision(d: Decimal) -> bool:
    return -d.as_tuple().exponent <= MAX_PLACES if d.as_tuple().exponent < 0 else True


# ============================================================================ lookups
async def owned_invoice(db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, *, lock: bool = False) -> Invoice:
    q = select(Invoice).where(Invoice.id == invoice_id, Invoice.owner_id == user_id, Invoice.deleted_at.is_(None))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    invoice = (await db.execute(q)).scalar_one_or_none()
    if invoice is None:
        raise not_found("Invoice")
    return invoice


async def current_revision(db: AsyncSession, invoice: Invoice, *, lock: bool = False) -> InvoiceRevision:
    q = select(InvoiceRevision).where(
        InvoiceRevision.id == invoice.current_revision_id, InvoiceRevision.invoice_id == invoice.id
    )
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    rev = (await db.execute(q)).scalar_one_or_none()
    if rev is None:  # pragma: no cover - every invoice is created with a revision
        raise not_found("Invoice revision")
    return rev


async def lines_of(db: AsyncSession, revision_id: uuid.UUID, *, lock: bool = False) -> list[InvoiceLine]:
    q = (
        select(InvoiceLine)
        .where(InvoiceLine.invoice_revision_id == revision_id)
        .order_by(InvoiceLine.line_number)
        .execution_options(populate_existing=True)
    )
    if lock:
        q = q.with_for_update()
    return list((await db.execute(q)).scalars())


async def supersede_explanations(db: AsyncSession, revision_id: uuid.UUID) -> None:
    await db.execute(
        update(InvoiceExplanation)
        .where(InvoiceExplanation.invoice_revision_id == revision_id, InvoiceExplanation.status == "current")
        .values(status="superseded")
        .execution_options(synchronize_session=False)
    )


def _touch(invoice: Invoice, rev: InvoiceRevision | None = None) -> None:
    invoice.version += 1
    invoice.updated_at = utcnow()
    if rev is not None:
        rev.version += 1


# ============================================================================ create
async def create_invoice(
    db: AsyncSession, user_id: uuid.UUID, *, asset_id: uuid.UUID | None, job_id: uuid.UUID | None, title: str
) -> tuple[Invoice, bool]:
    """Invoice + revision 1 from the owner's own available ``invoice`` asset (or a manual
    entry without a document). Re-submitting the same asset returns the existing invoice."""
    asset = None
    if asset_id is not None:
        asset = (
            await db.execute(
                select(EvidenceAsset)
                .where(
                    EvidenceAsset.id == asset_id,
                    EvidenceAsset.owner_id == user_id,
                    EvidenceAsset.uploaded_by == user_id,
                    EvidenceAsset.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if asset is None:
            raise not_found("Invoice document")
        if asset.purpose != "invoice":
            raise AppError(422, "asset_not_invoice", "That file was not uploaded as an invoice")
        if asset.status != "available":
            raise AppError(
                409, "asset_not_available", "The invoice file is still being checked. Try again when it is ready."
            )
        if asset.job_id is not None:
            if job_id is None:
                job_id = asset.job_id
            elif job_id != asset.job_id:
                raise AppError(422, "asset_job_mismatch", "That file was uploaded for a different service job")
        existing = (
            await db.execute(
                select(Invoice)
                .join(InvoiceRevision, InvoiceRevision.invoice_id == Invoice.id)
                .where(
                    InvoiceRevision.source_asset_id == asset.id,
                    Invoice.owner_id == user_id,
                    Invoice.deleted_at.is_(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    if job_id is not None:
        await access.job_for(db, user_id, job_id, owner_only=True)
    invoice = Invoice(owner_id=user_id, job_id=job_id, title=title, status="uploaded")
    db.add(invoice)
    await db.flush()
    rev = InvoiceRevision(
        invoice_id=invoice.id,
        revision_number=1,
        origin="owner_upload" if asset else "manual_entry",
        source_asset_id=asset.id if asset else None,
        uploaded_by=user_id,
        status="uploaded",
    )
    db.add(rev)
    await db.flush()
    invoice.current_revision_id = rev.id
    await db.flush()
    return invoice, True


# ============================================================================ extraction
def provider_status() -> dict:
    provider = extraction.get_provider()
    return {
        "provider": provider.name,
        "available": provider.available,
        "message": None
        if provider.available
        else "Automatic invoice reading is unavailable right now. You can enter and correct the details yourself.",
        "substitute": provider.name == "local_fixture",
    }


async def request_extraction(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, idempotency_key: str
) -> tuple[AnalysisRun, bool]:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    replay = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.requested_by == user_id, AnalysisRun.idempotency_key == idempotency_key
            )
        )
    ).scalar_one_or_none()
    if replay is not None:
        if replay.invoice_id != invoice.id or replay.kind != "invoice_extraction":
            raise AppError(409, "idempotency_key_reused", "That Idempotency-Key was already used for another request")
        return replay, False
    provider = extraction.get_provider()
    if not provider.available:
        raise AppError(503, "extraction_unavailable", provider_status()["message"])
    rev = await current_revision(db, invoice)
    if rev.source_asset_id is None:
        raise AppError(409, "no_document", "This invoice has no document to read; enter the details instead")
    if rev.extracted:
        raise AppError(409, "already_extracted", "This document has already been read; correct the details instead")
    asset = await db.get(EvidenceAsset, rev.source_asset_id)
    if asset is None or asset.status != "available" or asset.deleted_at is not None:
        raise AppError(409, "asset_not_available", "The invoice file is not available")
    inflight = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.invoice_id == invoice.id,
                AnalysisRun.invoice_revision_id == rev.id,
                AnalysisRun.kind == "invoice_extraction",
                AnalysisRun.status.in_(("pending", "running")),
            )
        )
    ).scalar_one_or_none()
    if inflight is not None:
        return inflight, False
    settings = get_settings()
    recent = (
        await db.execute(
            select(func.count(AnalysisRun.id)).where(
                AnalysisRun.requested_by == user_id, AnalysisRun.created_at > utcnow() - timedelta(days=1)
            )
        )
    ).scalar_one()
    if recent >= settings.service_analysis_runs_per_day:
        raise AppError(429, "analysis_quota_exceeded", "Too many document readings today. Please try again tomorrow.")
    try:
        async with db.begin_nested():
            run, created = await runs.create(
                db,
                kind="invoice_extraction",
                requested_by=user_id,
                invoice=invoice,
                assets=[asset],
                provider=provider.name,
                model=provider.model,
                config_version=extraction.CONFIG_VERSION,
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        raise AppError(
            409, "idempotency_key_reused", "That Idempotency-Key was already used for another request"
        ) from None
    return run, created


def enqueue_extraction(run_id: uuid.UUID) -> bool:
    """Queue the worker after the run is committed. Broker failures never fail the request:
    the run stays ``pending`` and the sweep task picks it up."""
    try:
        from app.celery_app import celery

        celery.send_task(EXTRACT_TASK, args=[str(run_id)], retry=False, ignore_result=True)
        return True
    except Exception as exc:  # pragma: no cover - broker outage
        logger.error("Could not queue invoice extraction: %s", type(exc).__name__)
        return False


EXTRACT_TASK = "app.tasks.service_invoices.extract_invoice"


async def execute_extraction_run(db: AsyncSession, run_id: uuid.UUID) -> str:
    """Worker body: claim → read the derivative → provider (no transaction open) → publish."""
    token = await runs.claim(db, run_id)
    if token is None:
        return "not_claimed"
    run = await db.get(AnalysisRun, run_id, populate_existing=True)
    if await runs.stale_reason(db, run) is not None:
        return await runs.publish(db, run_id, token, {})  # stored as a superseded diagnostic
    if not run.asset_versions:
        await runs.fail(db, run_id, token, "no_document")
        return "failed"
    asset_id = uuid.UUID(next(iter(run.asset_versions)))
    asset = await db.get(EvidenceAsset, asset_id)
    key = asset.derivative_key or asset.storage_key
    media_type = asset.detected_type or asset.declared_content_type or "application/octet-stream"
    pages = asset.pages
    await db.commit()  # end the read transaction: nothing is held across storage/provider calls
    try:
        content = await asyncio.to_thread(storage.get_store().get, key)
    except storage.ObjectStoreError:
        await runs.fail(db, run_id, token, "document_unavailable")
        return "failed"
    provider = extraction.get_provider()
    inp = extraction.ExtractionInput(
        content=content, media_type=media_type, sha256=hashlib.sha256(content).hexdigest(), pages=pages
    )
    try:
        draft = await provider.extract(inp)
    except extraction.ExtractionUnavailableError:
        await runs.fail(db, run_id, token, "provider_unavailable")
        return "failed"
    except Exception as exc:  # never let a parser bug leak document text
        logger.error("Invoice extraction failed: %s", type(exc).__name__)
        await runs.fail(db, run_id, token, "extraction_error")
        return "failed"
    output = {
        **draft.to_dict(),
        "provider": provider.name,
        "model": provider.model,
        "config_version": extraction.CONFIG_VERSION,
        "run_id": str(run_id),
        "media_type": media_type,
    }
    return await runs.publish(db, run_id, token, output, apply=_apply_extraction)


def _line_decimal(value: str | None) -> tuple[Decimal | None, bool]:
    if value is None:
        return None, False
    try:
        d = invoice_math.to_decimal(value)
    except invoice_math.AmountError:
        return None, True
    if not _within_precision(d):
        return None, True
    return d, False


async def _apply_extraction(db: AsyncSession, run: AnalysisRun) -> None:
    invoice = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == run.invoice_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if invoice is None or invoice.deleted_at is not None or invoice.current_revision_id != run.invoice_revision_id:
        run.status, run.output = "superseded", {"stale": "invoice_revised"}
        return
    rev = await current_revision(db, invoice, lock=True)
    if rev.extracted:
        run.status, run.output = "superseded", {"stale": "already_extracted"}
        return
    output = copy.deepcopy(run.output)
    fields = copy.deepcopy(rev.fields or {})
    for name in FIELD_NAMES:
        if (fields.get(name) or {}).get("source") in OWNER_SOURCES:
            continue  # the owner already entered this value by hand; the draft stays visible as extracted
        f = output["fields"][name]
        value = f["value"]
        if name in AMOUNT_FIELDS and value is not None:
            d, bad = _line_decimal(value)
            value = None if bad else format(d, "f")
            f = {**f, "illegible": f.get("illegible") or bad}
        fields[name] = {
            "value": value,
            "source": "extracted",
            "certainty": f["certainty"],
            "page": f["page"],
            "region": f["region"],
            "illegible": bool(f.get("illegible")),
            "by": None,
            "at": None,
            "history": [],
        }
    rev.fields = fields
    cur = (fields.get("currency") or {}).get("value")
    rev.currency = cur if invoice_math.valid_currency(cur) else None
    existing = await lines_of(db, rev.id)
    output["lines_applied"] = not existing
    if not existing:
        for ln in output["lines"]:
            values: dict[str, Any] = {}
            illegible = list(ln.get("illegible") or [])
            for col in LINE_DECIMALS:
                d, bad = _line_decimal(ln.get(col))
                values[col] = d
                if bad and col not in illegible:
                    illegible.append(col)
            certainty = "low" if illegible and ln["certainty"] in ("high", "medium") else ln["certainty"]
            db.add(
                InvoiceLine(
                    invoice_revision_id=rev.id,
                    line_number=ln["line_number"],
                    kind=ln["kind"],
                    description=ln.get("description"),
                    part_number=ln.get("part_number"),
                    unit=ln.get("unit"),
                    currency=ln.get("currency"),
                    page=ln.get("page"),
                    region=ln.get("region"),
                    certainty=certainty,
                    extracted={
                        "origin": "extracted",
                        "values": {c: ln.get(c) for c in LINE_VALUE_COLUMNS},
                        "kind_certainty": ln.get("kind_certainty"),
                        "illegible": illegible,
                    },
                    **values,
                )
            )
    rev.extracted = output
    if rev.status == "uploaded" or (rev.status == "owner_reviewed" and not existing and output["lines"]):
        rev.status = "extraction_draft"
    invoice.status = rev.status
    _touch(invoice, rev)
    await supersede_explanations(db, rev.id)


# ============================================================================ corrections
def _normalise_field(name: str, raw) -> str | None:
    if raw is None:
        return None
    if name in AMOUNT_FIELDS:
        try:
            d = invoice_math.to_decimal(raw)
        except invoice_math.AmountError as exc:
            raise AppError(422, "invalid_amount", f"{name}: {exc}") from None
        if not _within_precision(d):
            raise AppError(422, "invalid_amount", f"{name}: at most {MAX_PLACES} decimal places")
        return format(d, "f")
    if name == "currency":
        code = str(raw).strip().upper()
        if not invoice_math.valid_currency(code):
            raise AppError(422, "invalid_currency", "Use a three-letter currency code such as NZD, AUD or JPY")
        return code
    text = str(raw).strip()
    return text or None


def _blank_field() -> dict:
    return {
        "value": None,
        "source": "not_extracted",
        "certainty": "unknown",
        "page": None,
        "region": None,
        "illegible": False,
        "by": None,
        "at": None,
        "history": [],
    }


async def correct_fields(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, expected_version: int, changes: dict[str, Any]
) -> Invoice:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev = await current_revision(db, invoice, lock=True)
    access.check_version(rev.version, expected_version, "invoice")
    extracted_fields = (rev.extracted or {}).get("fields") or {}
    fields = copy.deepcopy(rev.fields or {})
    now, changed = _now(), {}
    for name, raw in changes.items():
        value = _normalise_field(name, raw)
        entry = fields.get(name) or _blank_field()
        old = entry.get("value")
        history = list(entry.get("history") or [])
        history.append({"value": old, "source": entry.get("source"), "by": entry.get("by"), "at": entry.get("at")})
        if name in extracted_fields:
            source = "owner_confirmed" if value == extracted_fields[name].get("value") else "owner_corrected"
        else:
            source = "owner_entered"
        entry.update(value=value, source=source, by=str(user_id), at=now, history=history[-20:], illegible=False)
        fields[name] = entry
        changed[name] = [old, value]
    rev.fields = fields
    if "currency" in changes:
        rev.currency = fields["currency"]["value"]
    _touch(invoice, rev)
    await supersede_explanations(db, rev.id)
    await audit.record(
        db,
        user_id,
        "invoice.fields_corrected",
        "service_invoice",
        invoice.id,
        {"revision_id": str(rev.id), "changed": changed},
    )
    return invoice


def _line_values(line: InvoiceLine) -> dict:
    return {
        "kind": line.kind,
        "description": line.description,
        "part_number": line.part_number,
        "quantity": invoice_math.fmt(line.quantity),
        "unit": line.unit,
        "unit_price": invoice_math.fmt(line.unit_price),
        "line_total": invoice_math.fmt(line.line_total),
        "tax_printed": invoice_math.fmt(line.tax_printed),
        "currency": line.currency,
    }


def _apply_line_changes(line: InvoiceLine, changes: dict[str, Any]) -> dict:
    before = _line_values(line)
    for col, raw in changes.items():
        if col in LINE_DECIMALS:
            try:
                d = invoice_math.to_decimal(raw)
            except invoice_math.AmountError as exc:
                raise AppError(422, "invalid_amount", f"{col}: {exc}") from None
            if d is not None and not _within_precision(d):
                raise AppError(422, "invalid_amount", f"{col}: at most {MAX_PLACES} decimal places")
            setattr(line, col, d)
        elif col == "currency":
            code = raw.strip().upper() if raw else None
            if code is not None and not invoice_math.valid_currency(code):
                raise AppError(422, "invalid_currency", "Use a three-letter currency code such as NZD, AUD or JPY")
            line.currency = code
        else:
            setattr(line, col, (raw.strip() or None) if isinstance(raw, str) else raw)
    if line.kind is None:
        line.kind = "unknown"
    after = _line_values(line)
    return {k: [before[k], after[k]] for k in after if before[k] != after[k]}


async def _current_line(db: AsyncSession, rev: InvoiceRevision, line_id: uuid.UUID) -> InvoiceLine:
    line = (
        await db.execute(
            select(InvoiceLine)
            .where(InvoiceLine.id == line_id, InvoiceLine.invoice_revision_id == rev.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if line is None:
        raise not_found("Invoice line")
    return line


async def correct_line(
    db: AsyncSession,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
) -> Invoice:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev = await current_revision(db, invoice, lock=True)
    line = await _current_line(db, rev, line_id)
    access.check_version(line.version, expected_version, "invoice line")
    changed = _apply_line_changes(line, changes)
    line.corrected_by, line.corrected_at = user_id, utcnow()
    line.version += 1
    _touch(invoice, rev)
    await supersede_explanations(db, rev.id)
    await audit.record(
        db,
        user_id,
        "invoice.line_corrected",
        "service_invoice",
        invoice.id,
        {"revision_id": str(rev.id), "line_id": str(line.id), "changed": changed},
    )
    return invoice


async def add_line(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, expected_version: int, values: dict[str, Any]
) -> tuple[Invoice, InvoiceLine]:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev = await current_revision(db, invoice, lock=True)
    access.check_version(rev.version, expected_version, "invoice")
    number = (
        await db.execute(
            select(func.coalesce(func.max(InvoiceLine.line_number), 0)).where(InvoiceLine.invoice_revision_id == rev.id)
        )
    ).scalar_one()
    line = InvoiceLine(
        invoice_revision_id=rev.id,
        line_number=number + 1,
        kind="unknown",
        certainty="unknown",
        extracted={"origin": "owner_manual"},
        corrected_by=user_id,
        corrected_at=utcnow(),
    )
    _apply_line_changes(line, values)
    db.add(line)
    _touch(invoice, rev)
    await db.flush()
    await supersede_explanations(db, rev.id)
    await audit.record(
        db,
        user_id,
        "invoice.line_added",
        "service_invoice",
        invoice.id,
        {"revision_id": str(rev.id), "line_id": str(line.id), "values": _line_values(line)},
    )
    return invoice, line


async def delete_line(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, line_id: uuid.UUID, expected_version: int
) -> Invoice:
    """Remove a line from the reviewed set (the extracted original stays in the revision's
    immutable ``extracted`` record and the removal is audited)."""
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev = await current_revision(db, invoice, lock=True)
    line = await _current_line(db, rev, line_id)
    access.check_version(line.version, expected_version, "invoice line")
    await audit.record(
        db,
        user_id,
        "invoice.line_removed",
        "service_invoice",
        invoice.id,
        {"revision_id": str(rev.id), "line_id": str(line.id), "values": _line_values(line)},
    )
    await db.execute(delete(InvoiceLine).where(InvoiceLine.id == line.id))
    _touch(invoice, rev)
    await supersede_explanations(db, rev.id)
    return invoice


def field_needs_confirmation(entry: dict) -> bool:
    if entry.get("source") != "extracted":
        return False
    if entry.get("illegible"):
        return True
    return entry.get("value") is not None and entry.get("certainty") in NEEDS_CONFIRMATION_CERTAINTY


def line_source(line: InvoiceLine) -> str:
    origin = (line.extracted or {}).get("origin", "extracted")
    if origin == "owner_manual":
        return "owner_entered"
    if line.corrected_by is not None:
        return "owner_corrected" if _changed_columns(line) else "owner_confirmed"
    return "extracted"


def _same(a, b) -> bool:
    if a == b:
        return True
    try:
        return a is not None and b is not None and Decimal(str(a)) == Decimal(str(b))
    except ArithmeticError:
        return False


def _changed_columns(line: InvoiceLine) -> list[str]:
    original = (line.extracted or {}).get("values")
    if original is None:
        return []
    now = _line_values(line)
    return sorted(k for k in now if not _same(now[k], original.get(k)))


def line_illegible(line: InvoiceLine) -> list[str]:
    if line.corrected_by is not None:
        return []
    return list((line.extracted or {}).get("illegible") or [])


def line_needs_confirmation(line: InvoiceLine) -> bool:
    if line_source(line) != "extracted":
        return False
    return bool(line_illegible(line)) or line.certainty in NEEDS_CONFIRMATION_CERTAINTY


def flagged_items(rev: InvoiceRevision, lines: list[InvoiceLine]) -> list[str]:
    fields = rev.fields or {}
    out = [f"field:{n}" for n in FIELD_NAMES if field_needs_confirmation(fields.get(n) or {})]
    out += [f"line:{ln.id}" for ln in lines if line_needs_confirmation(ln)]
    return out


async def review(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, expected_version: int, confirm: list[str]
) -> Invoice:
    """Owner review: listed low-certainty items are confirmed as printed; anything still
    flagged blocks the review (409 ``needs_confirmation``)."""
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev = await current_revision(db, invoice, lock=True)
    access.check_version(rev.version, expected_version, "invoice")
    lines = await lines_of(db, rev.id, lock=True)
    by_id = {str(ln.id): ln for ln in lines}
    fields = copy.deepcopy(rev.fields or {})
    now = _now()
    for item in confirm:
        kind, _, ref = item.partition(":")
        if kind == "field" and ref in FIELD_NAMES and ref in fields:
            entry = fields[ref]
            if entry.get("source") == "extracted":
                history = list(entry.get("history") or [])
                history.append({"value": entry.get("value"), "source": "extracted", "by": None, "at": None})
                entry.update(source="owner_confirmed", by=str(user_id), at=now, history=history, illegible=False)
        elif kind == "line" and ref in by_id:
            ln = by_id[ref]
            if ln.corrected_by is None:
                ln.corrected_by, ln.corrected_at = user_id, utcnow()
                ln.version += 1
        else:
            raise AppError(422, "invalid_confirmation", f"Unknown item to confirm: {item}")
    rev.fields = fields
    remaining = flagged_items(rev, lines)
    if remaining:
        raise AppError(
            409,
            "needs_confirmation",
            "Some values were hard to read. Confirm or correct them before marking the invoice reviewed.",
            extra={"needs_confirmation": remaining},
        )
    fields["_review"] = {"by": str(user_id), "at": now}
    rev.fields = dict(fields)
    rev.status = "owner_reviewed"
    invoice.status = "owner_reviewed"
    _touch(invoice, rev)
    await supersede_explanations(db, rev.id)
    await audit.record(db, user_id, "invoice.reviewed", "service_invoice", invoice.id, {"revision_id": str(rev.id)})
    return invoice


async def delete_invoice(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, expected_version: int | None
) -> None:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    access.check_version(invoice.version, expected_version, "invoice")
    invoice.status, invoice.deleted_at = "deleted", utcnow()
    _touch(invoice)
    rev_ids = (await db.execute(select(InvoiceRevision.id).where(InvoiceRevision.invoice_id == invoice.id))).scalars()
    for rid in list(rev_ids):
        await supersede_explanations(db, rid)
    await db.execute(
        update(InvoiceQuestion)
        .where(InvoiceQuestion.invoice_id == invoice.id)
        .values(status="closed")
        .execution_options(synchronize_session=False)
    )
    await audit.record(db, user_id, "invoice.deleted", "service_invoice", invoice.id, {})


# ============================================================================ explanation
async def _accepted_scopes(db: AsyncSession, job_id: uuid.UUID) -> list[dict]:
    rows = (
        await db.execute(
            select(ScopeRevision, ScopeDecision)
            .join(ScopeDecision, ScopeDecision.scope_revision_id == ScopeRevision.id)
            .where(
                ScopeRevision.job_id == job_id,
                ScopeDecision.job_id == job_id,
                ScopeDecision.decision == "accepted",
                ScopeDecision.revision_digest == ScopeRevision.content_digest,
            )
            .order_by(ScopeRevision.revision_number)
        )
    ).all()
    accepted = {rev.id for rev, _ in rows}
    # A later accepted full revision replaces the one it supersedes; accepted changes add to it.
    replaced = {rev.supersedes_id for rev, _ in rows if rev.supersedes_id in accepted and not rev.is_change}
    return [
        {
            "id": str(rev.id),
            "revision_number": rev.revision_number,
            "is_change": rev.is_change,
            "summary": rev.summary,
            "currency": rev.currency,
            "estimate_lines": rev.estimate_lines or [],
            "estimate_total_minor": rev.estimate_total_minor,
            "content_digest": rev.content_digest,
            "decision": {
                "id": str(dec.id),
                "decided_at": dec.decided_at.isoformat(),
                "decided_by": str(dec.decided_by),
            },
        }
        for rev, dec in rows
        if rev.id not in replaced
    ]


def _line_dict(line: InvoiceLine, currency: str | None = None) -> dict:
    cur = line.currency or currency
    return {
        "id": str(line.id),
        "line_number": line.line_number,
        "kind": line.kind,
        "description": line.description,
        "part_number": line.part_number,
        "quantity": invoice_math.fmt(line.quantity),
        "unit": line.unit,
        "unit_price": invoice_math.fmt(line.unit_price, cur),
        "line_total": invoice_math.fmt(line.line_total, cur),
        "tax_printed": invoice_math.fmt(line.tax_printed, cur),
        "currency": line.currency,
        "page": line.page,
        "region": line.region,
        "certainty": line.certainty,
        "needs_confirmation": line_needs_confirmation(line),
        "illegible": line_illegible(line),
        "version": line.version,
    }


async def build_context(
    db: AsyncSession, invoice: Invoice, rev: InvoiceRevision, lines: list[InvoiceLine]
) -> tuple[invoice_explain.ExplainContext, str]:
    fields = {n: field_view(n, (rev.fields or {}).get(n), rev) for n in FIELD_NAMES}
    job_ctx, prep, scopes = None, [], None
    if invoice.job_id is not None:
        job = await db.get(ServiceJob, invoice.job_id)
        if job is not None and job.deleted_at is None:
            job_ctx = {
                "id": str(job.id),
                "title": job.title,
                "affected_system": job.affected_system,
                "affected_equipment": job.affected_equipment,
            }
            prep = [
                {"id": str(p.id), "name": p.name, "status": p.status, "version": p.version}
                for p in (
                    await db.execute(
                        select(PreparationItem)
                        .where(
                            PreparationItem.job_id == job.id,
                            PreparationItem.status.notin_(("rejected", "replaced", "superseded")),
                        )
                        .order_by(PreparationItem.created_at)
                    )
                ).scalars()
            ]
            scopes = await _accepted_scopes(db, job.id)
    line_dicts = [_line_dict(ln, rev.currency) for ln in lines]
    ctx = invoice_explain.ExplainContext(
        invoice_id=str(invoice.id),
        revision_id=str(rev.id),
        revision_number=rev.revision_number,
        revision_status=rev.status,
        fields=fields,
        lines=line_dicts,
        job=job_ctx,
        preparation_items=prep,
        scopes=scopes,
        illegible_fields=[n for n, f in fields.items() if f["illegible"]],
    )
    basis = runs.digest(
        {
            "version": invoice_explain.EXPLANATION_VERSION,
            "revision": str(rev.id),
            "status": rev.status,
            "fields": {n: [f["value"], f["source"], f["illegible"]] for n, f in fields.items()},
            "lines": line_dicts,
            "job": job_ctx,
            "prep": prep,
            "scopes": [(s["id"], s["content_digest"], s["decision"]["id"]) for s in scopes or []],
        }
    )
    return ctx, basis


def checks_for(ctx: invoice_explain.ExplainContext) -> dict:
    def amount(name: str) -> Decimal | None:
        return _dec(ctx.fields[name]["value"])

    inp = invoice_math.InvoiceInput(
        currency=ctx.fields["currency"]["value"],
        subtotal=amount("subtotal"),
        tax_printed=amount("tax_printed"),
        total=amount("total"),
        illegible=ctx.illegible_fields,
        lines=[
            invoice_math.LineInput(
                id=ln["id"],
                line_number=ln["line_number"],
                kind=ln["kind"],
                quantity=_dec(ln["quantity"]),
                unit=ln["unit"],
                unit_price=_dec(ln["unit_price"]),
                line_total=_dec(ln["line_total"]),
                tax_printed=_dec(ln["tax_printed"]),
                currency=ln["currency"],
                illegible=ln["illegible"],
            )
            for ln in ctx.lines
        ],
    )
    return invoice_math.invoice_checks(inp)


async def explain(db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID) -> tuple[InvoiceExplanation, bool]:
    """Compute (or return the identical current) explanation for the current revision."""
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev = await current_revision(db, invoice)
    lines = await lines_of(db, rev.id)
    ctx, basis = await build_context(db, invoice, rev, lines)
    current = (
        (
            await db.execute(
                select(InvoiceExplanation).where(
                    InvoiceExplanation.invoice_revision_id == rev.id, InvoiceExplanation.status == "current"
                )
            )
        )
        .scalars()
        .all()
    )
    for exp in current:
        if exp.basis_digest == basis:
            return exp, False
    await supersede_explanations(db, rev.id)
    content = invoice_explain.build(ctx, checks_for(ctx))
    exp = InvoiceExplanation(invoice_revision_id=rev.id, status="current", basis_digest=basis, content=content)
    db.add(exp)
    await db.flush()
    return exp, True


# ============================================================================ questions (owner)
async def _question(
    db: AsyncSession, invoice: Invoice, question_id: uuid.UUID, *, lock: bool = False
) -> InvoiceQuestion:
    q = select(InvoiceQuestion).where(InvoiceQuestion.id == question_id, InvoiceQuestion.invoice_id == invoice.id)
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    question = (await db.execute(q)).scalar_one_or_none()
    if question is None:
        raise not_found("Question")
    return question


async def _line_on_invoice(db: AsyncSession, invoice: Invoice, line_id: uuid.UUID) -> InvoiceLine:
    line = (
        await db.execute(
            select(InvoiceLine)
            .join(InvoiceRevision, InvoiceRevision.id == InvoiceLine.invoice_revision_id)
            .where(InvoiceLine.id == line_id, InvoiceRevision.invoice_id == invoice.id)
        )
    ).scalar_one_or_none()
    if line is None:
        raise not_found("Invoice line")
    return line


async def create_question(
    db: AsyncSession,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    text: str,
    line_id: uuid.UUID | None,
    suggestion_key: str | None,
) -> InvoiceQuestion:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    rev_id = invoice.current_revision_id
    if line_id is not None:
        line = await _line_on_invoice(db, invoice, line_id)
        rev_id = line.invoice_revision_id
    q = InvoiceQuestion(
        invoice_id=invoice.id,
        invoice_revision_id=rev_id,
        line_id=line_id,
        origin="assistant_suggestion" if suggestion_key else "owner",
        text=text,
        status="draft",
        created_by=user_id,
    )
    db.add(q)
    await db.flush()
    return q


async def update_question(
    db: AsyncSession,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    question_id: uuid.UUID,
    expected_version: int,
    changes: dict[str, Any],
) -> InvoiceQuestion:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    q = await _question(db, invoice, question_id, lock=True)
    access.check_version(q.version, expected_version, "question")
    if q.status != "draft":
        raise AppError(409, "question_already_sent", "A sent question can't be edited; ask a new question instead")
    if "line_id" in changes:
        if changes["line_id"] is not None:
            line = await _line_on_invoice(db, invoice, changes["line_id"])
            q.invoice_revision_id = line.invoice_revision_id
        q.line_id = changes["line_id"]
    if "text" in changes:
        q.text = changes["text"]
    q.version += 1
    q.updated_at = utcnow()
    return q


async def delete_question(
    db: AsyncSession, user_id: uuid.UUID, invoice_id: uuid.UUID, question_id: uuid.UUID, expected_version: int | None
) -> None:
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    q = await _question(db, invoice, question_id, lock=True)
    access.check_version(q.version, expected_version, "question")
    if q.status != "draft":
        raise AppError(409, "question_already_sent", "A sent question can't be deleted")
    await db.delete(q)


async def _shareable_assets(
    db: AsyncSession, user_id: uuid.UUID, invoice: Invoice, asset_ids: list[uuid.UUID]
) -> list[EvidenceAsset]:
    """Only the owner's own available documents of this invoice or of its job."""
    if not asset_ids:
        return []
    revision_assets = set(
        (
            await db.execute(
                select(InvoiceRevision.source_asset_id).where(
                    InvoiceRevision.invoice_id == invoice.id, InvoiceRevision.source_asset_id.is_not(None)
                )
            )
        ).scalars()
    )
    rows = (
        await db.execute(
            select(EvidenceAsset).where(
                EvidenceAsset.id.in_(asset_ids),
                EvidenceAsset.owner_id == user_id,
                EvidenceAsset.status.in_(SHAREABLE_ASSET_STATUSES),
                EvidenceAsset.deleted_at.is_(None),
            )
        )
    ).scalars()
    found = {
        a.id: a for a in rows if a.id in revision_assets or (invoice.job_id is not None and a.job_id == invoice.job_id)
    }
    if set(asset_ids) - set(found):
        raise not_found("Supporting document")
    return [found[i] for i in asset_ids]


async def send_question(
    db: AsyncSession,
    user_id: uuid.UUID,
    invoice_id: uuid.UUID,
    question_id: uuid.UUID,
    *,
    expected_version: int,
    asset_ids: list[uuid.UUID],
    idempotency_key: str,
) -> tuple[InvoiceQuestion, bool]:
    """The owner's explicit send: shares this question and the selected documents with the
    job's accepted assignment. Nothing is sent any other way."""
    invoice = await owned_invoice(db, user_id, invoice_id, lock=True)
    q = await _question(db, invoice, question_id, lock=True)
    if q.status in ("shared", "answered"):
        return q, False  # repeated send: already shared, nothing sent twice
    if q.status != "draft":
        raise AppError(409, "question_closed", "This question is closed")
    access.check_version(q.version, expected_version, "question")
    if invoice.job_id is None:
        raise AppError(
            409,
            "standalone_invoice",
            "This invoice isn't linked to a service job, so there is no assigned contractor to ask.",
        )
    actor = await access.job_for(db, user_id, invoice.job_id, owner_only=True)
    assignment = await access.live_assignment(db, actor.job.id)
    if assignment is None or assignment.status != "accepted":
        raise AppError(
            409, "no_assigned_contractor", "No contractor has accepted this job, so there is no one to ask yet."
        )
    unique_ids = list(dict.fromkeys(asset_ids))
    if len(unique_ids) > MAX_SHARED_ASSETS:
        raise AppError(422, "too_many_documents", f"Share at most {MAX_SHARED_ASSETS} documents with a question")
    assets = await _shareable_assets(db, user_id, invoice, unique_ids)
    q.status = "shared"
    q.shared_assignment_id = assignment.id
    q.shared_asset_ids = [str(a.id) for a in assets]
    q.shared_at = utcnow()
    q.version += 1
    q.updated_at = utcnow()
    await audit.record(
        db,
        user_id,
        "invoice_question.shared",
        "service_invoice_question",
        q.id,
        {
            "invoice_id": str(invoice.id),
            "job_id": str(invoice.job_id),
            "assignment_id": str(assignment.id),
            "organization_id": str(assignment.organization_id),
            "asset_ids": q.shared_asset_ids,
            "idempotency_key": idempotency_key,
        },
    )
    members = (
        await db.execute(
            select(JobAssignmentMember.user_id).where(
                JobAssignmentMember.assignment_id == assignment.id, JobAssignmentMember.removed_at.is_(None)
            )
        )
    ).scalars()
    for member_id in list(members):
        await notify.notify(db, member_id, "invoice_question", job_id=invoice.job_id, key=f"{q.id}:{member_id}")
    return q, True


# ============================================================================ contractor side
async def contractor_actor(db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID) -> access.JobActor:
    actor = await access.job_for(db, user_id, job_id)
    if actor.role != "contractor":
        raise AppError(403, "contractor_only", "Owners manage invoice questions from the invoice itself")
    return actor


def _visible_questions(actor: access.JobActor):
    return (
        select(InvoiceQuestion, Invoice)
        .join(Invoice, Invoice.id == InvoiceQuestion.invoice_id)
        .where(
            Invoice.job_id == actor.job.id,
            Invoice.deleted_at.is_(None),
            InvoiceQuestion.shared_assignment_id == actor.assignment.id,
            InvoiceQuestion.status.in_(("shared", "answered")),
        )
    )


async def shared_questions(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID
) -> list[tuple[InvoiceQuestion, Invoice]]:
    actor = await contractor_actor(db, user_id, job_id)
    rows = (await db.execute(_visible_questions(actor).order_by(InvoiceQuestion.shared_at.desc()))).all()
    return [(q, inv) for q, inv in rows]


async def shared_question(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID, question_id: uuid.UUID
) -> tuple[access.JobActor, InvoiceQuestion, Invoice]:
    actor = await contractor_actor(db, user_id, job_id)
    row = (await db.execute(_visible_questions(actor).where(InvoiceQuestion.id == question_id))).first()
    if row is None:
        raise not_found("Question")
    return actor, row[0], row[1]


async def shared_asset_url(
    db: AsyncSession, user_id: uuid.UUID, job_id: uuid.UUID, question_id: uuid.UUID, asset_id: uuid.UUID
) -> dict:
    _actor, q, _invoice = await shared_question(db, user_id, job_id, question_id)
    if str(asset_id) not in (q.shared_asset_ids or []):
        raise not_found("Shared document")
    asset = await db.get(EvidenceAsset, asset_id)
    if asset is None or asset.status != "available" or asset.deleted_at is not None:
        raise not_found("Shared document")
    seconds = min(get_settings().signed_url_seconds, 300)
    key = asset.derivative_key or asset.storage_key
    content_type = asset.detected_type or "application/octet-stream"
    url = storage.get_store().signed_get_url(
        key, filename=f"invoice-document-{asset.id.hex[:8]}", content_type=content_type, seconds=seconds
    )
    return {"url": url, "expires_in": seconds, "content_type": content_type}


async def new_revision(
    db: AsyncSession,
    invoice: Invoice,
    *,
    origin: str,
    asset: EvidenceAsset,
    uploaded_by: uuid.UUID,
    organization_id: uuid.UUID | None,
) -> InvoiceRevision:
    """A new document revision supersedes the current one (and its explanation). Caller
    holds the invoice lock."""
    old = await current_revision(db, invoice, lock=True)
    number = (
        await db.execute(
            select(func.max(InvoiceRevision.revision_number)).where(InvoiceRevision.invoice_id == invoice.id)
        )
    ).scalar_one()
    rev = InvoiceRevision(
        invoice_id=invoice.id,
        revision_number=number + 1,
        origin=origin,
        source_asset_id=asset.id,
        uploaded_by=uploaded_by,
        organization_id=organization_id,
        status="uploaded",
        supersedes_id=old.id,
    )
    db.add(rev)
    old.status = "superseded"
    await db.flush()
    invoice.current_revision_id = rev.id
    invoice.status = "uploaded"
    _touch(invoice)
    await supersede_explanations(db, old.id)
    return rev


async def respond(
    db: AsyncSession,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    question_id: uuid.UUID,
    *,
    text: str,
    corrected_asset_id: uuid.UUID | None,
) -> tuple[InvoiceQuestionResponse, bool]:
    """The assigned contractor's attributed answer, optionally with a corrected invoice
    document (a new revision — the original and its extraction stay untouched)."""
    actor, q0, _ = await shared_question(db, user_id, job_id, question_id)
    invoice = (
        await db.execute(
            select(Invoice)
            .where(Invoice.id == q0.invoice_id, Invoice.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if invoice is None:
        raise not_found("Question")
    q = await _question(db, invoice, question_id, lock=True)
    if q.status not in ("shared", "answered") or q.shared_assignment_id != actor.assignment.id:
        raise not_found("Question")
    corrected: InvoiceRevision | None = None
    if corrected_asset_id is not None:
        asset = (
            await db.execute(
                select(EvidenceAsset)
                .where(
                    EvidenceAsset.id == corrected_asset_id,
                    EvidenceAsset.job_id == job_id,
                    EvidenceAsset.uploaded_by == user_id,
                    EvidenceAsset.purpose.in_(CORRECTION_ASSET_PURPOSES),
                    EvidenceAsset.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if asset is None:
            raise not_found("Corrected invoice document")
        if asset.status != "available":
            raise AppError(409, "asset_not_available", "The corrected document is still being checked")
        corrected = (
            await db.execute(
                select(InvoiceRevision).where(
                    InvoiceRevision.invoice_id == invoice.id, InvoiceRevision.source_asset_id == asset.id
                )
            )
        ).scalar_one_or_none()
        if corrected is None:
            corrected = await new_revision(
                db,
                invoice,
                origin="contractor_correction",
                asset=asset,
                uploaded_by=user_id,
                organization_id=actor.organization_id,
            )
    duplicate = (
        await db.execute(
            select(InvoiceQuestionResponse).where(
                InvoiceQuestionResponse.question_id == q.id,
                InvoiceQuestionResponse.author_id == user_id,
                InvoiceQuestionResponse.text == text,
                InvoiceQuestionResponse.corrected_revision_id.is_(None)
                if corrected is None
                else InvoiceQuestionResponse.corrected_revision_id == corrected.id,
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return duplicate, False
    resp = InvoiceQuestionResponse(
        question_id=q.id,
        author_id=user_id,
        organization_id=actor.organization_id,
        text=text,
        corrected_revision_id=corrected.id if corrected else None,
    )
    db.add(resp)
    q.status = "answered"
    q.version += 1
    q.updated_at = utcnow()
    await db.flush()
    await audit.record(
        db,
        user_id,
        "invoice_question.responded",
        "service_invoice_question",
        q.id,
        {
            "invoice_id": str(invoice.id),
            "job_id": str(job_id),
            "organization_id": str(actor.organization_id),
            "response_id": str(resp.id),
            "corrected_revision_id": str(corrected.id) if corrected else None,
        },
    )
    await notify.notify(db, invoice.owner_id, "invoice_response", job_id=job_id, key=str(resp.id))
    return resp, True


# ============================================================================ views
def field_view(name: str, entry: dict | None, rev: InvoiceRevision) -> dict:
    entry = entry or _blank_field()
    extracted = ((rev.extracted or {}).get("fields") or {}).get(name)
    return {
        "name": name,
        "value": entry.get("value"),
        "source": entry.get("source", "not_extracted"),
        "certainty": entry.get("certainty", "unknown"),
        "page": entry.get("page"),
        "region": entry.get("region"),
        "illegible": bool(entry.get("illegible")) and entry.get("source") == "extracted",
        "needs_confirmation": field_needs_confirmation(entry),
        "extracted_value": extracted.get("value") if extracted else None,
        "by": entry.get("by"),
        "at": entry.get("at"),
        "history": entry.get("history") or [],
    }


def line_view(line: InvoiceLine, currency: str | None = None) -> dict:
    ext = line.extracted or {}
    return {
        **_line_dict(line, currency),
        "source": line_source(line),
        "kind_certainty": ext.get("kind_certainty"),
        "extracted_values": ext.get("values"),
        "corrected_fields": _changed_columns(line),
        "corrected_by": line.corrected_by,
        "corrected_at": line.corrected_at,
    }


def revision_view(rev: InvoiceRevision) -> dict:
    ext = rev.extracted or {}
    review = (rev.fields or {}).get("_review") or {}
    return {
        "id": rev.id,
        "revision_number": rev.revision_number,
        "origin": rev.origin,
        "status": rev.status,
        "source_asset_id": rev.source_asset_id,
        "uploaded_by": rev.uploaded_by,
        "organization_id": rev.organization_id,
        "supersedes_id": rev.supersedes_id,
        "currency": rev.currency,
        "rounding": rev.rounding,
        "version": rev.version,
        "created_at": rev.created_at,
        "extraction_status": ext.get("status", "none"),
        "extraction_provider": ext.get("provider"),
        "extraction_notes": ext.get("notes") or [],
        "unparsed_text": ext.get("unparsed_text") or [],
        "reviewed_by": review.get("by"),
        "reviewed_at": review.get("at"),
        "fields": {n: field_view(n, (rev.fields or {}).get(n), rev) for n in FIELD_NAMES},
    }


def run_view(run: AnalysisRun | None) -> dict | None:
    if run is None:
        return None
    stale = (run.output or {}).get("stale") if run.status == "superseded" else None
    return {
        "id": run.id,
        "status": run.status,
        "invoice_revision_id": run.invoice_revision_id,
        "provider": run.provider,
        "model": run.model,
        "attempts": run.attempts,
        "error": run.error,
        "stale_reason": stale,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def response_view(r: InvoiceQuestionResponse, owner_id: uuid.UUID) -> dict:
    return {
        "id": r.id,
        "question_id": r.question_id,
        "author_id": r.author_id,
        "author_role": "owner" if r.author_id == owner_id else "contractor",
        "organization_id": r.organization_id,
        "text": r.text,
        "corrected_revision_id": r.corrected_revision_id,
        "created_at": r.created_at,
    }


async def responses_for(
    db: AsyncSession, question_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[InvoiceQuestionResponse]]:
    out: dict[uuid.UUID, list[InvoiceQuestionResponse]] = {qid: [] for qid in question_ids}
    if not question_ids:
        return out
    rows = (
        await db.execute(
            select(InvoiceQuestionResponse)
            .where(InvoiceQuestionResponse.question_id.in_(question_ids))
            .order_by(InvoiceQuestionResponse.created_at)
        )
    ).scalars()
    for r in rows:
        out[r.question_id].append(r)
    return out


def question_view(q: InvoiceQuestion, responses: list[InvoiceQuestionResponse], owner_id: uuid.UUID) -> dict:
    return {
        "id": q.id,
        "invoice_id": q.invoice_id,
        "invoice_revision_id": q.invoice_revision_id,
        "line_id": q.line_id,
        "origin": q.origin,
        "text": q.text,
        "status": q.status,
        "shared_assignment_id": q.shared_assignment_id,
        "shared_asset_ids": q.shared_asset_ids or [],
        "shared_at": q.shared_at,
        "created_by": q.created_by,
        "version": q.version,
        "created_at": q.created_at,
        "updated_at": q.updated_at,
        "responses": [response_view(r, owner_id) for r in responses],
    }


def explanation_view(exp: InvoiceExplanation | None, basis: str | None) -> dict | None:
    if exp is None:
        return None
    return {
        "id": exp.id,
        "invoice_revision_id": exp.invoice_revision_id,
        "status": exp.status,
        "basis_digest": exp.basis_digest,
        "stale": basis is not None and exp.basis_digest != basis,
        "created_at": exp.created_at,
        "content": exp.content,
    }


def summary_view(invoice: Invoice, rev: InvoiceRevision | None) -> dict:
    fields = (rev.fields or {}) if rev else {}
    total = (fields.get("total") or {}).get("value")
    return {
        "id": invoice.id,
        "title": invoice.title,
        "job_id": invoice.job_id,
        "standalone": invoice.job_id is None,
        "status": invoice.status,
        "version": invoice.version,
        "current_revision_id": invoice.current_revision_id,
        "revision_number": rev.revision_number if rev else None,
        "supplier_name": (fields.get("supplier_name") or {}).get("value"),
        "total": total,
        "currency": rev.currency if rev else None,
        "created_at": invoice.created_at,
        "updated_at": invoice.updated_at,
    }


async def detail_view(db: AsyncSession, invoice: Invoice) -> dict:
    await db.refresh(invoice)
    rev = await current_revision(db, invoice)
    lines = await lines_of(db, rev.id)
    revisions = list(
        (
            await db.execute(
                select(InvoiceRevision)
                .where(InvoiceRevision.invoice_id == invoice.id)
                .order_by(InvoiceRevision.revision_number)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    exp = (
        await db.execute(
            select(InvoiceExplanation)
            .where(InvoiceExplanation.invoice_revision_id == rev.id, InvoiceExplanation.status == "current")
            .order_by(InvoiceExplanation.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    _ctx, basis = await build_context(db, invoice, rev, lines)
    questions = list(
        (
            await db.execute(
                select(InvoiceQuestion)
                .where(InvoiceQuestion.invoice_id == invoice.id)
                .order_by(InvoiceQuestion.created_at)
                .execution_options(populate_existing=True)
            )
        ).scalars()
    )
    responses = await responses_for(db, [q.id for q in questions])
    latest_run = (
        await db.execute(
            select(AnalysisRun)
            .where(AnalysisRun.invoice_id == invoice.id, AnalysisRun.kind == "invoice_extraction")
            .order_by(AnalysisRun.created_at.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return {
        **summary_view(invoice, rev),
        "provisional": rev.status != "owner_reviewed",
        "needs_confirmation": flagged_items(rev, lines),
        "revision": revision_view(rev),
        "revisions": [
            {
                "id": r.id,
                "revision_number": r.revision_number,
                "origin": r.origin,
                "status": r.status,
                "source_asset_id": r.source_asset_id,
                "uploaded_by": r.uploaded_by,
                "organization_id": r.organization_id,
                "supersedes_id": r.supersedes_id,
                "created_at": r.created_at,
            }
            for r in revisions
        ],
        "lines": [line_view(ln, rev.currency) for ln in lines],
        "explanation": explanation_view(exp, basis),
        "questions": [question_view(q, responses[q.id], invoice.owner_id) for q in questions],
        "extraction": {**provider_status(), "latest_run": run_view(latest_run)},
    }


def shared_question_view(
    q: InvoiceQuestion,
    invoice: Invoice,
    line: InvoiceLine | None,
    assets: list[EvidenceAsset],
    rev: InvoiceRevision | None,
    responses: list[InvoiceQuestionResponse],
) -> dict:
    cur = (line.currency if line else None) or (rev.currency if rev else None)
    return {
        "id": q.id,
        "job_id": invoice.job_id,
        "invoice_id": invoice.id,
        "invoice_title": invoice.title,
        "invoice_revision_id": q.invoice_revision_id,
        "invoice_revision_number": rev.revision_number if rev else None,
        "text": q.text,
        "status": q.status,
        "shared_at": q.shared_at,
        "version": q.version,
        "line": None
        if line is None
        else {
            "line_number": line.line_number,
            "kind": line.kind,
            "description": line.description,
            "part_number": line.part_number,
            "quantity": invoice_math.fmt(line.quantity),
            "unit": line.unit,
            "unit_price": invoice_math.fmt(line.unit_price, cur),
            "line_total": invoice_math.fmt(line.line_total, cur),
            "currency": line.currency,
            "page": line.page,
        },
        "shared_assets": [
            {
                "id": a.id,
                "purpose": a.purpose,
                "detected_type": a.detected_type,
                "pages": a.pages,
                "size_bytes": a.size_bytes,
            }
            for a in assets
        ],
        "responses": [response_view(r, invoice.owner_id) for r in responses],
    }


async def shared_view(db: AsyncSession, q: InvoiceQuestion, invoice: Invoice) -> dict:
    line = await db.get(InvoiceLine, q.line_id) if q.line_id else None
    rev = await db.get(InvoiceRevision, q.invoice_revision_id)
    ids = [uuid.UUID(i) for i in q.shared_asset_ids or []]
    assets = []
    if ids:
        rows = (
            await db.execute(
                select(EvidenceAsset).where(
                    EvidenceAsset.id.in_(ids), EvidenceAsset.status == "available", EvidenceAsset.deleted_at.is_(None)
                )
            )
        ).scalars()
        by_id = {a.id: a for a in rows}
        assets = [by_id[i] for i in ids if i in by_id]
    responses = (await responses_for(db, [q.id]))[q.id]
    return shared_question_view(q, invoice, line, assets, rev, responses)
