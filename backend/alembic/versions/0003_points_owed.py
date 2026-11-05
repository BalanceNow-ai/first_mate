"""Points owed after refunds of already-spent points; bonus clawback ledger kinds.

Independent review findings: refund reversals that exceed the balance must be settled
from later credits, and crew monthly bonuses must be clawed back when refunds reduce
the crew's net spend for a closed period.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-05
"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

KINDS_V2 = (
    "'earn','earn_reversal','monthly_bonus','redeem_discount','redeem_experience',"
    "'redemption_reversal','profile_verification_bonus','adjustment'"
)
KINDS_V3 = KINDS_V2 + ",'monthly_bonus_reversal','owed_settlement'"


def upgrade() -> None:
    # Development databases migrated with an early draft of 0002 got double-prefixed
    # CHECK names (ck_<t>_ck_<t>_<name>); normalise them to the model names.
    op.execute(
        """
        DO $$
        DECLARE r record; prefix text;
        BEGIN
          FOR r IN SELECT c.conrelid::regclass::text AS tbl, c.conname
                   FROM pg_constraint c
                   WHERE c.contype = 'c' AND c.connamespace = 'public'::regnamespace
          LOOP
            prefix := 'ck_' || r.tbl || '_ck_' || r.tbl || '_';
            IF left(r.conname, length(prefix)) = prefix THEN
              EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I', r.tbl, r.conname,
                             'ck_' || r.tbl || '_' || substr(r.conname, length(prefix) + 1));
            END IF;
          END LOOP;
        END $$;
        """
    )
    op.add_column("crew_points", sa.Column("points_owed", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint("owed_nonnegative", "crew_points", "points_owed >= 0")
    op.drop_constraint(op.f("ck_points_transactions_valid_kind"), "points_transactions", type_="check")
    op.create_check_constraint("valid_kind", "points_transactions", f"kind IN ({KINDS_V3})")


def downgrade() -> None:
    op.execute("DELETE FROM points_transactions WHERE kind IN ('monthly_bonus_reversal','owed_settlement')")
    op.drop_constraint(op.f("ck_points_transactions_valid_kind"), "points_transactions", type_="check")
    op.create_check_constraint("valid_kind", "points_transactions", f"kind IN ({KINDS_V2})")
    op.drop_constraint(op.f("ck_crew_points_owed_nonnegative"), "crew_points", type_="check")
    op.drop_column("crew_points", "points_owed")
