"""Understand my invoice: upload, extraction, corrections, explanation, questions (workstream C).

Owner endpoints live under ``/invoices`` and are owner-private (anyone else: 404). The
assigned contractor's endpoints live under ``/service-jobs/{job_id}/invoice-questions``
and expose only questions the owner explicitly sent, with the documents selected for them.
Nothing here pays, disputes, orders, changes rewards or messages anyone automatically.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.core.rate_limit import mutation_limit
from app.database import get_db
from app.middleware.auth import CurrentUserId
from app.models.service_jobs import AnalysisRun, Invoice, InvoiceQuestion, InvoiceRevision
from app.schemas.invoices import (
    ContractorResponseCreate,
    ExtractionRunOut,
    FieldCorrections,
    InvoiceCreate,
    InvoiceDetailOut,
    InvoiceExplanationOut,
    InvoiceQuestionOut,
    InvoiceSummaryOut,
    LineCorrection,
    LineCreate,
    QuestionCreate,
    QuestionSend,
    QuestionUpdate,
    ReviewRequest,
    SharedInvoiceQuestionOut,
    SignedUrlOut,
)
from app.services.service_jobs import invoices as svc

router = APIRouter(tags=["Invoices"])

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,100}$")


def _require_key(key: str | None) -> str:
    if key is None or not IDEMPOTENCY_KEY.match(key):
        raise AppError(
            400,
            "idempotency_key_required",
            "An Idempotency-Key header of 8-100 characters (letters, digits, _ - : .) is required",
        )
    return key


async def _detail(db: AsyncSession, invoice: Invoice) -> dict:
    return await svc.detail_view(db, invoice)


# ============================================================================ owner
@router.post(
    "/invoices",
    response_model=InvoiceDetailOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": InvoiceDetailOut, "description": "Existing invoice for this document"}},
    dependencies=[Depends(mutation_limit())],
)
async def create_invoice(
    body: InvoiceCreate,
    response: Response,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Start "understand my invoice" from your uploaded invoice document (or manual entry).

    Linking ``job_id`` (your own job) enables comparison with the job's accepted scope and
    lets you send questions to the job's assigned contractor. A standalone invoice works
    fully for you but gives no one else access and creates no feedback eligibility."""
    invoice, created = await svc.create_invoice(
        db, user_id, asset_id=body.asset_id, job_id=body.job_id, title=body.title
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return await _detail(db, invoice)


@router.get("/invoices", response_model=list[InvoiceSummaryOut])
async def list_invoices(
    user_id: CurrentUserId,
    job_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict]:
    """Your invoices (newest first), optionally for one of your jobs."""
    q = (
        select(Invoice, InvoiceRevision)
        .outerjoin(InvoiceRevision, InvoiceRevision.id == Invoice.current_revision_id)
        .where(Invoice.owner_id == user_id, Invoice.deleted_at.is_(None))
    )
    if job_id is not None:
        q = q.where(Invoice.job_id == job_id)
    rows = (await db.execute(q.order_by(Invoice.created_at.desc()).limit(limit).offset(offset))).all()
    return [svc.summary_view(inv, rev) for inv, rev in rows]


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailOut)
async def get_invoice(
    invoice_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> dict:
    """The current revision with field/line sources, the explanation, questions and extraction status."""
    return await _detail(db, await svc.owned_invoice(db, user_id, invoice_id))


@router.delete(
    "/invoices/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(mutation_limit())]
)
async def delete_invoice(
    invoice_id: uuid.UUID,
    user_id: CurrentUserId,
    expected_version: int | None = Query(None),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    """Delete the invoice (soft delete): its explanations are invalidated and its questions closed."""
    await svc.delete_invoice(db, user_id, invoice_id, expected_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invoices/{invoice_id}/extract",
    response_model=ExtractionRunOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={200: {"model": ExtractionRunOut, "description": "Existing run for this key / revision"}},
    dependencies=[Depends(mutation_limit())],
)
async def extract_invoice(
    invoice_id: uuid.UUID,
    response: Response,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Queue reading of the current revision's document into a draft (asynchronous).

    Requires an ``Idempotency-Key``. With extraction unavailable this is a 503
    ``extraction_unavailable``; manual entry and correction keep working."""
    key = _require_key(idempotency_key)
    run, created = await svc.request_extraction(db, user_id, invoice_id, key)
    await db.commit()
    if created:
        svc.enqueue_extraction(run.id)
    else:
        response.status_code = status.HTTP_200_OK
    await db.refresh(run)
    return svc.run_view(run)


@router.get("/invoices/{invoice_id}/extraction-runs/{run_id}", response_model=ExtractionRunOut)
async def get_extraction_run(
    invoice_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    invoice = await svc.owned_invoice(db, user_id, invoice_id)
    run = (
        await db.execute(
            select(AnalysisRun).where(
                AnalysisRun.id == run_id, AnalysisRun.invoice_id == invoice.id, AnalysisRun.kind == "invoice_extraction"
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise not_found("Extraction run")
    return svc.run_view(run)


@router.patch(
    "/invoices/{invoice_id}/fields", response_model=InvoiceDetailOut, dependencies=[Depends(mutation_limit())]
)
async def correct_fields(
    invoice_id: uuid.UUID,
    body: FieldCorrections,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Correct or confirm header fields. The extracted values and the document are kept."""
    invoice = await svc.correct_fields(db, user_id, invoice_id, body.expected_version, body.changes())
    return await _detail(db, invoice)


@router.post(
    "/invoices/{invoice_id}/lines",
    response_model=InvoiceDetailOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def add_line(
    invoice_id: uuid.UUID,
    body: LineCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Add a line by hand (source ``owner_entered``)."""
    invoice, _line = await svc.add_line(db, user_id, invoice_id, body.expected_version, body.changes())
    return await _detail(db, invoice)


@router.patch(
    "/invoices/{invoice_id}/lines/{line_id}", response_model=InvoiceDetailOut, dependencies=[Depends(mutation_limit())]
)
async def correct_line(
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LineCorrection,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Correct (or confirm as printed) one line of the current revision."""
    invoice = await svc.correct_line(db, user_id, invoice_id, line_id, body.expected_version, body.changes())
    return await _detail(db, invoice)


@router.delete(
    "/invoices/{invoice_id}/lines/{line_id}", response_model=InvoiceDetailOut, dependencies=[Depends(mutation_limit())]
)
async def delete_line(
    invoice_id: uuid.UUID,
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    expected_version: int = Query(...),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Remove a misread line from the reviewed set (the extracted original is kept and the removal audited)."""
    invoice = await svc.delete_line(db, user_id, invoice_id, line_id, expected_version)
    return await _detail(db, invoice)


@router.post("/invoices/{invoice_id}/review", response_model=InvoiceDetailOut, dependencies=[Depends(mutation_limit())])
async def review_invoice(
    invoice_id: uuid.UUID,
    body: ReviewRequest,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Mark the current revision reviewed (comparisons stop being provisional). Values that
    were hard to read must be corrected or listed in ``confirm`` first (409 ``needs_confirmation``)."""
    invoice = await svc.review(db, user_id, invoice_id, body.expected_version, body.confirm)
    return await _detail(db, invoice)


@router.post(
    "/invoices/{invoice_id}/explain",
    response_model=InvoiceExplanationOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": InvoiceExplanationOut, "description": "Unchanged current explanation"}},
    dependencies=[Depends(mutation_limit())],
)
async def explain_invoice(
    invoice_id: uuid.UUID,
    response: Response,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Deterministic plain-language explanation, arithmetic checks, comparison with the
    accepted scope, obligations and suggested questions. Sends nothing."""
    exp, created = await svc.explain(db, user_id, invoice_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return svc.explanation_view(exp, exp.basis_digest)


# ---------------------------------------------------------------------------- questions
@router.get("/invoices/{invoice_id}/questions", response_model=list[InvoiceQuestionOut])
async def list_questions(
    invoice_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict]:
    invoice = await svc.owned_invoice(db, user_id, invoice_id)
    questions = list(
        (
            await db.execute(
                select(InvoiceQuestion)
                .where(InvoiceQuestion.invoice_id == invoice.id)
                .order_by(InvoiceQuestion.created_at)
            )
        ).scalars()
    )
    responses = await svc.responses_for(db, [q.id for q in questions])
    return [svc.question_view(q, responses[q.id], invoice.owner_id) for q in questions]


@router.post(
    "/invoices/{invoice_id}/questions",
    response_model=InvoiceQuestionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(mutation_limit())],
)
async def create_question(
    invoice_id: uuid.UUID,
    body: QuestionCreate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Draft a question (yours, or an edited suggestion). Drafts are private until you send them."""
    q = await svc.create_question(
        db, user_id, invoice_id, text=body.text, line_id=body.line_id, suggestion_key=body.suggestion_key
    )
    return svc.question_view(q, [], user_id)


@router.patch(
    "/invoices/{invoice_id}/questions/{question_id}",
    response_model=InvoiceQuestionOut,
    dependencies=[Depends(mutation_limit())],
)
async def update_question(
    invoice_id: uuid.UUID,
    question_id: uuid.UUID,
    body: QuestionUpdate,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    q = await svc.update_question(db, user_id, invoice_id, question_id, body.expected_version, body.changes())
    return svc.question_view(q, [], user_id)


@router.delete(
    "/invoices/{invoice_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(mutation_limit())],
)
async def delete_question(
    invoice_id: uuid.UUID,
    question_id: uuid.UUID,
    user_id: CurrentUserId,
    expected_version: int | None = Query(None),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    await svc.delete_question(db, user_id, invoice_id, question_id, expected_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invoices/{invoice_id}/questions/{question_id}/send",
    response_model=InvoiceQuestionOut,
    dependencies=[Depends(mutation_limit())],
)
async def send_question(
    invoice_id: uuid.UUID,
    question_id: uuid.UUID,
    body: QuestionSend,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Explicitly send this question (and the selected documents) to the job's assigned
    contractor. Refused for a standalone invoice (409 ``standalone_invoice``) or a job with
    no accepted contractor (409 ``no_assigned_contractor``). Repeating a send changes nothing."""
    key = _require_key(idempotency_key)
    q, _sent = await svc.send_question(
        db,
        user_id,
        invoice_id,
        question_id,
        expected_version=body.expected_version,
        asset_ids=body.asset_ids,
        idempotency_key=key,
    )
    responses = await svc.responses_for(db, [q.id])
    return svc.question_view(q, responses[q.id], user_id)


# ============================================================================ contractor
@router.get("/service-jobs/{job_id}/invoice-questions", response_model=list[SharedInvoiceQuestionOut])
async def contractor_questions(
    job_id: uuid.UUID, user_id: CurrentUserId, db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict]:
    """Invoice questions the owner sent to your organization's assignment on this job."""
    rows = await svc.shared_questions(db, user_id, job_id)
    return [await svc.shared_view(db, q, inv) for q, inv in rows]


@router.get("/service-jobs/{job_id}/invoice-questions/{question_id}", response_model=SharedInvoiceQuestionOut)
async def contractor_question(
    job_id: uuid.UUID,
    question_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    _actor, q, invoice = await svc.shared_question(db, user_id, job_id, question_id)
    return await svc.shared_view(db, q, invoice)


@router.get(
    "/service-jobs/{job_id}/invoice-questions/{question_id}/assets/{asset_id}/download-url",
    response_model=SignedUrlOut,
)
async def contractor_shared_asset(
    job_id: uuid.UUID,
    question_id: uuid.UUID,
    asset_id: uuid.UUID,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """A short-lived download link for a document the owner shared with this question."""
    return await svc.shared_asset_url(db, user_id, job_id, question_id, asset_id)


@router.post(
    "/service-jobs/{job_id}/invoice-questions/{question_id}/respond",
    response_model=SharedInvoiceQuestionOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": SharedInvoiceQuestionOut, "description": "Identical response already recorded"}},
    dependencies=[Depends(mutation_limit())],
)
async def contractor_respond(
    job_id: uuid.UUID,
    question_id: uuid.UUID,
    body: ContractorResponseCreate,
    response: Response,
    user_id: CurrentUserId,
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict:
    """Answer the question (attributed to you and your organization), optionally attaching a
    corrected invoice you uploaded for this job — it becomes a new revision; the original
    document, its extraction and the owner's corrections are never overwritten."""
    _resp, created = await svc.respond(
        db, user_id, job_id, question_id, text=body.text, corrected_asset_id=body.corrected_asset_id
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    _actor, q, invoice = await svc.shared_question(db, user_id, job_id, question_id)
    return await svc.shared_view(db, q, invoice)
