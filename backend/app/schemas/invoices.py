"""Understand my invoice — API contracts.

Money and quantities are exact decimal **strings** in the invoice's stated currency (never
floats; up to 4 decimal places, e.g. ``"237.50"``, ``"-20.00"``, ``"1200"`` for JPY). A
``null`` value means not printed / not known — it is never filled in. Regions are
normalised page boxes ``{x, y, w, h}`` in 0–1 from the top-left corner.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints

from app.schemas.common import APIModel, StrictInput

LineKind = Literal["part", "labour", "travel", "call_out", "consumable", "discount", "fee", "tax", "other", "unknown"]
Certainty = Literal["high", "medium", "low", "unknown"]
AmountStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^-?\d{1,10}(\.\d{1,4})?$")]
CurrencyStr = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z]{3}$")]


# ----------------------------------------------------------------------------- inputs
class InvoiceCreate(StrictInput):
    asset_id: uuid.UUID | None = Field(
        None, description="An available upload with purpose 'invoice' that you uploaded; omit for manual entry"
    )
    job_id: uuid.UUID | None = Field(None, description="Your own service job; omit for a standalone invoice")
    title: str = Field("Invoice", min_length=1, max_length=200)


class FieldCorrections(StrictInput):
    """Only the fields present are changed; ``null`` records "not on the invoice"."""

    expected_version: int = Field(..., description="The current revision's version")
    supplier_name: str | None = Field(None, max_length=300)
    invoice_number: str | None = Field(None, max_length=100)
    invoice_date: str | None = Field(None, max_length=40)
    currency: CurrencyStr | None = None
    subtotal: AmountStr | None = None
    tax_printed: AmountStr | None = None
    total: AmountStr | None = None
    warranty: str | None = Field(None, max_length=2000)
    follow_up: str | None = Field(None, max_length=2000)

    def changes(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "expected_version"}


class _LineValues(StrictInput):
    kind: LineKind | None = None
    description: str | None = Field(None, max_length=500)
    part_number: str | None = Field(None, max_length=80)
    quantity: AmountStr | None = None
    unit: str | None = Field(None, max_length=20)
    unit_price: AmountStr | None = None
    line_total: AmountStr | None = None
    tax_printed: AmountStr | None = None
    currency: CurrencyStr | None = None

    def changes(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.model_fields_set if k != "expected_version"}


class LineCorrection(_LineValues):
    """Only the fields present are changed. Sending a line unchanged confirms it as printed."""

    expected_version: int = Field(..., description="The line's version")


class LineCreate(_LineValues):
    expected_version: int = Field(..., description="The current revision's version")


class ReviewRequest(StrictInput):
    expected_version: int = Field(..., description="The current revision's version")
    confirm: list[str] = Field(
        default_factory=list,
        description="Low-certainty items confirmed as printed: 'field:<name>' or 'line:<line id>'",
    )


class QuestionCreate(StrictInput):
    text: str = Field(..., min_length=1, max_length=2000)
    line_id: uuid.UUID | None = None
    suggestion_key: str | None = Field(None, max_length=300, description="Key of the suggested question it came from")


class QuestionUpdate(StrictInput):
    expected_version: int
    text: str | None = Field(None, min_length=1, max_length=2000)
    line_id: uuid.UUID | None = None

    def changes(self) -> dict[str, Any]:
        out = {k: getattr(self, k) for k in self.model_fields_set if k in ("text", "line_id")}
        if out.get("text", "") is None:
            out.pop("text")
        return out


class QuestionSend(StrictInput):
    expected_version: int
    asset_ids: list[uuid.UUID] = Field(
        default_factory=list, description="Supporting documents of this invoice or its job to share with the question"
    )


class ContractorResponseCreate(StrictInput):
    text: str = Field(..., min_length=1, max_length=4000)
    corrected_asset_id: uuid.UUID | None = Field(
        None, description="An available job document/invoice upload you made for this job: a corrected invoice"
    )


# ----------------------------------------------------------------------------- outputs
class Region(APIModel):
    x: float
    y: float
    w: float
    h: float


class FieldHistoryEntry(APIModel):
    value: str | None = None
    source: str | None = None
    by: str | None = None
    at: str | None = None


class InvoiceFieldOut(APIModel):
    name: str
    value: str | None
    source: Literal["extracted", "owner_corrected", "owner_confirmed", "owner_entered", "not_extracted"]
    certainty: Certainty
    page: int | None
    region: Region | None
    illegible: bool
    needs_confirmation: bool
    extracted_value: str | None
    by: str | None
    at: str | None
    history: list[FieldHistoryEntry]


class InvoiceLineOut(APIModel):
    id: uuid.UUID
    line_number: int
    kind: LineKind
    kind_certainty: str | None
    description: str | None
    part_number: str | None
    quantity: str | None
    unit: str | None
    unit_price: str | None
    line_total: str | None
    tax_printed: str | None
    currency: str | None
    page: int | None
    region: Region | None
    certainty: Certainty
    source: Literal["extracted", "owner_corrected", "owner_confirmed", "owner_entered"]
    needs_confirmation: bool
    illegible: list[str]
    extracted_values: dict[str, str | None] | None
    corrected_fields: list[str]
    corrected_by: uuid.UUID | None
    corrected_at: datetime | None
    version: int


class UnparsedText(APIModel):
    text: str | None
    page: int | None
    region: Region | None


class InvoiceRevisionBrief(APIModel):
    id: uuid.UUID
    revision_number: int
    origin: Literal["owner_upload", "contractor_correction", "manual_entry"]
    status: Literal["uploaded", "extraction_draft", "owner_reviewed", "superseded"]
    source_asset_id: uuid.UUID | None
    uploaded_by: uuid.UUID
    organization_id: uuid.UUID | None
    supersedes_id: uuid.UUID | None
    created_at: datetime


class InvoiceRevisionOut(InvoiceRevisionBrief):
    currency: str | None
    rounding: str
    version: int
    extraction_status: Literal["none", "extracted", "unreadable"]
    extraction_provider: str | None
    extraction_notes: list[str]
    unparsed_text: list[UnparsedText]
    reviewed_by: str | None
    reviewed_at: str | None
    fields: dict[str, InvoiceFieldOut]


class ExtractionRunOut(APIModel):
    id: uuid.UUID
    status: Literal["pending", "running", "draft_ready", "confirmed", "superseded", "failed", "cancelled"]
    invoice_revision_id: uuid.UUID | None
    provider: str | None
    model: str | None
    attempts: int
    error: str | None
    stale_reason: str | None
    created_at: datetime
    updated_at: datetime


class ExtractionStatusOut(APIModel):
    provider: str
    available: bool
    message: str | None
    substitute: bool
    latest_run: ExtractionRunOut | None


class InvoiceExplanationOut(APIModel):
    id: uuid.UUID
    invoice_revision_id: uuid.UUID
    status: Literal["current", "superseded"]
    basis_digest: str
    stale: bool
    created_at: datetime
    content: dict[str, Any]


class QuestionResponseOut(APIModel):
    id: uuid.UUID
    question_id: uuid.UUID
    author_id: uuid.UUID
    author_role: Literal["owner", "contractor"]
    organization_id: uuid.UUID | None
    text: str
    corrected_revision_id: uuid.UUID | None
    created_at: datetime


class InvoiceQuestionOut(APIModel):
    id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_revision_id: uuid.UUID
    line_id: uuid.UUID | None
    origin: str
    text: str
    status: Literal["draft", "shared", "answered", "closed"]
    shared_assignment_id: uuid.UUID | None
    shared_asset_ids: list[str]
    shared_at: datetime | None
    created_by: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime
    responses: list[QuestionResponseOut]


class InvoiceSummaryOut(APIModel):
    id: uuid.UUID
    title: str
    job_id: uuid.UUID | None
    standalone: bool
    status: Literal["uploaded", "extraction_draft", "owner_reviewed", "superseded", "deleted"]
    version: int
    current_revision_id: uuid.UUID | None
    revision_number: int | None
    supplier_name: str | None
    total: str | None
    currency: str | None
    created_at: datetime
    updated_at: datetime


class InvoiceDetailOut(InvoiceSummaryOut):
    provisional: bool
    needs_confirmation: list[str]
    revision: InvoiceRevisionOut
    revisions: list[InvoiceRevisionBrief]
    lines: list[InvoiceLineOut]
    explanation: InvoiceExplanationOut | None
    questions: list[InvoiceQuestionOut]
    extraction: ExtractionStatusOut


class SharedLineOut(APIModel):
    line_number: int
    kind: LineKind
    description: str | None
    part_number: str | None
    quantity: str | None
    unit: str | None
    unit_price: str | None
    line_total: str | None
    currency: str | None
    page: int | None


class SharedAssetOut(APIModel):
    id: uuid.UUID
    purpose: str
    detected_type: str | None
    pages: int | None
    size_bytes: int | None


class SharedInvoiceQuestionOut(APIModel):
    """What the assigned contractor sees: the sent question and the selected documents only."""

    id: uuid.UUID
    job_id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_title: str
    invoice_revision_id: uuid.UUID
    invoice_revision_number: int | None
    text: str
    status: Literal["shared", "answered"]
    shared_at: datetime | None
    version: int
    line: SharedLineOut | None
    shared_assets: list[SharedAssetOut]
    responses: list[QuestionResponseOut]


class SignedUrlOut(APIModel):
    url: str
    expires_in: int
    content_type: str
