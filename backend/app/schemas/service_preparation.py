"""Observations, measurements, preparation items, briefs and scope (service jobs, workstream B).

Decimal values (measurement values, quantities) are strings exactly as stored, never
floats; money is integer minor units with a currency code.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from app.models.service_jobs import MEASUREMENT_DIMENSIONS
from app.schemas.common import APIModel, StrictInput

Dimension = Literal[MEASUREMENT_DIMENSIONS]  # type: ignore[valid-type]
MeasurementMethod = Literal[
    "marking_read",
    "owner_tape",
    "owner_caliper",
    "owner_other",
    "image_estimate_with_reference",
    "contractor_site",
    "source_document",
]
EvidenceCategory = Literal[
    "overview",
    "access_route",
    "label",
    "close_up",
    "connections",
    "route",
    "markings",
    "measurement",
    "document",
    "other",
]


class Region(StrictInput):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


# ---------------------------------------------------------------------- analysis
class AnalysisRequest(StrictInput):
    asset_ids: list[uuid.UUID] | None = Field(default=None, max_length=40)


class AnalysisRunResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID | None
    kind: str
    status: str
    provider: str | None
    model: str | None
    job_revision: int | None
    asset_ids: list[uuid.UUID]
    observation_count: int
    superseded_reason: str | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime


class AnalysisStatusResponse(APIModel):
    available: bool
    provider: str
    message: str | None
    substitute: bool
    runs: list[AnalysisRunResponse]


# ---------------------------------------------------------------------- observations
class ObservationResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    asset_id: uuid.UUID | None
    page: int | None
    region: dict | None
    kind: str
    assertion: str
    extracted_text: str | None
    state: str
    confidence: float | None
    uncertainty: str | None
    origin: Literal["model", "owner", "contractor", "assistant"]
    analysis_run_id: uuid.UUID | None
    model_version: str | None
    recorded_by: uuid.UUID | None
    supersedes_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None
    job_revision: int
    is_measurement: bool = False
    created_at: datetime


class ObservationNote(StrictInput):
    text: str = Field(min_length=1, max_length=2000)
    asset_id: uuid.UUID | None = None
    page: int | None = Field(default=None, ge=1, le=500)
    region: Region | None = None


class ObservationCorrection(StrictInput):
    assertion: str = Field(min_length=1, max_length=2000)
    extracted_text: str | None = Field(default=None, max_length=300)
    page: int | None = Field(default=None, ge=1, le=500)
    region: Region | None = None


class NoteBody(StrictInput):
    note: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------------- measurements
class MeasurementCreate(StrictInput):
    dimension: Dimension
    component: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=60, description='As written: "25", "1 1/4", "20-32", "M10x1.25"')
    unit: Literal["mm", "cm", "m", "in", "ft"] | None = None
    precision: str | None = Field(default=None, max_length=100, description='e.g. "±1 mm"; required for estimates')
    method: MeasurementMethod
    tool: str | None = Field(default=None, max_length=100)
    reference: str | None = Field(default=None, max_length=200, description="Scale reference for photo estimates")
    source_asset_id: uuid.UUID | None = None
    source_region: Region | None = None
    source_observation_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class MeasurementConfirm(StrictInput):
    method: Literal["contractor_site", "marking_read", "source_document"]
    note: str | None = Field(default=None, max_length=1000)


class Provenance(APIModel):
    badge: str
    label: str
    recorded_by: uuid.UUID | None
    recorded_by_role: str
    method: str
    # Recorded/confirmed by another contractor organization (identities withheld).
    other_organization: bool = False


class Confirmation(APIModel):
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    method: str | None


class ThreadParts(APIModel):
    standard: str | None
    size: str | None
    pitch: str | None


class MeasurementResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    dimension: str
    component: str
    value_text: str | None
    value_min: str | None
    value_max: str | None
    unit: str | None
    normalized_min_mm: str | None
    normalized_max_mm: str | None
    resolution_mm: str | None
    precision: str | None
    method: str
    tool: str | None
    reference: str | None
    thread: ThreadParts | None
    source_asset_id: uuid.UUID | None
    source_region: dict | None
    source_observation_id: uuid.UUID | None
    state: str
    provenance: Provenance
    recorded_by: uuid.UUID | None
    recorded_by_other_organization: bool = False
    confirmation: Confirmation | None
    supersedes_id: uuid.UUID | None
    superseded_by_id: uuid.UUID | None
    is_current: bool
    job_revision: int
    notes: str | None
    created_at: datetime


# ---------------------------------------------------------------------- preparation
class DimensionCheck(APIModel):
    status: Literal["not_applicable", "unknown", "range_includes_recorded_od", "range_excludes_recorded_od"]
    reason: str | None


class CatalogueCandidate(APIModel):
    product_id: uuid.UUID
    sku: str
    name: str
    brand: str | None
    price_cents: int
    sale_price_cents: int | None
    currency: str
    is_active: bool
    in_stock: bool
    fitment_status: str
    fitment_message: str
    dimension_check: DimensionCheck


class ItemDependency(APIModel):
    measurement_id: uuid.UUID
    dimension: str | None
    value_text: str | None
    unit: str | None
    state: str


class PreparationItemResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    category: Literal["part", "consumable", "tool"]
    name: str
    purpose: str
    quantity: str | None
    unit: str | None
    quantity_basis: str | None
    open_requirements: list[str]
    specification: dict[str, Any]
    depends_on: list[ItemDependency]
    supporting_asset_ids: list[uuid.UUID]
    source_note: str | None
    origin: Literal["assistant", "owner", "contractor"]
    created_by_role: str
    status: Literal["suggested", "needs_evidence", "contractor_confirmed", "rejected", "replaced", "superseded"]
    requirement_state: str
    catalogue_match: Literal["none", "candidates", "confirmed"]
    candidates: list[CatalogueCandidate]
    confirmed_product: CatalogueCandidate | None
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    confirmed_job_revision: int | None
    evidence_changed_since_confirmation: bool
    replaced_by_id: uuid.UUID | None
    evidence_request_ids: list[uuid.UUID]
    job_revision: int
    version: int
    commercial_note: str
    created_at: datetime
    updated_at: datetime


class PreparationItemCreate(StrictInput):
    category: Literal["part", "consumable", "tool"]
    name: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2000)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    unit: str | None = Field(default=None, max_length=30)
    quantity_basis: str | None = Field(default=None, max_length=500)
    open_requirements: list[str] = Field(default_factory=list, max_length=30)
    specification: dict[str, Any] = Field(default_factory=dict)
    depends_on_measurement_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    supporting_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=40)
    source_note: str | None = Field(default=None, max_length=1000)


class ItemReplace(PreparationItemCreate):
    expected_version: int | None = None


class ItemConfirm(StrictInput):
    expected_version: int | None = None
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    unit: str | None = Field(default=None, max_length=30)
    quantity_basis: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=1000)


class ItemReject(StrictInput):
    expected_version: int | None = None
    note: str | None = Field(default=None, max_length=1000)


class EvidenceAsk(StrictInput):
    category: EvidenceCategory
    prompt: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    component: str | None = Field(default=None, max_length=200)
    measurement_dimension: Dimension | None = None
    priority: Literal["high", "normal", "low"] = "normal"


class ItemEvidenceRequest(StrictInput):
    expected_version: int | None = None
    category: EvidenceCategory
    prompt: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    measurement_dimension: Dimension | None = None
    priority: Literal["high", "normal", "low"] = "normal"


class CatalogueMatch(StrictInput):
    product_id: uuid.UUID
    expected_version: int | None = None


class EvidenceRequestRef(APIModel):
    id: uuid.UUID
    category: str
    prompt: str
    reason: str
    requester_role: str
    status: str
    priority: str


class ItemEvidenceResponse(APIModel):
    item: PreparationItemResponse
    evidence_request: EvidenceRequestRef


# ---------------------------------------------------------------------- briefs
class BriefAcknowledgementResponse(APIModel):
    id: uuid.UUID
    kind: str
    note: str | None
    user_id: uuid.UUID
    organization_id: uuid.UUID
    created_at: datetime


class BriefResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    revision_number: int
    status: Literal["preview", "published", "superseded"]
    sections: list[str]
    recipient: dict | None
    content: dict | None
    job_revision: int
    current_job_revision: int
    content_digest: str
    created_by: uuid.UUID
    created_at: datetime
    published_at: datetime | None
    is_current: bool
    outdated: bool
    outdated_reasons: list[str]
    acknowledgements: list[BriefAcknowledgementResponse]


class BriefPublish(StrictInput):
    content_digest: str | None = Field(default=None, min_length=64, max_length=64)


class BriefAcknowledge(StrictInput):
    kind: Literal["reviewed", "incomplete", "limitations_acknowledged", "confirmed"]
    note: str | None = Field(default=None, max_length=2000)
    requested_view: EvidenceAsk | None = None


class BriefAcknowledgeResponse(APIModel):
    acknowledgement: BriefAcknowledgementResponse
    evidence_request: EvidenceRequestRef | None


# ---------------------------------------------------------------------- scope
class ScopeTask(StrictInput):
    description: str = Field(min_length=1, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)
    needs_site_inspection: bool = False


class EstimateLine(StrictInput):
    description: str = Field(min_length=1, max_length=500)
    kind: Literal["labour", "parts", "travel", "call_out", "consumables", "other"] = "other"
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    unit: str | None = Field(default=None, max_length=30)
    unit_price_minor: int | None = Field(default=None, ge=0)
    amount_minor: int | None = Field(default=None, ge=0)


class ScopeCreate(StrictInput):
    summary: str = Field(min_length=1, max_length=4000)
    tasks: list[ScopeTask] = Field(default_factory=list, max_length=100)
    estimate_lines: list[EstimateLine] = Field(default_factory=list, max_length=200)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    exclusions: str | None = Field(default=None, max_length=4000)
    assumptions: str | None = Field(default=None, max_length=4000)
    supersedes_id: uuid.UUID | None = None


class ScopeDecisionCreate(StrictInput):
    decision: Literal["accepted", "rejected", "change_requested"]
    revision_digest: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class ScopeDecisionResponse(APIModel):
    id: uuid.UUID
    scope_revision_id: uuid.UUID
    decision: str
    revision_digest: str
    decided_by: uuid.UUID
    note: str | None
    decided_at: datetime


class EstimateLineResponse(APIModel):
    description: str
    kind: str
    quantity: str | None
    unit: str | None
    unit_price_minor: int | None
    amount_minor: int


class ScopeResponse(APIModel):
    id: uuid.UUID
    job_id: uuid.UUID
    revision_number: int
    is_change: bool
    supersedes_id: uuid.UUID | None
    proposed_by: uuid.UUID
    organization_id: uuid.UUID | None
    summary: str
    tasks: list[dict[str, Any]]
    estimate_lines: list[EstimateLineResponse]
    estimate_total_minor: int | None
    currency: str | None
    exclusions: str | None
    assumptions: str | None
    status: str
    content_digest: str
    is_current: bool
    decision: ScopeDecisionResponse | None
    created_at: datetime
