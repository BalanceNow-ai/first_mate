"""Repair programme schema: money in cents, roles, reservations, ledger, fitment, RAG,
delivery operations, notifications. Data-preserving upgrade from the Phase-7 baseline.

Backfills (see docs/08_delivery/Repair_Programme.md §4):
* NUMERIC NZD amounts -> integer cents (rounded half-up); sale prices that were not
  below the list price are cleared; negative legacy stock is clamped to 0 (audited).
* Order status vocabulary is mapped; legacy *unpaid* orders keep their already-deducted
  stock as ``reserved`` reservations that expire through the normal release path.
  Legacy ``pi_mock_*`` intents (development fallback) are detached.
* Fitment rules carried over as ``unverified`` (they were never verified) and so no
  longer produce a positive "fits"; rules with no scope at all are removed (audited).
* Name-matched checklist links are retained but marked unverified.
* Users in several crews keep their earliest membership (audited).
* Existing points balances are carried into the ledger as an opening entry.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector  # noqa: F401  (used in create_table blocks)
from sqlalchemy.dialects import postgresql

import pgvector  # noqa: F401

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _drop_fk(table: str, column: str) -> None:
    """Drop the FK on ``table.column`` whatever it is named (legacy *_fkey names)."""
    bind = op.get_bind()
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if fk["constrained_columns"] == [column]:
            op.drop_constraint(fk["name"], table, type_="foreignkey")


def _audit(action: str, entity_type: str, select_sql: str) -> None:
    """Record rows about to be changed destructively in the audit log."""
    op.execute(
        f"""
        INSERT INTO audit_log (id, actor_id, action, entity_type, entity_id, detail, created_at)
        SELECT gen_random_uuid(), NULL, '{action}', '{entity_type}', x.entity_id, x.detail, now()
        FROM ({select_sql}) AS x
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------ new tables
    op.create_table('audit_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('entity_type', sa.String(), nullable=False),
    sa.Column('entity_id', sa.String(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_actor_id'), 'audit_log', ['actor_id'], unique=False)
    op.create_table('equipment_categories',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('parent_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['parent_id'], ['equipment_categories.id'], name=op.f('fk_equipment_categories_parent_id_equipment_categories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment_categories')),
    sa.UniqueConstraint('slug', name=op.f('uq_equipment_categories_slug'))
    )
    op.create_table('knowledge_sources',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('publisher', sa.String(), nullable=True),
    sa.Column('url', sa.String(), nullable=True),
    sa.Column('licence', sa.String(), nullable=False),
    sa.Column('licence_verified', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('admission_status', sa.String(), server_default='pending', nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('domain', sa.String(), nullable=False),
    sa.Column('applies_to', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('checksum', sa.String(), nullable=False),
    sa.Column('version', sa.String(), nullable=True),
    sa.Column('admitted_by', sa.UUID(), nullable=True),
    sa.Column('admitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("admission_status IN ('pending','admitted','revoked')", name=op.f('ck_knowledge_sources_valid_admission')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_sources'))
    )
    op.create_index(op.f('ix_knowledge_sources_domain'), 'knowledge_sources', ['domain'], unique=False)
    op.create_table('manufacturers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('country', sa.String(), nullable=True),
    sa.Column('website', sa.String(), nullable=True),
    sa.Column('mic_codes', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_manufacturers')),
    sa.UniqueConstraint('name', name=op.f('uq_manufacturers_name'))
    )
    op.create_table('operating_areas',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('center_lat', sa.Float(), nullable=False),
    sa.Column('center_lng', sa.Float(), nullable=False),
    sa.Column('radius_nm', sa.Float(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_operating_areas'))
    )
    op.create_table('worker_heartbeats',
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('name', name=op.f('pk_worker_heartbeats'))
    )
    op.create_table('boat_models',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('manufacturer_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('hull_type', sa.String(), nullable=True),
    sa.Column('propulsion_type', sa.String(), nullable=True),
    sa.Column('length_ft', sa.Numeric(precision=5, scale=1), nullable=True),
    sa.Column('beam_in', sa.Integer(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('source_url', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['manufacturer_id'], ['manufacturers.id'], name=op.f('fk_boat_models_manufacturer_id_manufacturers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_boat_models')),
    sa.UniqueConstraint('manufacturer_id', 'name', name=op.f('uq_boat_models_manufacturer_id_name'))
    )
    op.create_index(op.f('ix_boat_models_manufacturer_id'), 'boat_models', ['manufacturer_id'], unique=False)
    op.create_table('delivery_operators',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=False),
    sa.Column('vessel_name', sa.String(), nullable=True),
    sa.Column('area_id', sa.String(), nullable=False),
    sa.Column('is_online', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('certification_reference', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['area_id'], ['operating_areas.id'], name=op.f('fk_delivery_operators_area_id_operating_areas')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_delivery_operators_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_delivery_operators'))
    )
    op.create_table('delivery_quotes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('delivery_type', sa.String(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('service_name', sa.String(), nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='NZD', nullable=False),
    sa.Column('destination', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('parcel_weight_grams', sa.Integer(), nullable=False),
    sa.Column('cart_fingerprint', sa.String(), nullable=False),
    sa.Column('operating_area_id', sa.String(), nullable=True),
    sa.Column('nautical_miles', sa.Numeric(precision=7, scale=2), nullable=True),
    sa.Column('estimated_minutes', sa.Integer(), nullable=True),
    sa.Column('estimated_days', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_by_order_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("delivery_type IN ('courier','helm_dash')", name=op.f('ck_delivery_quotes_valid_delivery_type')),
    sa.CheckConstraint('price_cents >= 0', name=op.f('ck_delivery_quotes_price_nonnegative')),
    sa.ForeignKeyConstraint(['operating_area_id'], ['operating_areas.id'], name=op.f('fk_delivery_quotes_operating_area_id_operating_areas')),
    sa.ForeignKeyConstraint(['used_by_order_id'], ['orders.id'], name=op.f('fk_delivery_quotes_used_by_order_id_orders'), ondelete='SET NULL', use_alter=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_delivery_quotes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_quotes')),
    sa.UniqueConstraint('used_by_order_id', name=op.f('uq_delivery_quotes_used_by_order_id'))
    )
    op.create_index(op.f('ix_delivery_quotes_user_id'), 'delivery_quotes', ['user_id'], unique=False)
    op.create_table('experience_redemptions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('experience_id', sa.String(), nullable=False),
    sa.Column('experience_title', sa.String(), nullable=False),
    sa.Column('points_cost', sa.Integer(), nullable=False),
    sa.Column('cms_provider', sa.String(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('status', sa.String(), server_default='requested', nullable=False),
    sa.Column('customer_note', sa.Text(), nullable=True),
    sa.Column('staff_note', sa.Text(), nullable=True),
    sa.Column('handled_by', sa.UUID(), nullable=True),
    sa.Column('fulfilled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('requested','confirmed','fulfilled','cancelled')", name=op.f('ck_experience_redemptions_valid_status')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_experience_redemptions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_experience_redemptions'))
    )
    op.create_index(op.f('ix_experience_redemptions_user_id'), 'experience_redemptions', ['user_id'], unique=False)
    op.create_table('notification_outbox',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=True),
    sa.Column('channel', sa.String(), nullable=False),
    sa.Column('category', sa.String(), nullable=False),
    sa.Column('template', sa.String(), nullable=False),
    sa.Column('recipient', sa.String(), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
    sa.Column('idempotency_key', sa.String(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('provider', sa.String(), nullable=True),
    sa.Column('provider_message_id', sa.String(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('email','push')", name=op.f('ck_notification_outbox_valid_channel')),
    sa.CheckConstraint("status IN ('pending','sending','sent','failed','dead','suppressed')", name=op.f('ck_notification_outbox_valid_status')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notification_outbox_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notification_outbox')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_notification_outbox_idempotency_key'))
    )
    op.create_index(op.f('ix_notification_outbox_status'), 'notification_outbox', ['status'], unique=False)
    op.create_index(op.f('ix_notification_outbox_user_id'), 'notification_outbox', ['user_id'], unique=False)
    op.create_table('notification_preferences',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('email_enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('push_enabled', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('order_updates', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('delivery_updates', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('service_reminders', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('rewards_updates', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('marketing', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_notification_preferences_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('pk_notification_preferences'))
    )
    op.create_table('push_devices',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('token', sa.String(), nullable=False),
    sa.Column('platform', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_push_devices_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_push_devices')),
    sa.UniqueConstraint('token', name=op.f('uq_push_devices_token'))
    )
    op.create_index(op.f('ix_push_devices_user_id'), 'push_devices', ['user_id'], unique=False)
    op.create_table('crew_invites',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=False),
    sa.Column('invited_email', sa.String(), nullable=False),
    sa.Column('invited_by', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('pending','accepted','declined','revoked','expired')", name=op.f('ck_crew_invites_valid_status')),
    sa.ForeignKeyConstraint(['invited_by'], ['users.id'], name=op.f('fk_crew_invites_invited_by_users')),
    sa.ForeignKeyConstraint(['team_id'], ['crew_teams.id'], name=op.f('fk_crew_invites_team_id_crew_teams'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_crew_invites'))
    )
    op.create_index(op.f('ix_crew_invites_invited_email'), 'crew_invites', ['invited_email'], unique=False)
    op.create_index(op.f('ix_crew_invites_team_id'), 'crew_invites', ['team_id'], unique=False)
    op.create_table('model_years',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('boat_model_id', sa.UUID(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('brochure_url', sa.String(), nullable=True),
    sa.Column('hin_prefix', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['boat_model_id'], ['boat_models.id'], name=op.f('fk_model_years_boat_model_id_boat_models'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_years')),
    sa.UniqueConstraint('boat_model_id', 'year', name=op.f('uq_model_years_boat_model_id_year'))
    )
    op.create_index(op.f('ix_model_years_boat_model_id'), 'model_years', ['boat_model_id'], unique=False)
    op.create_table('courier_shipments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('service_name', sa.String(), nullable=True),
    sa.Column('label_reference', sa.String(), nullable=True),
    sa.Column('tracking_number', sa.String(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('is_test', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_courier_shipments_order_id_orders'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_courier_shipments')),
    sa.UniqueConstraint('order_id', name=op.f('uq_courier_shipments_order_id'))
    )
    op.create_table('discount_entitlements',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('points_cost', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), server_default='issued', nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('reserved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('issued','reserved','consumed','voided')", name=op.f('ck_discount_entitlements_valid_status')),
    sa.CheckConstraint('amount_cents > 0', name=op.f('ck_discount_entitlements_amount_positive')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_discount_entitlements_order_id_orders'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_discount_entitlements_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_discount_entitlements')),
    sa.UniqueConstraint('code', name=op.f('uq_discount_entitlements_code'))
    )
    op.create_index(op.f('ix_discount_entitlements_user_id'), 'discount_entitlements', ['user_id'], unique=False)
    op.create_table('oem_equipment',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('model_year_id', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('equipment_make', sa.String(), nullable=False),
    sa.Column('equipment_model', sa.String(), nullable=True),
    sa.Column('part_sku', sa.String(), nullable=True),
    sa.Column('is_standard', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('data_source', sa.String(), nullable=False),
    sa.Column('source_url', sa.String(), nullable=True),
    sa.Column('confidence_score', sa.Numeric(precision=3, scale=2), nullable=False),
    sa.Column('verification_status', sa.String(), server_default='unverified', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('confidence_score >= 0 AND confidence_score <= 1', name=op.f('ck_oem_equipment_confidence_range')),
    sa.ForeignKeyConstraint(['category_id'], ['equipment_categories.id'], name=op.f('fk_oem_equipment_category_id_equipment_categories')),
    sa.ForeignKeyConstraint(['model_year_id'], ['model_years.id'], name=op.f('fk_oem_equipment_model_year_id_model_years'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_oem_equipment'))
    )
    op.create_index(op.f('ix_oem_equipment_model_year_id'), 'oem_equipment', ['model_year_id'], unique=False)
    op.create_table('payment_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('provider', sa.String(), nullable=False),
    sa.Column('provider_event_id', sa.String(), nullable=False),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('payment_intent_id', sa.String(), nullable=True),
    sa.Column('outcome', sa.String(), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_payment_events_order_id_orders'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payment_events')),
    sa.UniqueConstraint('provider_event_id', name=op.f('uq_payment_events_provider_event_id'))
    )
    op.create_index(op.f('ix_payment_events_order_id'), 'payment_events', ['order_id'], unique=False)
    op.create_index(op.f('ix_payment_events_payment_intent_id'), 'payment_events', ['payment_intent_id'], unique=False)
    op.create_table('stock_reservations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('product_id', sa.UUID(), nullable=False),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('reserved','consumed','released','restocked')", name=op.f('ck_stock_reservations_valid_status')),
    sa.CheckConstraint('quantity > 0', name=op.f('ck_stock_reservations_quantity_positive')),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_stock_reservations_order_id_orders'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], name=op.f('fk_stock_reservations_product_id_products')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stock_reservations')),
    sa.UniqueConstraint('order_id', 'product_id', name=op.f('uq_stock_reservations_order_id_product_id'))
    )
    op.create_index(op.f('ix_stock_reservations_order_id'), 'stock_reservations', ['order_id'], unique=False)
    op.create_table('delivery_location_updates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('delivery_id', sa.UUID(), nullable=False),
    sa.Column('operator_id', sa.UUID(), nullable=False),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lng', sa.Float(), nullable=False),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('heading_deg', sa.Float(), nullable=True),
    sa.Column('speed_knots', sa.Float(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('operator_device','simulated')", name=op.f('ck_delivery_location_updates_valid_source')),
    sa.CheckConstraint('lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180', name=op.f('ck_delivery_location_updates_valid_coords')),
    sa.ForeignKeyConstraint(['delivery_id'], ['helm_dash_deliveries.id'], name=op.f('fk_delivery_location_updates_delivery_id_helm_dash_deliveries'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], name=op.f('fk_delivery_location_updates_operator_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_location_updates'))
    )
    op.create_index(op.f('ix_delivery_location_updates_delivery_id'), 'delivery_location_updates', ['delivery_id'], unique=False)
    op.create_table('delivery_status_events',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('delivery_id', sa.UUID(), nullable=False),
    sa.Column('from_status', sa.String(), nullable=True),
    sa.Column('to_status', sa.String(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_role', sa.String(), nullable=False),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['delivery_id'], ['helm_dash_deliveries.id'], name=op.f('fk_delivery_status_events_delivery_id_helm_dash_deliveries'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_delivery_status_events'))
    )
    op.create_index(op.f('ix_delivery_status_events_delivery_id'), 'delivery_status_events', ['delivery_id'], unique=False)
    op.create_table('equipment_verification_requests',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('vessel_id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('submitted_note', sa.Text(), nullable=True),
    sa.Column('evidence_url', sa.String(), nullable=True),
    sa.Column('reviewed_by', sa.UUID(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_equipment_verification_requests_user_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vessel_id'], ['vessels.id'], name=op.f('fk_equipment_verification_requests_vessel_id_vessels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_equipment_verification_requests'))
    )
    op.create_index(op.f('ix_equipment_verification_requests_vessel_id'), 'equipment_verification_requests', ['vessel_id'], unique=False)
    op.create_table('operator_payouts',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('delivery_id', sa.UUID(), nullable=False),
    sa.Column('operator_id', sa.UUID(), nullable=False),
    sa.Column('gross_fee_cents', sa.Integer(), nullable=False),
    sa.Column('share_bps', sa.Integer(), nullable=True),
    sa.Column('amount_cents', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('provider_reference', sa.String(), nullable=True),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('rate_unconfigured','pending_review','approved','paid','cancelled')", name=op.f('ck_operator_payouts_valid_status')),
    sa.ForeignKeyConstraint(['delivery_id'], ['helm_dash_deliveries.id'], name=op.f('fk_operator_payouts_delivery_id_helm_dash_deliveries')),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], name=op.f('fk_operator_payouts_operator_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_operator_payouts')),
    sa.UniqueConstraint('delivery_id', name=op.f('uq_operator_payouts_delivery_id'))
    )
    op.create_index(op.f('ix_operator_payouts_operator_id'), 'operator_payouts', ['operator_id'], unique=False)
    op.create_table('points_transactions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=True),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('points', sa.Integer(), nullable=False),
    sa.Column('balance_after', sa.Integer(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=True),
    sa.Column('entitlement_id', sa.UUID(), nullable=True),
    sa.Column('redemption_id', sa.UUID(), nullable=True),
    sa.Column('period', sa.String(length=7), nullable=True),
    sa.Column('eligible_spend_cents', sa.Integer(), nullable=True),
    sa.Column('idempotency_key', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('earn','earn_reversal','monthly_bonus','redeem_discount','redeem_experience','redemption_reversal','profile_verification_bonus','adjustment')", name=op.f('ck_points_transactions_valid_kind')),
    sa.CheckConstraint('points <> 0', name=op.f('ck_points_transactions_points_nonzero')),
    sa.ForeignKeyConstraint(['entitlement_id'], ['discount_entitlements.id'], name=op.f('fk_points_transactions_entitlement_id_discount_entitlements'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['order_id'], ['orders.id'], name=op.f('fk_points_transactions_order_id_orders'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['redemption_id'], ['experience_redemptions.id'], name=op.f('fk_points_transactions_redemption_id_experience_redemptions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['team_id'], ['crew_teams.id'], name=op.f('fk_points_transactions_team_id_crew_teams'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_points_transactions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_points_transactions')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_points_transactions_idempotency_key'))
    )
    op.create_index(op.f('ix_points_transactions_order_id'), 'points_transactions', ['order_id'], unique=False)
    op.create_index(op.f('ix_points_transactions_period'), 'points_transactions', ['period'], unique=False)
    op.create_index(op.f('ix_points_transactions_user_id'), 'points_transactions', ['user_id'], unique=False)
    op.create_table('vessel_equipment',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('vessel_id', sa.UUID(), nullable=False),
    sa.Column('category_id', sa.UUID(), nullable=False),
    sa.Column('make', sa.String(), nullable=False),
    sa.Column('model', sa.String(), nullable=True),
    sa.Column('serial_number', sa.String(), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('origin', sa.String(), nullable=False),
    sa.Column('oem_equipment_id', sa.UUID(), nullable=True),
    sa.Column('provenance', sa.String(), nullable=False),
    sa.Column('confidence_score', sa.Numeric(precision=3, scale=2), nullable=False),
    sa.Column('verification_status', sa.String(), nullable=False),
    sa.Column('installed_on', sa.Date(), nullable=True),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("origin IN ('oem','user_added')", name=op.f('ck_vessel_equipment_valid_origin')),
    sa.CheckConstraint("verification_status IN ('unverified','pending_review','verified','rejected')", name=op.f('ck_vessel_equipment_valid_verification')),
    sa.CheckConstraint('confidence_score >= 0 AND confidence_score <= 1', name=op.f('ck_vessel_equipment_confidence_range')),
    sa.ForeignKeyConstraint(['category_id'], ['equipment_categories.id'], name=op.f('fk_vessel_equipment_category_id_equipment_categories')),
    sa.ForeignKeyConstraint(['oem_equipment_id'], ['oem_equipment.id'], name=op.f('fk_vessel_equipment_oem_equipment_id_oem_equipment'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vessel_id'], ['vessels.id'], name=op.f('fk_vessel_equipment_vessel_id_vessels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vessel_equipment'))
    )
    op.create_index(op.f('ix_vessel_equipment_vessel_id'), 'vessel_equipment', ['vessel_id'], unique=False)
    op.create_table('service_records',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('vessel_id', sa.UUID(), nullable=False),
    sa.Column('equipment_id', sa.UUID(), nullable=True),
    sa.Column('service_type', sa.String(), nullable=False),
    sa.Column('performed_on', sa.Date(), nullable=False),
    sa.Column('engine_hours', sa.Integer(), nullable=True),
    sa.Column('provider_name', sa.String(), nullable=True),
    sa.Column('cost_cents', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['equipment_id'], ['vessel_equipment.id'], name=op.f('fk_service_records_equipment_id_vessel_equipment'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vessel_id'], ['vessels.id'], name=op.f('fk_service_records_vessel_id_vessels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_records'))
    )
    op.create_index(op.f('ix_service_records_vessel_id'), 'service_records', ['vessel_id'], unique=False)
    op.create_table('service_reminders',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('vessel_id', sa.UUID(), nullable=False),
    sa.Column('equipment_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('due_on', sa.Date(), nullable=True),
    sa.Column('due_engine_hours', sa.Integer(), nullable=True),
    sa.Column('interval_months', sa.Integer(), nullable=True),
    sa.Column('interval_hours', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('source', sa.String(), server_default='owner', nullable=False),
    sa.Column('knowledge_source_id', sa.UUID(), nullable=True),
    sa.Column('last_notified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active','completed','dismissed')", name=op.f('ck_service_reminders_valid_status')),
    sa.ForeignKeyConstraint(['equipment_id'], ['vessel_equipment.id'], name=op.f('fk_service_reminders_equipment_id_vessel_equipment'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['knowledge_source_id'], ['knowledge_sources.id'], name=op.f('fk_service_reminders_knowledge_source_id_knowledge_sources'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vessel_id'], ['vessels.id'], name=op.f('fk_service_reminders_vessel_id_vessels'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_service_reminders'))
    )
    op.create_index(op.f('ix_service_reminders_vessel_id'), 'service_reminders', ['vessel_id'], unique=False)

    # ------------------------------------------------------------------ users
    op.add_column("users", sa.Column("role", sa.String(), server_default="customer", nullable=False))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_check_constraint(
        "ck_users_valid_role", "users", "role IN ('customer','operator','dispatcher','admin')")

    # ------------------------------------------------------------------ products
    _audit(
        "migration_clamp_negative_stock", "product",
        "SELECT id::text AS entity_id, jsonb_build_object('stock_quantity', stock_quantity) AS detail "
        "FROM products WHERE stock_quantity < 0",
    )
    op.execute("UPDATE products SET stock_quantity = 0 WHERE stock_quantity < 0")
    op.add_column("products", sa.Column("price_cents", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("sale_price_cents", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("cost_price_cents", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE products SET
          price_cents = ROUND(price * 100)::int,
          sale_price_cents = CASE WHEN sale_price IS NOT NULL AND sale_price > 0 AND sale_price < price
                                  THEN ROUND(sale_price * 100)::int END,
          cost_price_cents = CASE WHEN cost_price IS NOT NULL THEN ROUND(cost_price * 100)::int END
        """
    )
    op.alter_column("products", "price_cents", nullable=False)
    op.drop_column("products", "sale_price")
    op.drop_column("products", "cost_price")
    op.drop_column("products", "price")
    op.add_column("products", sa.Column("oem_part_numbers", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))
    op.add_column("products", sa.Column("part_role", sa.String(), nullable=True))
    op.add_column("products", sa.Column("fitment_scope", sa.String(), server_default="unspecified", nullable=False))
    op.add_column("products", sa.Column("dangerous_goods", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("products", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.execute(
        "UPDATE products SET fitment_scope = 'specific' WHERE id IN (SELECT product_id FROM product_compatibility)"
    )
    op.alter_column("products", "stock_quantity", server_default="0")
    op.alter_column("products", "is_active", server_default=sa.text("true"))
    op.alter_column("products", "created_at", server_default=sa.text("now()"))
    op.create_index("ix_products_part_role", "products", ["part_role"])
    op.create_check_constraint(
        "ck_products_price_positive", "products", "price_cents > 0")
    op.create_check_constraint(
        "ck_products_sale_price_valid", "products",
        "sale_price_cents IS NULL OR (sale_price_cents > 0 AND sale_price_cents < price_cents)",
    )
    op.create_check_constraint(
        "ck_products_stock_nonnegative", "products", "stock_quantity >= 0")
    op.create_check_constraint(
        "ck_products_valid_fitment_scope", "products", "fitment_scope IN ('universal','specific','unspecified')"
    )

    # ------------------------------------------------------------------ fitment rules
    op.add_column("product_compatibility", sa.Column("engine_year_from", sa.Integer(), nullable=True))
    op.add_column("product_compatibility", sa.Column("engine_year_to", sa.Integer(), nullable=True))
    op.add_column("product_compatibility", sa.Column("equipment_category_id", sa.UUID(), nullable=True))
    op.add_column("product_compatibility", sa.Column("equipment_make", sa.String(), nullable=True))
    op.add_column("product_compatibility", sa.Column("equipment_model", sa.String(), nullable=True))
    op.add_column("product_compatibility", sa.Column("fitment_type", sa.String(), server_default="service_part", nullable=False))
    op.add_column("product_compatibility", sa.Column("verification_status", sa.String(), server_default="unverified", nullable=False))
    op.add_column("product_compatibility", sa.Column("confidence_score", sa.Numeric(precision=3, scale=2), server_default="0.30", nullable=False))
    op.add_column("product_compatibility", sa.Column("data_source", sa.String(), nullable=True))
    op.add_column("product_compatibility", sa.Column("source_url", sa.String(), nullable=True))
    op.add_column("product_compatibility", sa.Column("verified_by", sa.UUID(), nullable=True))
    op.add_column("product_compatibility", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("product_compatibility", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.execute("UPDATE product_compatibility SET data_source = 'legacy_unverified'")
    _audit(
        "migration_remove_unscoped_fitment_rule", "product_compatibility",
        "SELECT id::text AS entity_id, to_jsonb(pc.*) AS detail FROM product_compatibility pc "
        "WHERE vessel_make IS NULL AND engine_make IS NULL",
    )
    op.execute("DELETE FROM product_compatibility WHERE vessel_make IS NULL AND engine_make IS NULL")
    op.create_index("ix_product_compatibility_product_id", "product_compatibility", ["product_id"])
    op.create_foreign_key(
        "fk_product_compatibility_equipment_category",
        "product_compatibility", "equipment_categories", ["equipment_category_id"], ["id"],
    )
    op.create_check_constraint(
        "ck_product_compatibility_valid_verification", "product_compatibility",
        "verification_status IN ('unverified','verified','rejected')",
    )
    op.create_check_constraint(
        "ck_product_compatibility_confidence_range", "product_compatibility", "confidence_score >= 0 AND confidence_score <= 1"
    )
    op.create_check_constraint(
        "ck_product_compatibility_has_scope", "product_compatibility",
        "vessel_make IS NOT NULL OR engine_make IS NOT NULL OR equipment_category_id IS NOT NULL",
    )

    # ------------------------------------------------------------------ vessels
    op.add_column("vessels", sa.Column("hin_status", sa.String(), nullable=True))
    op.add_column("vessels", sa.Column("hin_decoded", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("vessels", sa.Column("model_year_id", sa.UUID(), nullable=True))
    op.add_column("vessels", sa.Column("propulsion_type", sa.String(), nullable=True))
    op.add_column("vessels", sa.Column("engine_year", sa.Integer(), nullable=True))
    op.add_column("vessels", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.alter_column("vessels", "length_ft", existing_type=sa.INTEGER(), type_=sa.Numeric(precision=5, scale=1), existing_nullable=True)
    op.alter_column("vessels", "is_primary", server_default=sa.text("false"))
    op.alter_column("vessels", "created_at", server_default=sa.text("now()"))
    op.execute("UPDATE vessels SET hin_status = 'unverified' WHERE hin IS NOT NULL AND hin <> ''")
    op.create_foreign_key(
        "fk_vessels_model_year_id_model_years", "vessels", "model_years", ["model_year_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "ck_vessels_year_range", "vessels", "year >= 1900 AND year <= 2100")
    op.create_check_constraint(
        "ck_vessels_engine_hours_nonneg", "vessels", "engine_hours IS NULL OR engine_hours >= 0")

    # ------------------------------------------------------------------ cart
    op.execute(
        """
        WITH ranked AS (
          SELECT id, user_id, product_id,
                 SUM(quantity) OVER (PARTITION BY user_id, product_id) AS total_qty,
                 ROW_NUMBER() OVER (PARTITION BY user_id, product_id ORDER BY created_at, id) AS rn
          FROM cart_items
        )
        UPDATE cart_items c SET quantity = r.total_qty FROM ranked r WHERE c.id = r.id AND r.rn = 1
        """
    )
    op.execute(
        """
        DELETE FROM cart_items WHERE id IN (
          SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY user_id, product_id
                          ORDER BY created_at, id) AS rn FROM cart_items) d WHERE d.rn > 1)
        """
    )
    op.execute("DELETE FROM cart_items WHERE quantity <= 0")
    op.add_column("cart_items", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.alter_column("cart_items", "created_at", server_default=sa.text("now()"))
    op.create_unique_constraint("uq_cart_items_user_id_product_id", "cart_items", ["user_id", "product_id"])
    op.create_check_constraint(
        "ck_cart_items_quantity_positive", "cart_items", "quantity > 0")

    # ------------------------------------------------------------------ orders
    for col in ("order_number", "idempotency_key"):
        op.add_column("orders", sa.Column(col, sa.String(), nullable=True))
    op.add_column("orders", sa.Column("payment_status", sa.String(), server_default="unpaid", nullable=False))
    op.add_column("orders", sa.Column("currency", sa.String(length=3), server_default="NZD", nullable=False))
    for col in ("subtotal_cents", "shipping_cents", "total_cents"):
        op.add_column("orders", sa.Column(col, sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("discount_cents", sa.Integer(), server_default="0", nullable=False))
    op.add_column("orders", sa.Column("refunded_cents", sa.Integer(), server_default="0", nullable=False))
    op.add_column("orders", sa.Column("delivery_quote_id", sa.UUID(), nullable=True))
    op.add_column("orders", sa.Column("pickup_location", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("discount_entitlement_id", sa.UUID(), nullable=True))
    op.add_column("orders", sa.Column("payment_provider", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("payment_intent_id", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("cancel_reason", sa.String(), nullable=True))
    op.add_column("orders", sa.Column("review_reason", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.execute(
        """
        UPDATE orders SET
          order_number = 'HM-' || UPPER(SUBSTRING(REPLACE(id::text, '-', '') FROM 1 FOR 10)),
          idempotency_key = 'legacy-' || id::text,
          subtotal_cents = ROUND(subtotal * 100)::int,
          shipping_cents = ROUND(shipping_cost * 100)::int,
          total_cents = ROUND(subtotal * 100)::int + ROUND(shipping_cost * 100)::int,
          review_reason = CASE WHEN ROUND(total * 100)::int
                                    <> ROUND(subtotal * 100)::int + ROUND(shipping_cost * 100)::int
                               THEN 'Legacy total ' || total::text || ' did not equal subtotal + shipping'
                          END,
          payment_intent_id = CASE WHEN stripe_payment_intent_id LIKE 'pi_mock_%' THEN NULL
                                   ELSE stripe_payment_intent_id END,
          payment_provider = CASE WHEN stripe_payment_intent_id IS NULL
                                    OR stripe_payment_intent_id LIKE 'pi_mock_%' THEN NULL
                                  ELSE 'stripe' END
        """
    )
    # Status vocabulary. Legacy unpaid orders had stock deducted at creation and no
    # reservation; record that stock as a reservation that expires normally.
    op.execute(
        """
        UPDATE orders SET
          payment_status = CASE status
              WHEN 'paid' THEN 'succeeded' WHEN 'fulfilled' THEN 'succeeded'
              WHEN 'shipped' THEN 'succeeded' WHEN 'delivered' THEN 'succeeded'
              ELSE 'unpaid' END,
          paid_at = CASE WHEN status IN ('paid','fulfilled','shipped','delivered') THEN created_at END,
          cancelled_at = CASE WHEN status = 'cancelled' THEN created_at END,
          cancel_reason = CASE WHEN status = 'cancelled' THEN 'legacy_cancelled' END,
          review_reason = CASE WHEN status = 'cancelled'
                               THEN COALESCE(review_reason || '; ', '') ||
                                    'Legacy cancelled order: payment/refund outcome and restock not recorded'
                               ELSE review_reason END,
          expires_at = CASE WHEN status = 'pending' THEN now() END,
          status = CASE status
              WHEN 'pending' THEN 'pending_payment' WHEN 'fulfilled' THEN 'ready_for_dispatch'
              WHEN 'shipped' THEN 'dispatched' WHEN 'paid' THEN 'paid'
              WHEN 'delivered' THEN 'delivered' WHEN 'cancelled' THEN 'cancelled'
              ELSE 'payment_review' END
        """
    )
    op.execute(
        """
        INSERT INTO stock_reservations (id, order_id, product_id, quantity, status, created_at, updated_at)
        SELECT gen_random_uuid(), oi.order_id, oi.product_id, SUM(oi.quantity),
               CASE WHEN o.status = 'pending_payment' THEN 'reserved'
                    WHEN o.status = 'cancelled' THEN 'released'
                    ELSE 'consumed' END,
               now(), now()
        FROM order_items oi JOIN orders o ON o.id = oi.order_id
        GROUP BY oi.order_id, oi.product_id, o.status
        """
    )
    for col in ("order_number", "idempotency_key", "subtotal_cents", "shipping_cents", "total_cents"):
        op.alter_column("orders", col, nullable=False)
    op.drop_column("orders", "shipping_cost")
    op.drop_column("orders", "subtotal")
    op.drop_column("orders", "total")
    op.drop_column("orders", "stripe_payment_intent_id")
    op.alter_column("orders", "created_at", server_default=sa.text("now()"))
    op.create_unique_constraint("uq_orders_order_number", "orders", ["order_number"])
    op.create_unique_constraint("uq_orders_payment_intent_id", "orders", ["payment_intent_id"])
    op.create_unique_constraint("uq_orders_user_id_idempotency_key", "orders", ["user_id", "idempotency_key"])
    op.create_foreign_key(
        "fk_orders_discount_entitlement_id", "orders", "discount_entitlements",
        ["discount_entitlement_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_orders_delivery_quote_id_delivery_quotes", "orders", "delivery_quotes",
        ["delivery_quote_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_orders_valid_status", "orders",
        "status IN ('pending_payment','paid','ready_for_dispatch','dispatched','delivered',"
        "'collected','cancelled','expired','refunded','payment_review')",
    )
    op.create_check_constraint(
        "ck_orders_valid_payment_status", "orders",
        "payment_status IN ('unpaid','requires_action','processing','failed','succeeded',"
        "'partially_refunded','refunded')",
    )
    op.create_check_constraint(
        "ck_orders_valid_delivery_type", "orders",
        "delivery_type IS NULL OR delivery_type IN ('courier','helm_dash','click_and_collect')",
    )
    op.create_check_constraint(
        "ck_orders_amounts_valid", "orders",
        "subtotal_cents >= 0 AND discount_cents >= 0 AND shipping_cents >= 0 AND total_cents >= 0 "
        "AND refunded_cents >= 0 AND refunded_cents <= total_cents",
    )
    op.create_check_constraint(
        "ck_orders_total_consistent", "orders", "total_cents = subtotal_cents - discount_cents + shipping_cents"
    )

    op.create_foreign_key(
        "fk_delivery_quotes_used_by_order_id_orders", "delivery_quotes", "orders",
        ["used_by_order_id"], ["id"], ondelete="SET NULL",
    )

    # ------------------------------------------------------------------ order items
    op.add_column("order_items", sa.Column("product_name", sa.String(), nullable=True))
    op.add_column("order_items", sa.Column("sku", sa.String(), nullable=True))
    for col in ("list_price_cents", "unit_price_cents", "line_total_cents"):
        op.add_column("order_items", sa.Column(col, sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE order_items oi SET
          product_name = p.name, sku = p.sku,
          unit_price_cents = ROUND(oi.unit_price * 100)::int,
          list_price_cents = ROUND(oi.unit_price * 100)::int,
          line_total_cents = ROUND(oi.unit_price * 100)::int * oi.quantity
        FROM products p WHERE p.id = oi.product_id
        """
    )
    for col in ("product_name", "sku", "list_price_cents", "unit_price_cents", "line_total_cents"):
        op.alter_column("order_items", col, nullable=False)
    op.drop_column("order_items", "unit_price")
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_check_constraint(
        "ck_order_items_quantity_positive", "order_items", "quantity > 0")
    op.create_check_constraint(
        "ck_order_items_line_total_consistent", "order_items", "line_total_cents = unit_price_cents * quantity"
    )

    # ------------------------------------------------------------------ helm dash
    op.add_column("helm_dash_deliveries", sa.Column("area_id", sa.String(), nullable=True))
    op.add_column("helm_dash_deliveries", sa.Column("delivery_fee_cents", sa.Integer(), nullable=True))
    for col in ("assigned_at", "accepted_at", "picked_up_at", "delivered_at"):
        op.add_column("helm_dash_deliveries", sa.Column(col, sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE helm_dash_deliveries SET delivery_fee_cents = ROUND(delivery_fee * 100)::int")
    op.alter_column("helm_dash_deliveries", "delivery_fee_cents", nullable=False)
    op.drop_column("helm_dash_deliveries", "delivery_fee")
    op.execute(
        """
        UPDATE helm_dash_deliveries SET status = CASE status
          WHEN 'pending' THEN 'awaiting_dispatch' WHEN 'pickup' THEN 'picked_up'
          WHEN 'assigned' THEN 'assigned' WHEN 'en_route' THEN 'en_route'
          WHEN 'delivered' THEN 'delivered' WHEN 'cancelled' THEN 'cancelled'
          ELSE 'failed' END
        """
    )
    op.execute(
        "UPDATE helm_dash_deliveries SET operator_id = NULL "
        "WHERE operator_id IS NOT NULL AND operator_id NOT IN (SELECT id FROM users)"
    )
    op.alter_column(
        "helm_dash_deliveries", "nautical_miles",
        existing_type=sa.NUMERIC(precision=6, scale=2), type_=sa.Numeric(precision=7, scale=2), existing_nullable=True,
    )
    op.alter_column("helm_dash_deliveries", "created_at", server_default=sa.text("now()"))
    op.alter_column("helm_dash_deliveries", "updated_at", server_default=sa.text("now()"))
    op.create_index("ix_helm_dash_deliveries_operator_id", "helm_dash_deliveries", ["operator_id"])
    op.create_foreign_key("fk_helm_dash_deliveries_operator_id_users", "helm_dash_deliveries", "users", ["operator_id"], ["id"])
    op.create_foreign_key(
        "fk_helm_dash_deliveries_area_id_operating_areas", "helm_dash_deliveries", "operating_areas", ["area_id"], ["id"]
    )
    for uc in sa.inspect(op.get_bind()).get_unique_constraints("helm_dash_deliveries"):
        if uc["column_names"] == ["order_id"] and uc["name"] != "uq_helm_dash_deliveries_order_id":
            op.execute(f'ALTER TABLE helm_dash_deliveries RENAME CONSTRAINT "{uc["name"]}" '
                       "TO uq_helm_dash_deliveries_order_id")
    op.create_check_constraint(
        "ck_helm_dash_deliveries_valid_status", "helm_dash_deliveries",
        "status IN ('awaiting_dispatch','assigned','accepted','picked_up','en_route','delivered','failed','cancelled')",
    )

    # ------------------------------------------------------------------ loyalty
    _audit(
        "migration_drop_crew_wallet_balance", "crew_team",
        "SELECT id::text AS entity_id, jsonb_build_object('crew_wallet_balance', crew_wallet_balance) AS detail "
        "FROM crew_teams WHERE crew_wallet_balance <> 0",
    )
    op.drop_column("crew_teams", "crew_wallet_balance")
    op.alter_column("crew_teams", "created_at", server_default=sa.text("now()"))
    _audit(
        "migration_remove_extra_crew_membership", "crew_team_member",
        """SELECT user_id::text AS entity_id, jsonb_build_object('team_id', team_id, 'joined_at', joined_at) AS detail
           FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY joined_at, team_id) AS rn
                 FROM crew_team_members) m WHERE m.rn > 1""",
    )
    op.execute(
        """
        DELETE FROM crew_team_members WHERE (team_id, user_id) IN (
          SELECT team_id, user_id FROM (
            SELECT team_id, user_id, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY joined_at, team_id) AS rn
            FROM crew_team_members) m WHERE m.rn > 1)
        """
    )
    op.add_column("crew_team_members", sa.Column("role", sa.String(), server_default="member", nullable=False))
    op.execute(
        "UPDATE crew_team_members m SET role = 'captain' FROM crew_teams t "
        "WHERE t.id = m.team_id AND t.created_by = m.user_id"
    )
    op.alter_column("crew_team_members", "joined_at", server_default=sa.text("now()"))
    op.create_unique_constraint("uq_crew_team_members_user_id", "crew_team_members", ["user_id"])

    op.add_column("crew_points", sa.Column("lifetime_earned", sa.Integer(), server_default="0", nullable=False))
    op.execute("UPDATE crew_points SET points_balance = 0 WHERE points_balance < 0")
    op.execute("UPDATE crew_points SET lifetime_earned = points_balance")
    op.alter_column("crew_points", "points_balance", server_default="0")
    op.alter_column("crew_points", "tier", server_default="deckhand")
    op.alter_column("crew_points", "updated_at", server_default=sa.text("now()"))
    op.create_check_constraint(
        "ck_crew_points_balance_nonnegative", "crew_points", "points_balance >= 0")
    op.execute(
        """
        INSERT INTO points_transactions (id, user_id, kind, points, balance_after, idempotency_key, description, created_at)
        SELECT gen_random_uuid(), user_id, 'adjustment', points_balance, points_balance,
               'legacy-opening-balance:' || user_id::text, 'Balance carried forward from the previous system', now()
        FROM crew_points WHERE points_balance > 0
        """
    )

    # ------------------------------------------------------------------ AI / RAG
    op.add_column("ai_conversations", sa.Column("title", sa.String(), nullable=True))
    _drop_fk("ai_conversations", "vessel_id")
    op.create_foreign_key(
        "fk_ai_conversations_vessel_id_vessels", "ai_conversations", "vessels", ["vessel_id"], ["id"], ondelete="SET NULL"
    )
    op.alter_column("ai_conversations", "messages", server_default="[]")
    op.alter_column("ai_conversations", "created_at", server_default=sa.text("now()"))
    op.alter_column("ai_conversations", "updated_at", server_default=sa.text("now()"))
    # Legacy chunks have no admitted source and are therefore never retrieved.
    op.add_column("rag_documents", sa.Column("source_id", sa.UUID(), nullable=True))
    op.add_column("rag_documents", sa.Column("chunk_index", sa.Integer(), server_default="0", nullable=False))
    op.add_column("rag_documents", sa.Column("heading", sa.String(), nullable=True))
    op.add_column("rag_documents", sa.Column("embedding_model", sa.String(), nullable=True))
    op.alter_column("rag_documents", "created_at", server_default=sa.text("now()"))
    op.create_index("ix_rag_documents_source_id", "rag_documents", ["source_id"])
    op.create_foreign_key(
        "fk_rag_documents_source_id_knowledge_sources", "rag_documents", "knowledge_sources",
        ["source_id"], ["id"], ondelete="CASCADE",
    )
    op.execute(
        "CREATE INDEX ix_rag_documents_embedding_hnsw ON rag_documents "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # ------------------------------------------------------------------ checklists
    _audit(
        "migration_remove_duplicate_checklist", "voyage_checklist",
        """SELECT id::text AS entity_id, jsonb_build_object('vessel_id', vessel_id, 'tier', tier) AS detail
           FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY vessel_id, tier ORDER BY created_at, id) AS rn
                 FROM voyage_checklists) c WHERE c.rn > 1""",
    )
    op.execute(
        """
        DELETE FROM voyage_checklists WHERE id IN (
          SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY vessel_id, tier ORDER BY created_at, id) AS rn
                          FROM voyage_checklists) c WHERE c.rn > 1)
        """
    )
    op.execute(
        "DELETE FROM voyage_checklists WHERE tier NOT IN ('grab_and_go','coastal_cruising','offshore_passage')"
    )
    op.add_column("voyage_checklists", sa.Column("template_version", sa.String(), nullable=True))
    op.execute("UPDATE voyage_checklists SET template_version = 'legacy'")
    op.alter_column("voyage_checklists", "created_at", server_default=sa.text("now()"))
    op.create_index("ix_voyage_checklists_vessel_id", "voyage_checklists", ["vessel_id"])
    op.create_unique_constraint("uq_voyage_checklists_vessel_id_tier", "voyage_checklists", ["vessel_id", "tier"])
    op.create_check_constraint(
        "ck_voyage_checklists_valid_tier", "voyage_checklists", "tier IN ('grab_and_go','coastal_cruising','offshore_passage')"
    )
    op.add_column("checklist_items", sa.Column("template_key", sa.String(), nullable=True))
    op.add_column("checklist_items", sa.Column("position", sa.Integer(), server_default="0", nullable=False))
    op.add_column("checklist_items", sa.Column("part_role", sa.String(), nullable=True))
    op.add_column("checklist_items", sa.Column("applicability", sa.String(), server_default="applies", nullable=False))
    op.add_column("checklist_items", sa.Column("link_status", sa.String(), server_default="unlinked", nullable=False))
    op.add_column("checklist_items", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True))
    # Legacy links came from name matching (or manual linking): keep, mark unverified.
    op.execute("UPDATE checklist_items SET link_status = 'user_linked_unverified' WHERE product_id IS NOT NULL")
    op.execute("UPDATE checklist_items SET quantity = 1 WHERE quantity IS NULL OR quantity < 1")
    op.alter_column("checklist_items", "quantity", server_default="1")
    op.alter_column("checklist_items", "is_checked", server_default=sa.text("false"))
    op.create_index("ix_checklist_items_checklist_id", "checklist_items", ["checklist_id"])
    _drop_fk("checklist_items", "product_id")
    op.create_foreign_key(
        "fk_checklist_items_product_id_products", "checklist_items", "products", ["product_id"], ["id"], ondelete="SET NULL"
    )
    op.create_check_constraint(
        "ck_checklist_items_valid_link_status", "checklist_items",
        "link_status IN ('verified_fit','universal','user_linked_unverified','unlinked')",
    )
    op.create_check_constraint(
        "ck_checklist_items_quantity_positive", "checklist_items", "quantity > 0")

    # ------------------------------------------------------------------ users timestamps
    op.alter_column("users", "created_at", server_default=sa.text("now()"))


def downgrade() -> None:
    raise RuntimeError(
        "0002 transforms data irreversibly (amount units, statuses, memberships). "
        "Roll back by restoring the pre-upgrade backup taken by deploy/deploy.sh "
        "(see docs/08_delivery/Operations_Runbook.md)."
    )
