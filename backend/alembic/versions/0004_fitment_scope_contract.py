"""Fitment-rule scope contract: dependent restrictions need their parent scope (FM-02).

A rule such as {engine F150, vessel_model 2250, year_to 2000} used to pass validation
and the evaluator silently ignored the vessel restrictions. Rows that break the contract
(blank strings count as absent; years 1900–2100 and ordered) are moved verbatim, with
the reasons, to ``fitment_rule_quarantine`` — so they can support no fit — and the
constraints are then added fully validated. ``python -m app.cli fitment-audit`` lists
the quarantined rules for staff to recreate correctly.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLE = "product_compatibility"
# Literal copy of app.models.product.FITMENT_SCOPE_CHECKS at this revision.
FITMENT_SCOPE_CHECKS = {
    "nonblank_scope": (
        "NOT btrim(coalesce(vessel_make, '')) = '' OR NOT btrim(coalesce(engine_make, '')) = '' OR equipment_category_id IS NOT NULL"
    ),
    "vessel_dependents": (
        "NOT btrim(coalesce(vessel_make, '')) = '' OR (btrim(coalesce(vessel_model, '')) = '' AND year_from IS NULL AND year_to IS NULL)"
    ),
    "engine_dependents": (
        "NOT btrim(coalesce(engine_make, '')) = '' OR (btrim(coalesce(engine_model, '')) = '' AND engine_year_from IS NULL AND engine_year_to IS NULL)"
    ),
    "equipment_dependents": (
        "equipment_category_id IS NOT NULL OR (btrim(coalesce(equipment_make, '')) = '' AND btrim(coalesce(equipment_model, '')) = '')"
    ),
    "vessel_years": (
        "(year_from IS NULL OR year_from BETWEEN 1900 AND 2100) AND (year_to IS NULL OR year_to BETWEEN 1900 AND 2100) AND (year_from IS NULL OR year_to IS NULL OR year_from <= year_to)"
    ),
    "engine_years": (
        "(engine_year_from IS NULL OR engine_year_from BETWEEN 1900 AND 2100) AND (engine_year_to IS NULL OR engine_year_to BETWEEN 1900 AND 2100) AND (engine_year_from IS NULL OR engine_year_to IS NULL OR engine_year_from <= engine_year_to)"
    ),
}


def upgrade() -> None:
    op.create_table(
        "fitment_rule_quarantine",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rule", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("problems", sa.Text(), nullable=False),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fitment_rule_quarantine")),
    )
    valid = " AND ".join(f"({sql})" for sql in FITMENT_SCOPE_CHECKS.values())
    problems = ", ".join(f"CASE WHEN NOT ({sql}) THEN '{name}' END" for name, sql in FITMENT_SCOPE_CHECKS.items())
    op.execute(
        f"INSERT INTO fitment_rule_quarantine (id, original_id, product_id, rule, problems) "
        f"SELECT gen_random_uuid(), pc.id, pc.product_id, to_jsonb(pc), concat_ws('; ', {problems}) "
        f"FROM {TABLE} pc WHERE NOT ({valid})"
    )
    op.execute(f"DELETE FROM {TABLE} WHERE NOT ({valid})")
    for name, sql in FITMENT_SCOPE_CHECKS.items():
        op.create_check_constraint(name, TABLE, sql)


def downgrade() -> None:
    for name in FITMENT_SCOPE_CHECKS:
        op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS ck_{TABLE}_{name}")
    op.execute(
        f"INSERT INTO {TABLE} SELECT (jsonb_populate_record(NULL::{TABLE}, rule)).* FROM fitment_rule_quarantine"
    )
    op.drop_table("fitment_rule_quarantine")
