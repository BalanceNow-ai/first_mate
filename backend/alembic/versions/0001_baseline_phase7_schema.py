"""Baseline: the exact schema produced by Base.metadata.create_all() at main@49877e2.

The DDL in ``0001_phase7_schema.sql`` is a ``pg_dump --schema-only`` of a database
created by the Phase-7 code, so constraint names are PostgreSQL's defaults (``*_fkey``)
exactly as on any database created before this repair programme.

* Fresh install: ``alembic upgrade head`` runs this file, then 0002.
* Existing Phase-7 database: ``alembic stamp 0001`` once, then ``alembic upgrade head``.

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

_SQL = Path(__file__).with_name("0001_phase7_schema.sql")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    ddl = _SQL.read_text()
    for statement in ddl.split(";\n"):
        statement = statement.strip()
        if statement and not statement.upper().startswith("CREATE EXTENSION"):
            op.execute(statement)


def downgrade() -> None:
    for table in (
        "checklist_items", "helm_dash_deliveries", "voyage_checklists", "ai_conversations",
        "crew_team_members", "order_items", "crew_teams", "crew_points", "cart_items",
        "orders", "product_compatibility", "vessels", "rag_documents", "products", "users",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
