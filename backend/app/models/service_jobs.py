"""Service jobs: guided evidence, contractor preparation, invoices and reciprocal feedback.

Domain contract: docs/04_technical_spec/Service_Jobs_and_Contractor_Assistant_Specification.md
(decisions SJ-D1… in the Repair Programme §8). Every row is owned by exactly one job (or,
for a standalone invoice, one owner); composite foreign keys keep children on the job of
their parent so a crafted id can never attach evidence, items or decisions across jobs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, created_at_col, updated_at_col, uuid_pk

# Shared vocabularies --------------------------------------------------------------
ASSERTION_STATES = (
    "model_suggested",
    "owner_declared",
    "owner_measured",
    "contractor_confirmed",
    "source_verified",
    "rejected",
    "superseded",
    "unknown",
)
JOB_STATUSES = (
    "draft",
    "evidence_collection",
    "contractor_review",
    "preparation_ready",
    "scheduled",
    "attended",
    "completed",
    "archived",
    "cancelled",
)
# Sections an owner can share with an assigned organization (SJ-06).
JOB_SECTIONS = (
    "summary",  # title, symptoms, history, vessel/equipment identity
    "evidence",  # photos/documents, observations, evidence requests
    "measurements",
    "preparation",  # preparation items, briefs
    "access_general",  # marina/berth area, hours, parking, power/water, hazards
    "access_restricted",  # gate codes, key handover, contacts, exact location
    "scope",  # scope revisions and decisions
    "invoices",  # only invoices/questions the owner explicitly shares
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ",".join(f"'{v}'" for v in values) + ")"


def _fk_user(nullable: bool = False, ondelete: str = "RESTRICT"):
    return mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete=ondelete), nullable=nullable, index=True)


# Organizations ----------------------------------------------------------------------
class ContractorOrganization(Base):
    __tablename__ = "contractor_organizations"
    __table_args__ = (CheckConstraint(_in("status", ("active", "suspended")), name="valid_status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String, nullable=True)
    nzbn: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    # Provisioned by an audited admin/CLI action; a directory entry alone grants nothing.
    created_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class ContractorMembership(Base):
    __tablename__ = "contractor_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_contractor_memberships_org_user"),
        CheckConstraint(_in("role", ("member", "admin")), name="valid_role"),
        CheckConstraint(_in("status", ("active", "removed")), name="valid_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = _fk_user(ondelete="CASCADE")
    role: Mapped[str] = mapped_column(String, nullable=False, default="member", server_default="member")
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    verified_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


# Jobs ----------------------------------------------------------------------------
class ServiceJob(Base):
    __tablename__ = "service_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="valid_status"),
        CheckConstraint(_in("urgency", ("routine", "soon", "urgent", "unknown")), name="valid_urgency"),
        CheckConstraint("version >= 1 AND evidence_revision >= 0", name="versions_positive"),
        UniqueConstraint("id", "owner_id", name="uq_service_jobs_id_owner"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = _fk_user(ondelete="CASCADE")
    vessel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vessels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    entry_point: Mapped[str] = mapped_column(String, nullable=False, default="vessel", server_default="vessel")
    title: Mapped[str] = mapped_column(String, nullable=False)
    issue_description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    affected_system: Mapped[str | None] = mapped_column(String, nullable=True)
    affected_equipment: Mapped[str | None] = mapped_column(String, nullable=True)
    occurs_when: Mapped[str | None] = mapped_column(Text, nullable=True)
    already_tried: Mapped[str | None] = mapped_column(Text, nullable=True)
    urgency: Mapped[str] = mapped_column(String, nullable=False, default="unknown", server_default="unknown")
    # Owner-confirmed vessel/equipment context at job creation (corrections are explicit).
    vessel_context: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", server_default="draft", index=True)
    disputed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # Optimistic concurrency for job edits/transitions (409 on mismatch).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Bumped whenever supporting material changes; binds analysis, briefs and confirmations.
    evidence_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retention_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


def _job_fk(ondelete: str = "CASCADE"):
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("service_jobs.id", ondelete=ondelete), nullable=False, index=True
    )


class JobAccessDetails(Base):
    """Logistics (general) and access credentials (restricted) — separate sections."""

    __tablename__ = "service_job_access"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    # access_general: marina/berth area, rendezvous, parking/loading, hours, owner
    # attendance, locker/panel access, obstructions, power/water, known hazards.
    general: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # access_restricted: gate code, key handover, contact name/phone, exact location.
    restricted: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    updated_at: Mapped[datetime] = updated_at_col()


class JobAssignment(Base):
    """Explicit owner grant of selected sections to one contractor organization."""

    __tablename__ = "service_job_assignments"
    __table_args__ = (
        CheckConstraint(_in("status", ("invited", "accepted", "declined", "revoked")), name="valid_status"),
        UniqueConstraint("id", "job_id", name="uq_service_job_assignments_id_job"),
        # At most one live (invited/accepted) assignment per job.
        Index(
            "uq_service_job_assignments_live",
            "job_id",
            unique=True,
            postgresql_where=text("status IN ('invited','accepted')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="invited", server_default="invited")
    sections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # Owner opt-in: contractor sees live updates after the shared brief, not only the snapshot.
    live_updates: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    shared_brief_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    invited_by: Mapped[uuid.UUID] = _fk_user()
    accepted_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class JobAssignmentMember(Base):
    """Members of the organization assigned to work the job (org admins manage these)."""

    __tablename__ = "service_job_assignment_members"
    __table_args__ = (UniqueConstraint("assignment_id", "user_id", name="uq_service_job_assignment_members"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_job_assignments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = _fk_user(ondelete="CASCADE")
    # Only these members may see access_restricted, even within the organization.
    restricted_access: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    added_by: Mapped[uuid.UUID] = _fk_user()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class EvidenceRequest(Base):
    __tablename__ = "service_job_evidence_requests"
    __table_args__ = (
        CheckConstraint(
            _in(
                "category",
                (
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
                ),
            ),
            name="valid_category",
        ),
        CheckConstraint(_in("requester_role", ("assistant", "owner", "contractor")), name="valid_requester_role"),
        CheckConstraint(_in("status", ("outstanding", "answered", "unavailable", "waived")), name="valid_status"),
        CheckConstraint(_in("priority", ("high", "normal", "low")), name="valid_priority"),
        UniqueConstraint("id", "job_id", name="uq_service_job_evidence_requests_id_job"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    requested_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    requester_role: Mapped[str] = mapped_column(String, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[str] = mapped_column(String, nullable=False)
    component: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    measurement_dimension: Mapped[str | None] = mapped_column(String, nullable=True)
    priority: Mapped[str] = mapped_column(String, nullable=False, default="normal", server_default="normal")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="outstanding", server_default="outstanding", index=True
    )
    # cannot_safely_access | not_visible | not_available | other
    unavailable_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    technician_inspection_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    answer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


# Media ----------------------------------------------------------------------------
class EvidenceAsset(Base):
    """A private uploaded file. Job evidence (``job_id``) or a standalone invoice document
    (``job_id`` null, ``owner_id`` set). Originals stay private; shared views use the
    metadata-stripped derivative."""

    __tablename__ = "service_assets"
    __table_args__ = (
        CheckConstraint(_in("purpose", ("job_photo", "job_document", "invoice")), name="valid_purpose"),
        CheckConstraint(
            _in("status", ("upload_pending", "quarantined", "processing", "available", "rejected", "deleted")),
            name="valid_status",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_nonneg"),
        UniqueConstraint("id", "job_id", name="uq_service_assets_id_job"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_service_assets_owner_idem"),
        ForeignKeyConstraint(
            ["evidence_request_id", "job_id"],
            ["service_job_evidence_requests.id", "service_job_evidence_requests.job_id"],
            name="fk_service_assets_request_same_job",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = _fk_user(ondelete="CASCADE")  # the job owner / invoice owner
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = _fk_user()
    uploader_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="SET NULL"), nullable=True
    )
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    evidence_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    declared_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    declared_content_type: Mapped[str | None] = mapped_column(String, nullable=True)
    max_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Opaque random keys (never derived from user input); never exposed by the API.
    storage_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    derivative_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    detected_type: Mapped[str | None] = mapped_column(String, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="upload_pending", server_default="upload_pending", index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    scan_result: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # Capture-quality hints: {"blur": "ok"|"blurry"|"not_assessed", "dark": …, …}
    quality: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # Worker claim/lease/fencing (processing never holds a DB lock across scanner/storage).
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AnalysisRun(Base):
    """One background analysis bound to exact inputs; published only if still current."""

    __tablename__ = "service_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            _in("kind", ("capture_quality", "evidence_observations", "invoice_extraction", "invoice_explanation")),
            name="valid_kind",
        ),
        CheckConstraint(
            _in("status", ("pending", "running", "draft_ready", "confirmed", "superseded", "failed", "cancelled")),
            name="valid_status",
        ),
        CheckConstraint("(job_id IS NOT NULL) OR (invoice_id IS NOT NULL)", name="has_subject"),
        UniqueConstraint("requested_by", "idempotency_key", name="uq_service_analysis_runs_idem"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_jobs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    requested_by: Mapped[uuid.UUID] = _fk_user()
    # Exact inputs: job evidence_revision, {asset_id: version}, invoice revision, grant.
    job_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    invoice_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    config_version: Mapped[str | None] = mapped_column(String, nullable=True)
    input_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", server_default="pending", index=True)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


# Observations, measurements and preparation ------------------------------------------
class Observation(Base):
    __tablename__ = "service_observations"
    __table_args__ = (
        CheckConstraint(_in("state", ASSERTION_STATES), name="valid_state"),
        CheckConstraint(
            _in("kind", ("marking_text", "label_text", "visible_feature", "quality", "owner_note", "contractor_note")),
            name="valid_kind",
        ),
        ForeignKeyConstraint(
            ["asset_id", "job_id"], ["service_assets.id", "service_assets.job_id"], name="fk_service_obs_asset_same_job"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Normalised 0–1 region on the (orientation-corrected) derivative: {x, y, w, h}.
    region: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    # "Image text appears to read 25 mm ID" — never a measured dimension by itself.
    assertion: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_observations.id", ondelete="SET NULL"), nullable=True
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


MEASUREMENT_DIMENSIONS = (
    "hose_internal_diameter",
    "hose_external_diameter",
    "fitting_outside_diameter",
    "thread",
    "clamp_range",
    "route_length",
    "bend_radius",
    "clearance",
    "other",
)


class Measurement(Base):
    __tablename__ = "service_measurements"
    __table_args__ = (
        CheckConstraint(_in("state", ASSERTION_STATES), name="valid_state"),
        CheckConstraint(_in("dimension", MEASUREMENT_DIMENSIONS), name="valid_dimension"),
        CheckConstraint(
            _in(
                "method",
                (
                    "marking_read",
                    "owner_tape",
                    "owner_caliper",
                    "owner_other",
                    "image_estimate_with_reference",
                    "contractor_site",
                    "source_document",
                    "unknown",
                ),
            ),
            name="valid_method",
        ),
        CheckConstraint("value_min IS NULL OR value_max IS NULL OR value_min <= value_max", name="range_ordered"),
        ForeignKeyConstraint(
            ["source_asset_id", "job_id"],
            ["service_assets.id", "service_assets.job_id"],
            name="fk_service_measurements_asset_same_job",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    dimension: Mapped[str] = mapped_column(String, nullable=False)
    component: Mapped[str] = mapped_column(String, nullable=False)
    # As written: "25", "1 1/4", "M10x1.25"; range as min/max in the original unit.
    value_text: Mapped[str | None] = mapped_column(String, nullable=True)
    value_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    value_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    # Central conversion for lengths only, never adding precision (see the service).
    normalized_min_mm: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    normalized_max_mm: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    precision: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "±1 mm", "nearest 5 mm"
    method: Mapped[str] = mapped_column(String, nullable=False)
    tool: Mapped[str | None] = mapped_column(String, nullable=True)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)  # scale reference for estimates
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_region: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_observations.id", ondelete="SET NULL"), nullable=True
    )
    state: Mapped[str] = mapped_column(String, nullable=False)
    recorded_by: Mapped[uuid.UUID] = _fk_user()
    confirmed_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmation_method: Mapped[str | None] = mapped_column(String, nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_measurements.id", ondelete="SET NULL"), nullable=True
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class PreparationItem(Base):
    __tablename__ = "service_preparation_items"
    __table_args__ = (
        CheckConstraint(_in("category", ("part", "consumable", "tool")), name="valid_category"),
        CheckConstraint(_in("origin", ("assistant", "owner", "contractor")), name="valid_origin"),
        CheckConstraint(
            _in(
                "status",
                ("suggested", "needs_evidence", "contractor_confirmed", "rejected", "replaced", "superseded"),
            ),
            name="valid_status",
        ),
        CheckConstraint(_in("catalogue_match", ("none", "candidates", "confirmed")), name="valid_catalogue_match"),
        CheckConstraint("quantity IS NULL OR quantity > 0", name="quantity_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    category: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)  # generic requirement, e.g. "sanitation hose"
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)  # null = unknown
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity_basis: Mapped[str | None] = mapped_column(Text, nullable=True)  # assumption/allowance, author
    # Requirements still needed: ["internal diameter", "application rating", …]
    open_requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    specification: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    depends_on_measurement_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    supporting_asset_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_product_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    catalogue_match: Mapped[str] = mapped_column(String, nullable=False, default="none", server_default="none")
    confirmed_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="suggested", server_default="suggested")
    created_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    confirmed_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_job_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_preparation_items.id", ondelete="SET NULL"), nullable=True
    )
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class PreparationBrief(Base):
    """Immutable shared revision of the contractor brief (``content`` is a snapshot)."""

    __tablename__ = "service_briefs"
    __table_args__ = (
        UniqueConstraint("job_id", "revision_number", name="uq_service_briefs_job_revision"),
        CheckConstraint(_in("status", ("preview", "published", "superseded")), name="valid_status"),
        UniqueConstraint("id", "job_id", name="uq_service_briefs_id_job"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="preview", server_default="preview")
    sections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    job_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[uuid.UUID] = _fk_user()
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class BriefAcknowledgement(Base):
    __tablename__ = "service_brief_acknowledgements"
    __table_args__ = (
        CheckConstraint(
            _in("kind", ("reviewed", "incomplete", "limitations_acknowledged", "confirmed")), name="valid_kind"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    brief_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_briefs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = _fk_user()
    kind: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class ScopeRevision(Base):
    __tablename__ = "service_scope_revisions"
    __table_args__ = (
        UniqueConstraint("job_id", "revision_number", name="uq_service_scope_job_revision"),
        CheckConstraint(
            _in("status", ("draft", "proposed", "accepted", "rejected", "change_requested", "superseded")),
            name="valid_status",
        ),
        CheckConstraint("estimate_total_minor IS NULL OR estimate_total_minor >= 0", name="estimate_nonneg"),
        UniqueConstraint("id", "job_id", name="uq_service_scope_revisions_id_job"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_scope_revisions.id", ondelete="SET NULL"), nullable=True
    )
    proposed_by: Mapped[uuid.UUID] = _fk_user()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    tasks: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # [{"description", "quantity", "unit", "unit_price_minor", "amount_minor", "kind"}]
    estimate_lines: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    estimate_total_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    exclusions: Mapped[str | None] = mapped_column(Text, nullable=True)
    assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="proposed", server_default="proposed")
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class ScopeDecision(Base):
    """Explicit owner (or delegated approver) decision on ONE exact scope revision."""

    __tablename__ = "service_scope_decisions"
    __table_args__ = (
        CheckConstraint(_in("decision", ("accepted", "rejected", "change_requested")), name="valid_decision"),
        UniqueConstraint("scope_revision_id", name="uq_service_scope_decisions_revision"),
        UniqueConstraint("decided_by", "idempotency_key", name="uq_service_scope_decisions_idem"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    scope_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_scope_revisions.id", ondelete="CASCADE"), nullable=False
    )
    # The decision binds the exact content the owner saw.
    revision_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    decided_by: Mapped[uuid.UUID] = _fk_user()
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime] = created_at_col()


class VisitEvent(Base):
    __tablename__ = "service_visit_events"
    __table_args__ = (
        CheckConstraint(
            _in("kind", ("scheduled", "attended", "completed", "cancelled", "completion_contested")),
            name="valid_kind",
        ),
        CheckConstraint(_in("actor_role", ("owner", "contractor", "admin", "system")), name="valid_actor_role"),
        ForeignKeyConstraint(
            ["assignment_id", "job_id"],
            ["service_job_assignments.id", "service_job_assignments.job_id"],
            name="fk_service_visit_assignment_same_job",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk()
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    actor_role: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    contests_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_visit_events.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    recorded_at: Mapped[datetime] = created_at_col()


# Invoices ---------------------------------------------------------------------------
class Invoice(Base):
    __tablename__ = "service_invoices"
    __table_args__ = (
        CheckConstraint(
            _in("status", ("uploaded", "extraction_draft", "owner_reviewed", "superseded", "deleted")),
            name="valid_status",
        ),
        # A linked job must belong to the invoice owner.
        ForeignKeyConstraint(
            ["job_id", "owner_id"],
            ["service_jobs.id", "service_jobs.owner_id"],
            name="fk_service_invoices_job_same_owner",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = _fk_user(ondelete="CASCADE")
    # Linked only to the owner's own job; a standalone invoice confers nothing (SJ-15).
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploaded", server_default="uploaded")
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class InvoiceRevision(Base):
    """One document revision (owner upload or contractor correction). The source document
    is never overwritten: ``extracted`` is immutable, corrections live in ``fields``."""

    __tablename__ = "service_invoice_revisions"
    __table_args__ = (
        UniqueConstraint("invoice_id", "revision_number", name="uq_service_invoice_revisions_number"),
        CheckConstraint(_in("origin", ("owner_upload", "contractor_correction", "manual_entry")), name="valid_origin"),
        CheckConstraint(
            _in("status", ("uploaded", "extraction_draft", "owner_reviewed", "superseded")), name="valid_status"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    source_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_assets.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_by: Mapped[uuid.UUID] = _fk_user()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="uploaded", server_default="uploaded")
    # {field: {"value", "page", "region", "certainty"}} as extracted (immutable)…
    extracted: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # …and as reviewed: {field: {"value", "source": "extracted"|"owner_corrected", "by", "at"}}
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    rounding: Mapped[str] = mapped_column(String, nullable=False, default="half_up", server_default="half_up")
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_revisions.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = created_at_col()


class InvoiceLine(Base):
    __tablename__ = "service_invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_revision_id", "line_number", name="uq_service_invoice_lines_number"),
        CheckConstraint(
            _in(
                "kind",
                ("part", "labour", "travel", "call_out", "consumable", "discount", "fee", "tax", "other", "unknown"),
            ),
            name="valid_kind",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="unknown", server_default="unknown")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_number: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)  # major units, exact
    line_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    tax_printed: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    certainty: Mapped[str] = mapped_column(String, nullable=False, default="unknown", server_default="unknown")
    extracted: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    corrected_by: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class InvoiceExplanation(Base):
    __tablename__ = "service_invoice_explanations"
    __table_args__ = (CheckConstraint(_in("status", ("current", "superseded")), name="valid_status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="current", server_default="current")
    # Digest of the reviewed fields/lines and compared scope it was computed from.
    basis_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = created_at_col()


class InvoiceQuestion(Base):
    __tablename__ = "service_invoice_questions"
    __table_args__ = (CheckConstraint(_in("status", ("draft", "shared", "answered", "closed")), name="valid_status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_revisions.id", ondelete="CASCADE"), nullable=False
    )
    line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_lines.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[str] = mapped_column(String, nullable=False, default="owner", server_default="owner")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", server_default="draft")
    shared_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_job_assignments.id", ondelete="SET NULL"), nullable=True
    )
    shared_asset_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = _fk_user()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class InvoiceQuestionResponse(Base):
    __tablename__ = "service_invoice_question_responses"

    id: Mapped[uuid.UUID] = uuid_pk()
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = _fk_user()
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_invoice_revisions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()


# Feedback and moderation --------------------------------------------------------------
class FeedbackWindow(Base):
    """Server-recorded eligibility event and the 14-day blind window for one job."""

    __tablename__ = "service_feedback_windows"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_job_assignments.id", ondelete="RESTRICT"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="RESTRICT"), nullable=False
    )
    owner_id: Mapped[uuid.UUID] = _fk_user()
    eligibility_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_visit_events.id", ondelete="RESTRICT"), nullable=False
    )
    # "attended_then_cancelled" restricts the applicable dimensions.
    basis: Mapped[str] = mapped_column(String, nullable=False)
    opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class JobFeedback(Base):
    __tablename__ = "service_feedback"
    __table_args__ = (
        CheckConstraint(_in("direction", ("owner_to_contractor", "contractor_to_owner")), name="valid_direction"),
        CheckConstraint(_in("status", ("draft", "submitted", "revealed", "withdrawn")), name="valid_status"),
        UniqueConstraint("job_id", "direction", name="uq_service_feedback_job_direction"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_feedback_windows.job_id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String, nullable=False)
    author_id: Mapped[uuid.UUID] = _fk_user()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contractor_organizations.id", ondelete="RESTRICT"), nullable=False
    )
    # {dimension: 1..5 | "not_applicable"}; missing answers are absent, never zero.
    ratings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft", server_default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    under_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class FeedbackVersion(Base):
    __tablename__ = "service_feedback_versions"
    __table_args__ = (UniqueConstraint("feedback_id", "version", name="uq_service_feedback_versions"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_feedback.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    ratings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class FeedbackResponse(Base):
    __tablename__ = "service_feedback_responses"
    __table_args__ = (CheckConstraint(_in("kind", ("response", "addendum", "correction_request")), name="valid_kind"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_feedback.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID] = _fk_user()
    kind: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    hidden_by_case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = created_at_col()


class ModerationCase(Base):
    __tablename__ = "service_moderation_cases"
    __table_args__ = (
        CheckConstraint(
            _in(
                "category",
                (
                    "factual_dispute",
                    "opinion",
                    "harassment",
                    "personal_or_security_information",
                    "completion_contested",
                    "other",
                ),
            ),
            name="valid_category",
        ),
        CheckConstraint(_in("status", ("open", "under_review", "resolved")), name="valid_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = _job_fk(ondelete="CASCADE")
    feedback_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_feedback.id", ondelete="CASCADE"), nullable=True, index=True
    )
    visit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_visit_events.id", ondelete="SET NULL"), nullable=True
    )
    reporter_id: Mapped[uuid.UUID] = _fk_user()
    category: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open", server_default="open", index=True)
    restrict_content: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    assigned_moderator_id: Mapped[uuid.UUID | None] = _fk_user(nullable=True, ondelete="SET NULL")
    disposition: Mapped[str | None] = mapped_column(String, nullable=True)
    disposition_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at_col()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModerationAction(Base):
    __tablename__ = "service_moderation_actions"

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("service_moderation_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID] = _fk_user()
    action: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = created_at_col()
