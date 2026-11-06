"""Service jobs: contractor organizations, explicit job grants, private evidence, measurements,
preparation briefs, scope decisions, visits, invoices and reciprocal feedback (SJ-01…SJ-24).

New tables only (plus the ``moderator`` role); no existing data is changed.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

ROLES_V1 = "role IN ('customer','operator','dispatcher','admin')"
ROLES_V2 = "role IN ('customer','operator','dispatcher','admin','moderator')"


def upgrade() -> None:
    op.drop_constraint("valid_role", "users", type_="check")
    op.create_check_constraint("valid_role", "users", ROLES_V2)
    op.create_table(
        "contractor_organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("trading_name", sa.String(), nullable=True),
        sa.Column("nzbn", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active','suspended')", name=op.f("ck_contractor_organizations_valid_status")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_contractor_organizations_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contractor_organizations")),
    )
    op.create_index(
        op.f("ix_contractor_organizations_created_by"), "contractor_organizations", ["created_by"], unique=False
    )
    op.create_table(
        "contractor_memberships",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(), server_default="member", nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('member','admin')", name=op.f("ck_contractor_memberships_valid_role")),
        sa.CheckConstraint("status IN ('active','removed')", name=op.f("ck_contractor_memberships_valid_status")),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_contractor_memberships_organization_id_contractor_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_contractor_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"], ["users.id"], name=op.f("fk_contractor_memberships_verified_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contractor_memberships")),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_contractor_memberships_org_user"),
    )
    op.create_index(
        op.f("ix_contractor_memberships_organization_id"), "contractor_memberships", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_contractor_memberships_user_id"), "contractor_memberships", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_contractor_memberships_verified_by"), "contractor_memberships", ["verified_by"], unique=False
    )
    op.create_table(
        "service_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("vessel_id", sa.UUID(), nullable=True),
        sa.Column("entry_point", sa.String(), server_default="vessel", nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("issue_description", sa.Text(), server_default="", nullable=False),
        sa.Column("affected_system", sa.String(), nullable=True),
        sa.Column("affected_equipment", sa.String(), nullable=True),
        sa.Column("occurs_when", sa.Text(), nullable=True),
        sa.Column("already_tried", sa.Text(), nullable=True),
        sa.Column("urgency", sa.String(), server_default="unknown", nullable=False),
        sa.Column("vessel_context", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        sa.Column("disputed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("evidence_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retention_hold", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','evidence_collection','contractor_review','preparation_ready','scheduled','attended','completed','archived','cancelled')",
            name=op.f("ck_service_jobs_valid_status"),
        ),
        sa.CheckConstraint(
            "urgency IN ('routine','soon','urgent','unknown')", name=op.f("ck_service_jobs_valid_urgency")
        ),
        sa.CheckConstraint("version >= 1 AND evidence_revision >= 0", name=op.f("ck_service_jobs_versions_positive")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_service_jobs_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["vessel_id"], ["vessels.id"], name=op.f("fk_service_jobs_vessel_id_vessels"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_jobs")),
        sa.UniqueConstraint("id", "owner_id", name="uq_service_jobs_id_owner"),
    )
    op.create_index(op.f("ix_service_jobs_owner_id"), "service_jobs", ["owner_id"], unique=False)
    op.create_index(op.f("ix_service_jobs_status"), "service_jobs", ["status"], unique=False)
    op.create_index(op.f("ix_service_jobs_vessel_id"), "service_jobs", ["vessel_id"], unique=False)
    op.create_table(
        "service_briefs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="preview", nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('preview','published','superseded')", name=op.f("ck_service_briefs_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_service_briefs_created_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["service_jobs.id"], name=op.f("fk_service_briefs_job_id_service_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_briefs")),
        sa.UniqueConstraint("id", "job_id", name="uq_service_briefs_id_job"),
        sa.UniqueConstraint("job_id", "revision_number", name="uq_service_briefs_job_revision"),
    )
    op.create_index(op.f("ix_service_briefs_created_by"), "service_briefs", ["created_by"], unique=False)
    op.create_index(op.f("ix_service_briefs_job_id"), "service_briefs", ["job_id"], unique=False)
    op.create_table(
        "service_invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="uploaded", nullable=False),
        sa.Column("current_revision_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('uploaded','extraction_draft','owner_reviewed','superseded','deleted')",
            name=op.f("ck_service_invoices_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "owner_id"],
            ["service_jobs.id", "service_jobs.owner_id"],
            name="fk_service_invoices_job_same_owner",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_service_invoices_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_invoices")),
    )
    op.create_index(op.f("ix_service_invoices_job_id"), "service_invoices", ["job_id"], unique=False)
    op.create_index(op.f("ix_service_invoices_owner_id"), "service_invoices", ["owner_id"], unique=False)
    op.create_table(
        "service_job_access",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("general", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("restricted", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["service_jobs.id"], name=op.f("fk_service_job_access_job_id_service_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_service_job_access")),
    )
    op.create_table(
        "service_job_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), server_default="invited", nullable=False),
        sa.Column("sections", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("live_updates", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("shared_brief_id", sa.UUID(), nullable=True),
        sa.Column("invited_by", sa.UUID(), nullable=False),
        sa.Column("accepted_by", sa.UUID(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('invited','accepted','declined','revoked')",
            name=op.f("ck_service_job_assignments_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
            name=op.f("fk_service_job_assignments_accepted_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["users.id"], name=op.f("fk_service_job_assignments_invited_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_job_assignments_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_job_assignments_organization_id_contractor_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_job_assignments")),
        sa.UniqueConstraint("id", "job_id", name="uq_service_job_assignments_id_job"),
    )
    op.create_index(
        op.f("ix_service_job_assignments_accepted_by"), "service_job_assignments", ["accepted_by"], unique=False
    )
    op.create_index(
        op.f("ix_service_job_assignments_invited_by"), "service_job_assignments", ["invited_by"], unique=False
    )
    op.create_index(op.f("ix_service_job_assignments_job_id"), "service_job_assignments", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_service_job_assignments_organization_id"), "service_job_assignments", ["organization_id"], unique=False
    )
    op.create_index(
        "uq_service_job_assignments_live",
        "service_job_assignments",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('invited','accepted')"),
    )
    op.create_table(
        "service_job_evidence_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("requester_role", sa.String(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("measurement_dimension", sa.String(), nullable=True),
        sa.Column("priority", sa.String(), server_default="normal", nullable=False),
        sa.Column("status", sa.String(), server_default="outstanding", nullable=False),
        sa.Column("unavailable_reason", sa.String(), nullable=True),
        sa.Column("technician_inspection_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("answer_note", sa.Text(), nullable=True),
        sa.Column("answered_by", sa.UUID(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "category IN ('overview','access_route','label','close_up','connections','route','markings','measurement','document','other')",
            name=op.f("ck_service_job_evidence_requests_valid_category"),
        ),
        sa.CheckConstraint(
            "priority IN ('high','normal','low')", name=op.f("ck_service_job_evidence_requests_valid_priority")
        ),
        sa.CheckConstraint(
            "requester_role IN ('assistant','owner','contractor')",
            name=op.f("ck_service_job_evidence_requests_valid_requester_role"),
        ),
        sa.CheckConstraint(
            "status IN ('outstanding','answered','unavailable','waived')",
            name=op.f("ck_service_job_evidence_requests_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["answered_by"],
            ["users.id"],
            name=op.f("fk_service_job_evidence_requests_answered_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_job_evidence_requests_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_job_evidence_requests_organization_id_contractor_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_service_job_evidence_requests_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_job_evidence_requests")),
        sa.UniqueConstraint("id", "job_id", name="uq_service_job_evidence_requests_id_job"),
    )
    op.create_index(
        op.f("ix_service_job_evidence_requests_answered_by"),
        "service_job_evidence_requests",
        ["answered_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_job_evidence_requests_job_id"), "service_job_evidence_requests", ["job_id"], unique=False
    )
    op.create_index(
        op.f("ix_service_job_evidence_requests_requested_by"),
        "service_job_evidence_requests",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_job_evidence_requests_status"), "service_job_evidence_requests", ["status"], unique=False
    )
    op.create_table(
        "service_preparation_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("quantity_basis", sa.Text(), nullable=True),
        sa.Column("open_requirements", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("specification", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "depends_on_measurement_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("supporting_asset_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column(
            "candidate_product_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("catalogue_match", sa.String(), server_default="none", nullable=False),
        sa.Column("confirmed_product_id", sa.UUID(), nullable=True),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="suggested", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_job_revision", sa.Integer(), nullable=True),
        sa.Column("replaced_by_id", sa.UUID(), nullable=True),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "catalogue_match IN ('none','candidates','confirmed')",
            name=op.f("ck_service_preparation_items_valid_catalogue_match"),
        ),
        sa.CheckConstraint(
            "category IN ('part','consumable','tool')", name=op.f("ck_service_preparation_items_valid_category")
        ),
        sa.CheckConstraint(
            "origin IN ('assistant','owner','contractor')", name=op.f("ck_service_preparation_items_valid_origin")
        ),
        sa.CheckConstraint(
            "status IN ('suggested','needs_evidence','contractor_confirmed','rejected','replaced','superseded')",
            name=op.f("ck_service_preparation_items_valid_status"),
        ),
        sa.CheckConstraint(
            "quantity IS NULL OR quantity > 0", name=op.f("ck_service_preparation_items_quantity_positive")
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["users.id"],
            name=op.f("fk_service_preparation_items_confirmed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_product_id"],
            ["products.id"],
            name=op.f("fk_service_preparation_items_confirmed_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_service_preparation_items_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_preparation_items_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["service_preparation_items.id"],
            name=op.f("fk_service_preparation_items_replaced_by_id_service_preparation_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_preparation_items")),
    )
    op.create_index(
        op.f("ix_service_preparation_items_confirmed_by"), "service_preparation_items", ["confirmed_by"], unique=False
    )
    op.create_index(
        op.f("ix_service_preparation_items_created_by"), "service_preparation_items", ["created_by"], unique=False
    )
    op.create_index(op.f("ix_service_preparation_items_job_id"), "service_preparation_items", ["job_id"], unique=False)
    op.create_table(
        "service_scope_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("is_change", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("proposed_by", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("tasks", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("estimate_lines", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("estimate_total_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("exclusions", sa.Text(), nullable=True),
        sa.Column("assumptions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="proposed", nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','proposed','accepted','rejected','change_requested','superseded')",
            name=op.f("ck_service_scope_revisions_valid_status"),
        ),
        sa.CheckConstraint(
            "estimate_total_minor IS NULL OR estimate_total_minor >= 0",
            name=op.f("ck_service_scope_revisions_estimate_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_scope_revisions_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_scope_revisions_organization_id_contractor_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"],
            ["users.id"],
            name=op.f("fk_service_scope_revisions_proposed_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["service_scope_revisions.id"],
            name=op.f("fk_service_scope_revisions_supersedes_id_service_scope_revisions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_scope_revisions")),
        sa.UniqueConstraint("id", "job_id", name="uq_service_scope_revisions_id_job"),
        sa.UniqueConstraint("job_id", "revision_number", name="uq_service_scope_job_revision"),
    )
    op.create_index(op.f("ix_service_scope_revisions_job_id"), "service_scope_revisions", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_service_scope_revisions_proposed_by"), "service_scope_revisions", ["proposed_by"], unique=False
    )
    op.create_table(
        "service_analysis_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("invoice_id", sa.UUID(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column("job_revision", sa.Integer(), nullable=True),
        sa.Column("asset_versions", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("invoice_revision_id", sa.UUID(), nullable=True),
        sa.Column("assignment_id", sa.UUID(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("config_version", sa.String(), nullable=True),
        sa.Column("input_digest", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(), server_default="pending", nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('capture_quality','evidence_observations','invoice_extraction','invoice_explanation')",
            name=op.f("ck_service_analysis_runs_valid_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('pending','running','draft_ready','confirmed','superseded','failed','cancelled')",
            name=op.f("ck_service_analysis_runs_valid_status"),
        ),
        sa.CheckConstraint(
            "(job_id IS NOT NULL) OR (invoice_id IS NOT NULL)", name=op.f("ck_service_analysis_runs_has_subject")
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["service_invoices.id"],
            name=op.f("fk_service_analysis_runs_invoice_id_service_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_analysis_runs_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_service_analysis_runs_requested_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_analysis_runs")),
        sa.UniqueConstraint("requested_by", "idempotency_key", name="uq_service_analysis_runs_idem"),
    )
    op.create_index(op.f("ix_service_analysis_runs_invoice_id"), "service_analysis_runs", ["invoice_id"], unique=False)
    op.create_index(op.f("ix_service_analysis_runs_job_id"), "service_analysis_runs", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_service_analysis_runs_requested_by"), "service_analysis_runs", ["requested_by"], unique=False
    )
    op.create_index(op.f("ix_service_analysis_runs_status"), "service_analysis_runs", ["status"], unique=False)
    op.create_table(
        "service_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("uploader_organization_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("evidence_request_id", sa.UUID(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("declared_filename", sa.String(), nullable=True),
        sa.Column("declared_content_type", sa.String(), nullable=True),
        sa.Column("max_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column("derivative_key", sa.String(), nullable=True),
        sa.Column("detected_type", sa.String(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), server_default="upload_pending", nullable=False),
        sa.Column("rejection_reason", sa.String(), nullable=True),
        sa.Column("scan_result", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("duplicate_of_id", sa.UUID(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('job_photo','job_document','invoice')", name=op.f("ck_service_assets_valid_purpose")
        ),
        sa.CheckConstraint(
            "status IN ('upload_pending','quarantined','processing','available','rejected','deleted')",
            name=op.f("ck_service_assets_valid_status"),
        ),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name=op.f("ck_service_assets_size_nonneg")),
        sa.ForeignKeyConstraint(
            ["evidence_request_id", "job_id"],
            ["service_job_evidence_requests.id", "service_job_evidence_requests.job_id"],
            name="fk_service_assets_request_same_job",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["service_jobs.id"], name=op.f("fk_service_assets_job_id_service_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_service_assets_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_service_assets_uploaded_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["uploader_organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_assets_uploader_organization_id_contractor_organizations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_assets")),
        sa.UniqueConstraint("derivative_key", name=op.f("uq_service_assets_derivative_key")),
        sa.UniqueConstraint("id", "job_id", name="uq_service_assets_id_job"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_service_assets_owner_idem"),
        sa.UniqueConstraint("storage_key", name=op.f("uq_service_assets_storage_key")),
    )
    op.create_index(
        op.f("ix_service_assets_evidence_request_id"), "service_assets", ["evidence_request_id"], unique=False
    )
    op.create_index(op.f("ix_service_assets_job_id"), "service_assets", ["job_id"], unique=False)
    op.create_index(op.f("ix_service_assets_owner_id"), "service_assets", ["owner_id"], unique=False)
    op.create_index(op.f("ix_service_assets_sha256"), "service_assets", ["sha256"], unique=False)
    op.create_index(op.f("ix_service_assets_status"), "service_assets", ["status"], unique=False)
    op.create_index(op.f("ix_service_assets_uploaded_by"), "service_assets", ["uploaded_by"], unique=False)
    op.create_table(
        "service_brief_acknowledgements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("brief_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('reviewed','incomplete','limitations_acknowledged','confirmed')",
            name=op.f("ck_service_brief_acknowledgements_valid_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["brief_id"],
            ["service_briefs.id"],
            name=op.f("fk_service_brief_acknowledgements_brief_id_service_briefs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_brief_acknowledgements_organization_id_contractor_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_service_brief_acknowledgements_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_brief_acknowledgements")),
    )
    op.create_index(
        op.f("ix_service_brief_acknowledgements_brief_id"), "service_brief_acknowledgements", ["brief_id"], unique=False
    )
    op.create_index(
        op.f("ix_service_brief_acknowledgements_user_id"), "service_brief_acknowledgements", ["user_id"], unique=False
    )
    op.create_table(
        "service_job_assignment_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("restricted_access", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("added_by", sa.UUID(), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["added_by"],
            ["users.id"],
            name=op.f("fk_service_job_assignment_members_added_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["service_job_assignments.id"],
            name=op.f("fk_service_job_assignment_members_assignment_id_service_job_assignments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_service_job_assignment_members_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_job_assignment_members")),
        sa.UniqueConstraint("assignment_id", "user_id", name="uq_service_job_assignment_members"),
    )
    op.create_index(
        op.f("ix_service_job_assignment_members_added_by"), "service_job_assignment_members", ["added_by"], unique=False
    )
    op.create_index(
        op.f("ix_service_job_assignment_members_assignment_id"),
        "service_job_assignment_members",
        ["assignment_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_job_assignment_members_user_id"), "service_job_assignment_members", ["user_id"], unique=False
    )
    op.create_table(
        "service_scope_decisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("scope_revision_id", sa.UUID(), nullable=False),
        sa.Column("revision_digest", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted','rejected','change_requested')",
            name=op.f("ck_service_scope_decisions_valid_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_service_scope_decisions_decided_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_scope_decisions_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scope_revision_id"],
            ["service_scope_revisions.id"],
            name=op.f("fk_service_scope_decisions_scope_revision_id_service_scope_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_scope_decisions")),
        sa.UniqueConstraint("decided_by", "idempotency_key", name="uq_service_scope_decisions_idem"),
        sa.UniqueConstraint("scope_revision_id", name="uq_service_scope_decisions_revision"),
    )
    op.create_index(
        op.f("ix_service_scope_decisions_decided_by"), "service_scope_decisions", ["decided_by"], unique=False
    )
    op.create_index(op.f("ix_service_scope_decisions_job_id"), "service_scope_decisions", ["job_id"], unique=False)
    op.create_table(
        "service_visit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("contests_event_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "actor_role IN ('owner','contractor','admin','system')",
            name=op.f("ck_service_visit_events_valid_actor_role"),
        ),
        sa.CheckConstraint(
            "kind IN ('scheduled','attended','completed','cancelled','completion_contested')",
            name=op.f("ck_service_visit_events_valid_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_service_visit_events_actor_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "job_id"],
            ["service_job_assignments.id", "service_job_assignments.job_id"],
            name="fk_service_visit_assignment_same_job",
        ),
        sa.ForeignKeyConstraint(
            ["contests_event_id"],
            ["service_visit_events.id"],
            name=op.f("fk_service_visit_events_contests_event_id_service_visit_events"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_visit_events_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_visit_events")),
    )
    op.create_index(op.f("ix_service_visit_events_actor_id"), "service_visit_events", ["actor_id"], unique=False)
    op.create_index(op.f("ix_service_visit_events_job_id"), "service_visit_events", ["job_id"], unique=False)
    op.create_table(
        "service_feedback_windows",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("eligibility_event_id", sa.UUID(), nullable=False),
        sa.Column("basis", sa.String(), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["service_job_assignments.id"],
            name=op.f("fk_service_feedback_windows_assignment_id_service_job_assignments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["eligibility_event_id"],
            ["service_visit_events.id"],
            name=op.f("fk_service_feedback_windows_eligibility_event_id_service_visit_events"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_feedback_windows_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_feedback_windows_organization_id_contractor_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_service_feedback_windows_owner_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_service_feedback_windows")),
    )
    op.create_index(
        op.f("ix_service_feedback_windows_owner_id"), "service_feedback_windows", ["owner_id"], unique=False
    )
    op.create_table(
        "service_invoice_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("source_asset_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(), server_default="uploaded", nullable=False),
        sa.Column("extracted", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("rounding", sa.String(), server_default="half_up", nullable=False),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "origin IN ('owner_upload','contractor_correction','manual_entry')",
            name=op.f("ck_service_invoice_revisions_valid_origin"),
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','extraction_draft','owner_reviewed','superseded')",
            name=op.f("ck_service_invoice_revisions_valid_status"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["service_invoices.id"],
            name=op.f("fk_service_invoice_revisions_invoice_id_service_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_invoice_revisions_organization_id_contractor_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id"],
            ["service_assets.id"],
            name=op.f("fk_service_invoice_revisions_source_asset_id_service_assets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["service_invoice_revisions.id"],
            name=op.f("fk_service_invoice_revisions_supersedes_id_service_invoice_revisions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_service_invoice_revisions_uploaded_by_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_invoice_revisions")),
        sa.UniqueConstraint("invoice_id", "revision_number", name="uq_service_invoice_revisions_number"),
    )
    op.create_index(
        op.f("ix_service_invoice_revisions_invoice_id"), "service_invoice_revisions", ["invoice_id"], unique=False
    )
    op.create_index(
        op.f("ix_service_invoice_revisions_uploaded_by"), "service_invoice_revisions", ["uploaded_by"], unique=False
    )
    op.create_table(
        "service_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("region", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("assertion", sa.Text(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("analysis_run_id", sa.UUID(), nullable=True),
        sa.Column("model_version", sa.String(), nullable=True),
        sa.Column("recorded_by", sa.UUID(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('marking_text','label_text','visible_feature','quality','owner_note','contractor_note')",
            name=op.f("ck_service_observations_valid_kind"),
        ),
        sa.CheckConstraint(
            "state IN ('model_suggested','owner_declared','owner_measured','contractor_confirmed','source_verified','rejected','superseded','unknown')",
            name=op.f("ck_service_observations_valid_state"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"],
            ["service_analysis_runs.id"],
            name=op.f("fk_service_observations_analysis_run_id_service_analysis_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "job_id"], ["service_assets.id", "service_assets.job_id"], name="fk_service_obs_asset_same_job"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_observations_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name=op.f("fk_service_observations_recorded_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["service_observations.id"],
            name=op.f("fk_service_observations_supersedes_id_service_observations"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_observations")),
    )
    op.create_index(op.f("ix_service_observations_asset_id"), "service_observations", ["asset_id"], unique=False)
    op.create_index(op.f("ix_service_observations_job_id"), "service_observations", ["job_id"], unique=False)
    op.create_index(op.f("ix_service_observations_recorded_by"), "service_observations", ["recorded_by"], unique=False)
    op.create_table(
        "service_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("ratings", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("under_review", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "direction IN ('owner_to_contractor','contractor_to_owner')",
            name=op.f("ck_service_feedback_valid_direction"),
        ),
        sa.CheckConstraint(
            "status IN ('draft','submitted','revealed','withdrawn')", name=op.f("ck_service_feedback_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_service_feedback_author_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_feedback_windows.job_id"],
            name=op.f("fk_service_feedback_job_id_service_feedback_windows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_feedback_organization_id_contractor_organizations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_feedback")),
        sa.UniqueConstraint("job_id", "direction", name="uq_service_feedback_job_direction"),
    )
    op.create_index(op.f("ix_service_feedback_author_id"), "service_feedback", ["author_id"], unique=False)
    op.create_table(
        "service_invoice_explanations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_revision_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), server_default="current", nullable=False),
        sa.Column("basis_digest", sa.String(length=64), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('current','superseded')", name=op.f("ck_service_invoice_explanations_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["invoice_revision_id"],
            ["service_invoice_revisions.id"],
            name=op.f("fk_service_invoice_explanations_invoice_revision_id_service_invoice_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_invoice_explanations")),
    )
    op.create_index(
        op.f("ix_service_invoice_explanations_invoice_revision_id"),
        "service_invoice_explanations",
        ["invoice_revision_id"],
        unique=False,
    )
    op.create_table(
        "service_invoice_lines",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_revision_id", sa.UUID(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), server_default="unknown", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("part_number", sa.String(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("tax_printed", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("region", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("certainty", sa.String(), server_default="unknown", nullable=False),
        sa.Column("extracted", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("corrected_by", sa.UUID(), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "kind IN ('part','labour','travel','call_out','consumable','discount','fee','tax','other','unknown')",
            name=op.f("ck_service_invoice_lines_valid_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["corrected_by"],
            ["users.id"],
            name=op.f("fk_service_invoice_lines_corrected_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_revision_id"],
            ["service_invoice_revisions.id"],
            name=op.f("fk_service_invoice_lines_invoice_revision_id_service_invoice_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_invoice_lines")),
        sa.UniqueConstraint("invoice_revision_id", "line_number", name="uq_service_invoice_lines_number"),
    )
    op.create_index(
        op.f("ix_service_invoice_lines_corrected_by"), "service_invoice_lines", ["corrected_by"], unique=False
    )
    op.create_index(
        op.f("ix_service_invoice_lines_invoice_revision_id"),
        "service_invoice_lines",
        ["invoice_revision_id"],
        unique=False,
    )
    op.create_table(
        "service_measurements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("dimension", sa.String(), nullable=False),
        sa.Column("component", sa.String(), nullable=False),
        sa.Column("value_text", sa.String(), nullable=True),
        sa.Column("value_min", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("value_max", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("normalized_min_mm", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("normalized_max_mm", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("precision", sa.String(), nullable=True),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("tool", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("source_asset_id", sa.UUID(), nullable=True),
        sa.Column("source_region", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_observation_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("recorded_by", sa.UUID(), nullable=False),
        sa.Column("confirmed_by", sa.UUID(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmation_method", sa.String(), nullable=True),
        sa.Column("supersedes_id", sa.UUID(), nullable=True),
        sa.Column("job_revision", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "dimension IN ('hose_internal_diameter','hose_external_diameter','fitting_outside_diameter','thread','clamp_range','route_length','bend_radius','clearance','other')",
            name=op.f("ck_service_measurements_valid_dimension"),
        ),
        sa.CheckConstraint(
            "method IN ('marking_read','owner_tape','owner_caliper','owner_other','image_estimate_with_reference','contractor_site','source_document','unknown')",
            name=op.f("ck_service_measurements_valid_method"),
        ),
        sa.CheckConstraint(
            "state IN ('model_suggested','owner_declared','owner_measured','contractor_confirmed','source_verified','rejected','superseded','unknown')",
            name=op.f("ck_service_measurements_valid_state"),
        ),
        sa.CheckConstraint(
            "value_min IS NULL OR value_max IS NULL OR value_min <= value_max",
            name=op.f("ck_service_measurements_range_ordered"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name=op.f("fk_service_measurements_confirmed_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_measurements_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"], ["users.id"], name=op.f("fk_service_measurements_recorded_by_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_asset_id", "job_id"],
            ["service_assets.id", "service_assets.job_id"],
            name="fk_service_measurements_asset_same_job",
        ),
        sa.ForeignKeyConstraint(
            ["source_observation_id"],
            ["service_observations.id"],
            name=op.f("fk_service_measurements_source_observation_id_service_observations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["service_measurements.id"],
            name=op.f("fk_service_measurements_supersedes_id_service_measurements"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_measurements")),
    )
    op.create_index(
        op.f("ix_service_measurements_confirmed_by"), "service_measurements", ["confirmed_by"], unique=False
    )
    op.create_index(op.f("ix_service_measurements_job_id"), "service_measurements", ["job_id"], unique=False)
    op.create_index(op.f("ix_service_measurements_recorded_by"), "service_measurements", ["recorded_by"], unique=False)
    op.create_table(
        "service_feedback_responses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("hidden_by_case_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('response','addendum','correction_request')",
            name=op.f("ck_service_feedback_responses_valid_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_service_feedback_responses_author_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["service_feedback.id"],
            name=op.f("fk_service_feedback_responses_feedback_id_service_feedback"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_feedback_responses")),
    )
    op.create_index(
        op.f("ix_service_feedback_responses_author_id"), "service_feedback_responses", ["author_id"], unique=False
    )
    op.create_index(
        op.f("ix_service_feedback_responses_feedback_id"), "service_feedback_responses", ["feedback_id"], unique=False
    )
    op.create_table(
        "service_feedback_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("ratings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("narrative", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["service_feedback.id"],
            name=op.f("fk_service_feedback_versions_feedback_id_service_feedback"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_feedback_versions")),
        sa.UniqueConstraint("feedback_id", "version", name="uq_service_feedback_versions"),
    )
    op.create_index(
        op.f("ix_service_feedback_versions_feedback_id"), "service_feedback_versions", ["feedback_id"], unique=False
    )
    op.create_table(
        "service_invoice_questions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("invoice_id", sa.UUID(), nullable=False),
        sa.Column("invoice_revision_id", sa.UUID(), nullable=False),
        sa.Column("line_id", sa.UUID(), nullable=True),
        sa.Column("origin", sa.String(), server_default="owner", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="draft", nullable=False),
        sa.Column("shared_assignment_id", sa.UUID(), nullable=True),
        sa.Column("shared_asset_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','shared','answered','closed')", name=op.f("ck_service_invoice_questions_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_service_invoice_questions_created_by_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["service_invoices.id"],
            name=op.f("fk_service_invoice_questions_invoice_id_service_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invoice_revision_id"],
            ["service_invoice_revisions.id"],
            name=op.f("fk_service_invoice_questions_invoice_revision_id_service_invoice_revisions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["line_id"],
            ["service_invoice_lines.id"],
            name=op.f("fk_service_invoice_questions_line_id_service_invoice_lines"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["shared_assignment_id"],
            ["service_job_assignments.id"],
            name=op.f("fk_service_invoice_questions_shared_assignment_id_service_job_assignments"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_invoice_questions")),
    )
    op.create_index(
        op.f("ix_service_invoice_questions_created_by"), "service_invoice_questions", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_service_invoice_questions_invoice_id"), "service_invoice_questions", ["invoice_id"], unique=False
    )
    op.create_table(
        "service_moderation_cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("feedback_id", sa.UUID(), nullable=True),
        sa.Column("visit_event_id", sa.UUID(), nullable=True),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("restrict_content", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("assigned_moderator_id", sa.UUID(), nullable=True),
        sa.Column("disposition", sa.String(), nullable=True),
        sa.Column("disposition_note", sa.Text(), nullable=True),
        sa.Column("retention_hold", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "category IN ('factual_dispute','opinion','harassment','personal_or_security_information','completion_contested','other')",
            name=op.f("ck_service_moderation_cases_valid_category"),
        ),
        sa.CheckConstraint(
            "status IN ('open','under_review','resolved')", name=op.f("ck_service_moderation_cases_valid_status")
        ),
        sa.ForeignKeyConstraint(
            ["assigned_moderator_id"],
            ["users.id"],
            name=op.f("fk_service_moderation_cases_assigned_moderator_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_id"],
            ["service_feedback.id"],
            name=op.f("fk_service_moderation_cases_feedback_id_service_feedback"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["service_jobs.id"],
            name=op.f("fk_service_moderation_cases_job_id_service_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reporter_id"],
            ["users.id"],
            name=op.f("fk_service_moderation_cases_reporter_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["visit_event_id"],
            ["service_visit_events.id"],
            name=op.f("fk_service_moderation_cases_visit_event_id_service_visit_events"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_moderation_cases")),
    )
    op.create_index(
        op.f("ix_service_moderation_cases_assigned_moderator_id"),
        "service_moderation_cases",
        ["assigned_moderator_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_moderation_cases_feedback_id"), "service_moderation_cases", ["feedback_id"], unique=False
    )
    op.create_index(op.f("ix_service_moderation_cases_job_id"), "service_moderation_cases", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_service_moderation_cases_reporter_id"), "service_moderation_cases", ["reporter_id"], unique=False
    )
    op.create_index(op.f("ix_service_moderation_cases_status"), "service_moderation_cases", ["status"], unique=False)
    op.create_table(
        "service_invoice_question_responses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("corrected_revision_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_service_invoice_question_responses_author_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["corrected_revision_id"],
            ["service_invoice_revisions.id"],
            name=op.f("fk_service_invoice_question_responses_corrected_revision_id_service_invoice_revisions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["contractor_organizations.id"],
            name=op.f("fk_service_invoice_question_responses_organization_id_contractor_organizations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["service_invoice_questions.id"],
            name=op.f("fk_service_invoice_question_responses_question_id_service_invoice_questions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_invoice_question_responses")),
    )
    op.create_index(
        op.f("ix_service_invoice_question_responses_author_id"),
        "service_invoice_question_responses",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_invoice_question_responses_question_id"),
        "service_invoice_question_responses",
        ["question_id"],
        unique=False,
    )
    op.create_table(
        "service_moderation_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("content_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_service_moderation_actions_actor_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["service_moderation_cases.id"],
            name=op.f("fk_service_moderation_actions_case_id_service_moderation_cases"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_moderation_actions")),
    )
    op.create_index(
        op.f("ix_service_moderation_actions_actor_id"), "service_moderation_actions", ["actor_id"], unique=False
    )
    op.create_index(
        op.f("ix_service_moderation_actions_case_id"), "service_moderation_actions", ["case_id"], unique=False
    )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'customer' WHERE role = 'moderator'")
    op.drop_constraint("valid_role", "users", type_="check")
    op.create_check_constraint("valid_role", "users", ROLES_V1)
    op.drop_index(op.f("ix_service_moderation_actions_case_id"), table_name="service_moderation_actions")
    op.drop_index(op.f("ix_service_moderation_actions_actor_id"), table_name="service_moderation_actions")
    op.drop_table("service_moderation_actions")
    op.drop_index(
        op.f("ix_service_invoice_question_responses_question_id"), table_name="service_invoice_question_responses"
    )
    op.drop_index(
        op.f("ix_service_invoice_question_responses_author_id"), table_name="service_invoice_question_responses"
    )
    op.drop_table("service_invoice_question_responses")
    op.drop_index(op.f("ix_service_moderation_cases_status"), table_name="service_moderation_cases")
    op.drop_index(op.f("ix_service_moderation_cases_reporter_id"), table_name="service_moderation_cases")
    op.drop_index(op.f("ix_service_moderation_cases_job_id"), table_name="service_moderation_cases")
    op.drop_index(op.f("ix_service_moderation_cases_feedback_id"), table_name="service_moderation_cases")
    op.drop_index(op.f("ix_service_moderation_cases_assigned_moderator_id"), table_name="service_moderation_cases")
    op.drop_table("service_moderation_cases")
    op.drop_index(op.f("ix_service_invoice_questions_invoice_id"), table_name="service_invoice_questions")
    op.drop_index(op.f("ix_service_invoice_questions_created_by"), table_name="service_invoice_questions")
    op.drop_table("service_invoice_questions")
    op.drop_index(op.f("ix_service_feedback_versions_feedback_id"), table_name="service_feedback_versions")
    op.drop_table("service_feedback_versions")
    op.drop_index(op.f("ix_service_feedback_responses_feedback_id"), table_name="service_feedback_responses")
    op.drop_index(op.f("ix_service_feedback_responses_author_id"), table_name="service_feedback_responses")
    op.drop_table("service_feedback_responses")
    op.drop_index(op.f("ix_service_measurements_recorded_by"), table_name="service_measurements")
    op.drop_index(op.f("ix_service_measurements_job_id"), table_name="service_measurements")
    op.drop_index(op.f("ix_service_measurements_confirmed_by"), table_name="service_measurements")
    op.drop_table("service_measurements")
    op.drop_index(op.f("ix_service_invoice_lines_invoice_revision_id"), table_name="service_invoice_lines")
    op.drop_index(op.f("ix_service_invoice_lines_corrected_by"), table_name="service_invoice_lines")
    op.drop_table("service_invoice_lines")
    op.drop_index(
        op.f("ix_service_invoice_explanations_invoice_revision_id"), table_name="service_invoice_explanations"
    )
    op.drop_table("service_invoice_explanations")
    op.drop_index(op.f("ix_service_feedback_author_id"), table_name="service_feedback")
    op.drop_table("service_feedback")
    op.drop_index(op.f("ix_service_observations_recorded_by"), table_name="service_observations")
    op.drop_index(op.f("ix_service_observations_job_id"), table_name="service_observations")
    op.drop_index(op.f("ix_service_observations_asset_id"), table_name="service_observations")
    op.drop_table("service_observations")
    op.drop_index(op.f("ix_service_invoice_revisions_uploaded_by"), table_name="service_invoice_revisions")
    op.drop_index(op.f("ix_service_invoice_revisions_invoice_id"), table_name="service_invoice_revisions")
    op.drop_table("service_invoice_revisions")
    op.drop_index(op.f("ix_service_feedback_windows_owner_id"), table_name="service_feedback_windows")
    op.drop_table("service_feedback_windows")
    op.drop_index(op.f("ix_service_visit_events_job_id"), table_name="service_visit_events")
    op.drop_index(op.f("ix_service_visit_events_actor_id"), table_name="service_visit_events")
    op.drop_table("service_visit_events")
    op.drop_index(op.f("ix_service_scope_decisions_job_id"), table_name="service_scope_decisions")
    op.drop_index(op.f("ix_service_scope_decisions_decided_by"), table_name="service_scope_decisions")
    op.drop_table("service_scope_decisions")
    op.drop_index(op.f("ix_service_job_assignment_members_user_id"), table_name="service_job_assignment_members")
    op.drop_index(op.f("ix_service_job_assignment_members_assignment_id"), table_name="service_job_assignment_members")
    op.drop_index(op.f("ix_service_job_assignment_members_added_by"), table_name="service_job_assignment_members")
    op.drop_table("service_job_assignment_members")
    op.drop_index(op.f("ix_service_brief_acknowledgements_user_id"), table_name="service_brief_acknowledgements")
    op.drop_index(op.f("ix_service_brief_acknowledgements_brief_id"), table_name="service_brief_acknowledgements")
    op.drop_table("service_brief_acknowledgements")
    op.drop_index(op.f("ix_service_assets_uploaded_by"), table_name="service_assets")
    op.drop_index(op.f("ix_service_assets_status"), table_name="service_assets")
    op.drop_index(op.f("ix_service_assets_sha256"), table_name="service_assets")
    op.drop_index(op.f("ix_service_assets_owner_id"), table_name="service_assets")
    op.drop_index(op.f("ix_service_assets_job_id"), table_name="service_assets")
    op.drop_index(op.f("ix_service_assets_evidence_request_id"), table_name="service_assets")
    op.drop_table("service_assets")
    op.drop_index(op.f("ix_service_analysis_runs_status"), table_name="service_analysis_runs")
    op.drop_index(op.f("ix_service_analysis_runs_requested_by"), table_name="service_analysis_runs")
    op.drop_index(op.f("ix_service_analysis_runs_job_id"), table_name="service_analysis_runs")
    op.drop_index(op.f("ix_service_analysis_runs_invoice_id"), table_name="service_analysis_runs")
    op.drop_table("service_analysis_runs")
    op.drop_index(op.f("ix_service_scope_revisions_proposed_by"), table_name="service_scope_revisions")
    op.drop_index(op.f("ix_service_scope_revisions_job_id"), table_name="service_scope_revisions")
    op.drop_table("service_scope_revisions")
    op.drop_index(op.f("ix_service_preparation_items_job_id"), table_name="service_preparation_items")
    op.drop_index(op.f("ix_service_preparation_items_created_by"), table_name="service_preparation_items")
    op.drop_index(op.f("ix_service_preparation_items_confirmed_by"), table_name="service_preparation_items")
    op.drop_table("service_preparation_items")
    op.drop_index(op.f("ix_service_job_evidence_requests_status"), table_name="service_job_evidence_requests")
    op.drop_index(op.f("ix_service_job_evidence_requests_requested_by"), table_name="service_job_evidence_requests")
    op.drop_index(op.f("ix_service_job_evidence_requests_job_id"), table_name="service_job_evidence_requests")
    op.drop_index(op.f("ix_service_job_evidence_requests_answered_by"), table_name="service_job_evidence_requests")
    op.drop_table("service_job_evidence_requests")
    op.drop_index(
        "uq_service_job_assignments_live",
        table_name="service_job_assignments",
        postgresql_where=sa.text("status IN ('invited','accepted')"),
    )
    op.drop_index(op.f("ix_service_job_assignments_organization_id"), table_name="service_job_assignments")
    op.drop_index(op.f("ix_service_job_assignments_job_id"), table_name="service_job_assignments")
    op.drop_index(op.f("ix_service_job_assignments_invited_by"), table_name="service_job_assignments")
    op.drop_index(op.f("ix_service_job_assignments_accepted_by"), table_name="service_job_assignments")
    op.drop_table("service_job_assignments")
    op.drop_table("service_job_access")
    op.drop_index(op.f("ix_service_invoices_owner_id"), table_name="service_invoices")
    op.drop_index(op.f("ix_service_invoices_job_id"), table_name="service_invoices")
    op.drop_table("service_invoices")
    op.drop_index(op.f("ix_service_briefs_job_id"), table_name="service_briefs")
    op.drop_index(op.f("ix_service_briefs_created_by"), table_name="service_briefs")
    op.drop_table("service_briefs")
    op.drop_index(op.f("ix_service_jobs_vessel_id"), table_name="service_jobs")
    op.drop_index(op.f("ix_service_jobs_status"), table_name="service_jobs")
    op.drop_index(op.f("ix_service_jobs_owner_id"), table_name="service_jobs")
    op.drop_table("service_jobs")
    op.drop_index(op.f("ix_contractor_memberships_verified_by"), table_name="contractor_memberships")
    op.drop_index(op.f("ix_contractor_memberships_user_id"), table_name="contractor_memberships")
    op.drop_index(op.f("ix_contractor_memberships_organization_id"), table_name="contractor_memberships")
    op.drop_table("contractor_memberships")
    op.drop_index(op.f("ix_contractor_organizations_created_by"), table_name="contractor_organizations")
    op.drop_table("contractor_organizations")
