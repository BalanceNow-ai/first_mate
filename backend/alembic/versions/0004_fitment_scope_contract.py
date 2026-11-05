"""Fitment-rule scope contract: dependent restrictions need their parent scope (FM-02).

A rule such as {engine F150, vessel_model 2250, year_to 2000} used to pass validation
and the evaluator silently ignored the vessel restrictions. The constraints are added
``NOT VALID`` so every new or updated row is checked immediately without rewriting
existing data; they are validated here only when no existing row violates them.
Existing malformed rows are evaluated as ``unknown`` (fail closed) and listed by
``python -m app.cli fitment-audit`` for correction, after which
``ALTER TABLE product_compatibility VALIDATE CONSTRAINT …`` can be run.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TABLE = "product_compatibility"
# Literal copy of app.models.product.FITMENT_SCOPE_CHECKS at this revision.
FITMENT_SCOPE_CHECKS = {
    "nonblank_scope": (
        "btrim(coalesce(vessel_make, '')) <> '' OR btrim(coalesce(engine_make, '')) <> '' "
        "OR equipment_category_id IS NOT NULL"
    ),
    "vessel_dependents": (
        "btrim(coalesce(vessel_make, '')) <> '' OR (vessel_model IS NULL AND year_from IS NULL AND year_to IS NULL)"
    ),
    "engine_dependents": (
        "btrim(coalesce(engine_make, '')) <> '' "
        "OR (engine_model IS NULL AND engine_year_from IS NULL AND engine_year_to IS NULL)"
    ),
    "equipment_dependents": "equipment_category_id IS NOT NULL OR (equipment_make IS NULL AND equipment_model IS NULL)",
    "vessel_year_order": "year_from IS NULL OR year_to IS NULL OR year_from <= year_to",
    "engine_year_order": "engine_year_from IS NULL OR engine_year_to IS NULL OR engine_year_from <= engine_year_to",
}


def upgrade() -> None:
    conn = op.get_bind()
    for name, sql in FITMENT_SCOPE_CHECKS.items():
        full = f"ck_{TABLE}_{name}"
        op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {full} CHECK ({sql}) NOT VALID")
        violations = conn.execute(sa.text(f"SELECT count(*) FROM {TABLE} WHERE NOT ({sql})")).scalar_one()
        if violations == 0:
            op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {full}")


def downgrade() -> None:
    for name in FITMENT_SCOPE_CHECKS:
        op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS ck_{TABLE}_{name}")
