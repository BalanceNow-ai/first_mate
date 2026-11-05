"""Migration proofs: clean install, Phase-7 upgrade with data, and no model drift."""

import asyncio
import os
import uuid

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.database import Base
from app.tests.conftest import BACKEND_DIR, TEST_DATABASE_URL

_BASE, _TEST_DB = TEST_DATABASE_URL.rsplit("/", 1)
MIGRATION_DB_NAME = f"{_TEST_DB}_migration"
MIGRATION_DB = f"{_BASE}/{MIGRATION_DB_NAME}"
ADMIN_DB = f"{_BASE}/postgres"


def _alembic(target: str) -> None:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = MIGRATION_DB
    command.upgrade(cfg, target)


async def _recreate_db() -> None:
    admin = create_async_engine(ADMIN_DB, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {MIGRATION_DB_NAME} WITH (FORCE)"))
        await conn.execute(text(f"CREATE DATABASE {MIGRATION_DB_NAME}"))
    await admin.dispose()


async def _exec(sql: str, **params):
    eng = create_async_engine(MIGRATION_DB, poolclass=NullPool)
    async with eng.begin() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.mappings().all() if result.returns_rows else None
    await eng.dispose()
    return rows


def _run(coro):
    return asyncio.run(coro)


U1, U2 = uuid.uuid4(), uuid.uuid4()
P1, P2, P3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
O_PENDING, O_PAID, O_CANCELLED, O_FULFILLED = (uuid.uuid4() for _ in range(4))
T1, T2 = uuid.uuid4(), uuid.uuid4()
V1 = uuid.uuid4()
C1, C2 = uuid.uuid4(), uuid.uuid4()

LEGACY_DATA = f"""
INSERT INTO users (id, email, full_name, created_at) VALUES
  ('{U1}', 'skipper@example.test', 'Legacy Skipper', now()),
  ('{U2}', 'mate@example.test', NULL, now());
INSERT INTO products (id, sku, name, category, price, sale_price, cost_price, stock_quantity, is_active, created_at) VALUES
  ('{P1}', 'OIL-1', 'Engine Oil', 'Engine', 62.90, 49.95, 38.00, 10, true, now()),
  ('{P2}', 'PLUG-1', 'Spark Plug', 'Engine', 12.345, 12.345, NULL, -2, true, now()),
  ('{P3}', 'TAPE-1', 'Duct Tape', 'General', 9.99, NULL, NULL, 5, true, now());
INSERT INTO product_compatibility (id, product_id, vessel_make, vessel_model, engine_make) VALUES
  (gen_random_uuid(), '{P1}', 'Stabicraft', '2050', 'Yamaha'),
  (gen_random_uuid(), '{P3}', NULL, NULL, NULL);
INSERT INTO vessels (id, user_id, nickname, make, model, year, length_ft, hin, is_primary, created_at) VALUES
  ('{V1}', '{U1}', 'Legacy Boat', 'Stabicraft', '2050', 2021, 20, 'ABC12345D101', true, now());
INSERT INTO cart_items (id, user_id, product_id, quantity, created_at) VALUES
  (gen_random_uuid(), '{U1}', '{P1}', 1, now() - interval '1 hour'),
  (gen_random_uuid(), '{U1}', '{P1}', 2, now()),
  (gen_random_uuid(), '{U1}', '{P3}', 0, now());
INSERT INTO orders (id, user_id, status, subtotal, shipping_cost, total, stripe_payment_intent_id, delivery_type, created_at) VALUES
  ('{O_PENDING}', '{U1}', 'pending', 62.90, 9.90, 72.80, 'pi_mock_{O_PENDING}', 'courier', now()),
  ('{O_PAID}', '{U1}', 'paid', 100.00, 0, 100.00, 'pi_live_abc', 'click_and_collect', now()),
  ('{O_CANCELLED}', '{U2}', 'cancelled', 10.00, 5.00, 15.00, NULL, 'courier', now()),
  ('{O_FULFILLED}', '{U2}', 'fulfilled', 10.005, 0, 10.00, 'pi_live_def', 'courier', now());
INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) VALUES
  (gen_random_uuid(), '{O_PENDING}', '{P1}', 1, 62.90),
  (gen_random_uuid(), '{O_PAID}', '{P3}', 10, 10.00),
  (gen_random_uuid(), '{O_CANCELLED}', '{P3}', 1, 10.00),
  (gen_random_uuid(), '{O_FULFILLED}', '{P2}', 1, 10.005);
INSERT INTO helm_dash_deliveries (id, order_id, status, delivery_coordinates, delivery_fee, created_at, updated_at, operator_id) VALUES
  (gen_random_uuid(), '{O_PAID}', 'pickup', '{{"lat": -36.8, "lng": 174.8}}', 31.505, now(), now(), gen_random_uuid());
INSERT INTO crew_points (id, user_id, points_balance, tier, updated_at) VALUES
  (gen_random_uuid(), '{U1}', 1500, 'deckhand', now());
INSERT INTO crew_teams (id, name, created_by, crew_wallet_balance, created_at) VALUES
  ('{T1}', 'First', '{U1}', 0, now()), ('{T2}', 'Second', '{U2}', 7, now());
INSERT INTO crew_team_members (team_id, user_id, joined_at) VALUES
  ('{T1}', '{U1}', now() - interval '2 days'), ('{T2}', '{U1}', now()), ('{T2}', '{U2}', now());
INSERT INTO voyage_checklists (id, vessel_id, tier, name, created_at) VALUES
  ('{C1}', '{V1}', 'grab_and_go', 'Grab', now() - interval '1 day'),
  ('{C2}', '{V1}', 'grab_and_go', 'Grab dup', now());
INSERT INTO checklist_items (id, checklist_id, system, item_name, quantity, product_id, is_checked) VALUES
  (gen_random_uuid(), '{C1}', 'Engine', 'Spare Spark Plugs', 1, '{P2}', true);
INSERT INTO rag_documents (id, agent_domain, source, content, created_at) VALUES
  (gen_random_uuid(), 'engine', 'legacy.pdf', 'legacy chunk', now());
"""


@pytest.fixture(scope="module")
def upgraded():
    _run(_recreate_db())
    _alembic("0001")
    _run(_exec("SELECT 1"))
    for stmt in LEGACY_DATA.strip().split(";\n"):
        if stmt.strip():
            _run(_exec(stmt))
    _alembic("head")
    return True


def q(sql: str, **params):
    return _run(_exec(sql, **params))


def test_products_converted_to_cents(upgraded):
    rows = {r["sku"]: r for r in q("SELECT sku, price_cents, sale_price_cents, cost_price_cents, stock_quantity, fitment_scope FROM products")}
    assert rows["OIL-1"]["price_cents"] == 6290 and rows["OIL-1"]["sale_price_cents"] == 4995
    assert rows["OIL-1"]["cost_price_cents"] == 3800 and rows["OIL-1"]["fitment_scope"] == "specific"
    assert rows["PLUG-1"]["price_cents"] == 1235  # half-up
    assert rows["PLUG-1"]["sale_price_cents"] is None  # sale >= price cleared
    assert rows["PLUG-1"]["stock_quantity"] == 0  # clamped
    audit = q("SELECT action FROM audit_log")
    actions = {a["action"] for a in audit}
    assert {"migration_clamp_negative_stock", "migration_remove_unscoped_fitment_rule",
            "migration_remove_extra_crew_membership", "migration_drop_crew_wallet_balance",
            "migration_remove_duplicate_checklist"} <= actions


def test_fitment_rules_become_unverified(upgraded):
    rules = q("SELECT verification_status, data_source FROM product_compatibility")
    assert len(rules) == 1  # unscoped rule removed
    assert rules[0]["verification_status"] == "unverified"


def test_orders_mapped(upgraded):
    o = {str(r["id"]): r for r in q("SELECT * FROM orders")}
    pend = o[str(O_PENDING)]
    assert pend["status"] == "pending_payment" and pend["payment_status"] == "unpaid"
    assert pend["total_cents"] == 7280 and pend["payment_intent_id"] is None  # mock PI detached
    assert pend["expires_at"] is not None and pend["order_number"].startswith("HM-")
    paid = o[str(O_PAID)]
    assert paid["status"] == "paid" and paid["payment_status"] == "succeeded" and paid["payment_provider"] == "stripe"
    assert o[str(O_FULFILLED)]["status"] == "ready_for_dispatch"
    assert o[str(O_FULFILLED)]["review_reason"]  # legacy rounding discrepancy flagged
    assert o[str(O_CANCELLED)]["status"] == "cancelled" and "Legacy cancelled" in o[str(O_CANCELLED)]["review_reason"]
    res = {str(r["order_id"]): r["status"] for r in q("SELECT order_id, status FROM stock_reservations")}
    assert res[str(O_PENDING)] == "reserved" and res[str(O_PAID)] == "consumed" and res[str(O_CANCELLED)] == "released"
    items = q("SELECT product_name, unit_price_cents, line_total_cents FROM order_items WHERE order_id = :o", o=O_PAID)
    assert items[0]["product_name"] == "Duct Tape" and items[0]["line_total_cents"] == 10000


def test_cart_and_crews_deduplicated(upgraded):
    cart = q("SELECT product_id, quantity FROM cart_items")
    assert [(str(c["product_id"]), c["quantity"]) for c in cart] == [(str(P1), 3)]
    members = q("SELECT team_id, user_id, role FROM crew_team_members ORDER BY user_id")
    by_user = {str(m["user_id"]): m for m in members}
    assert str(by_user[str(U1)]["team_id"]) == str(T1) and by_user[str(U1)]["role"] == "captain"
    ledger = q("SELECT points, balance_after, kind FROM points_transactions")
    assert ledger == [{"points": 1500, "balance_after": 1500, "kind": "adjustment"}]


def test_delivery_checklist_and_rag(upgraded):
    d = q("SELECT status, delivery_fee_cents, operator_id FROM helm_dash_deliveries")[0]
    assert d["status"] == "picked_up" and d["delivery_fee_cents"] == 3151 and d["operator_id"] is None
    lists = q("SELECT id FROM voyage_checklists")
    assert [str(x["id"]) for x in lists] == [str(C1)]
    item = q("SELECT link_status, is_checked FROM checklist_items")[0]
    assert item["link_status"] == "user_linked_unverified" and item["is_checked"] is True
    rag = q("SELECT source_id FROM rag_documents")[0]
    assert rag["source_id"] is None  # never admitted -> never retrieved
    v = q("SELECT length_ft, hin_status FROM vessels")[0]
    assert float(v["length_ft"]) == 20.0 and v["hin_status"] == "unverified"


def test_models_match_migrated_schema(upgraded):
    async def _diff():
        eng = create_async_engine(MIGRATION_DB, poolclass=NullPool)
        async with eng.connect() as conn:
            diff = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
            )
        await eng.dispose()
        return diff

    assert _run(_diff()) == []
