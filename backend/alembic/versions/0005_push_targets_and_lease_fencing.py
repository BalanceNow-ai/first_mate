"""Per-device push outcomes and outbox lease fencing (FM-04).

A partial FCM success used to mark the whole notification sent, losing devices that
failed transiently. Outcomes are now stored per device (``push_targets``) so a retry
targets only the devices still pending, and each claim carries a ``lease_token`` so a
worker whose lease expired cannot overwrite a row another worker has reclaimed.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notification_outbox",
        sa.Column("push_targets", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )
    op.add_column("notification_outbox", sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notification_outbox", "lease_token")
    op.drop_column("notification_outbox", "push_targets")
