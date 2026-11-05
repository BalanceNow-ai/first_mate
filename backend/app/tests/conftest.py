"""Test harness: real PostgreSQL (+pgvector), real Alembic migrations, real signed tokens.

Authentication is *not* overridden. Every authenticated request carries an HS256
access token signed with the test project's server-only secret and checked for
issuer, audience, expiry and subject by the production verification code.

Set ``TEST_DATABASE_URL`` to point at a disposable database (it is truncated
between tests). Default: postgresql+asyncpg://helm:helm@localhost:5432/helm_test
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://helm:helm@localhost:5432/helm_test")
TEST_JWT_SECRET = "test-only-supabase-jwt-secret-0123456789abcdef"
TEST_ISSUER = "http://supabase.test/auth/v1"

# Configure the application *before* it is imported.
os.environ.update(
    {
        "APP_ENV": "test",
        "DATABASE_URL": TEST_DATABASE_URL,
        "AUTH_MODE": "hs256",
        "SUPABASE_URL": "http://supabase.test",
        "SUPABASE_JWT_SECRET": TEST_JWT_SECRET,
        "SUPABASE_JWT_AUDIENCE": "authenticated",
        "RATE_LIMIT_BACKEND": "memory",
        "PAYMENT_PROVIDER": "local",
        "COURIER_RATE_MODE": "rate_card",
        "HELM_DASH_ENABLED": "true",
        "AI_ENABLED": "true",
        "LLM_PROVIDER": "local_extractive",
        "EMBEDDING_PROVIDER": "local_hash",
        "CMS_PROVIDER": "local_fixture",
        "EMAIL_PROVIDER": "log_sink",
        "PUSH_PROVIDER": "log_sink",
        "SEARCH_BACKEND": "postgres",
    }
)

import jwt  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from alembic import command  # noqa: E402
from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.core.rate_limit import reset_rate_limits  # noqa: E402
from app.database import async_session, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.product import Product, ProductCompatibility  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.vessel import Vessel  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def make_token(
    sub: uuid.UUID | str,
    email: str | None = "user@example.test",
    *,
    expires_in: int = 3600,
    audience: str = "authenticated",
    issuer: str = TEST_ISSUER,
    secret: str = TEST_JWT_SECRET,
    algorithm: str = "HS256",
    extra: dict | None = None,
) -> str:
    """Create a Supabase-shaped access token."""
    now = int(time.time())
    claims = {
        "sub": str(sub),
        "aud": audience,
        "iss": issuer,
        "iat": now,
        "exp": now + expires_in,
        "role": "authenticated",
        "aal": "aal1",
        "session_id": str(uuid.uuid4()),
        "is_anonymous": False,
    }
    if email is not None:
        claims["email"] = email
    claims.update(extra or {})
    return jwt.encode(claims, secret, algorithm=algorithm)


def auth_headers(sub: uuid.UUID, email: str, **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub, email, **kwargs)}"}


@dataclass
class Actor:
    """A provisioned user plus ready-to-use request headers."""

    id: uuid.UUID
    email: str
    role: str
    headers: dict[str, str] = field(repr=False)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    """Build the schema with the real migration chain once per session."""
    import asyncio

    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        await engine.dispose()

    asyncio.run(_reset())
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    command.upgrade(cfg, "head")


_TABLES: list[str] = []


@pytest_asyncio.fixture(autouse=True)
async def clean_database() -> AsyncGenerator[None, None]:
    """Truncate every application table before each test."""
    async with engine.begin() as conn:
        if not _TABLES:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'")
            )
            _TABLES.extend(r[0] for r in rows)
        await conn.execute(text(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE"))
    reset_rate_limits()
    yield


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Unauthenticated client against the real ASGI app."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
        await session.commit()


async def create_actor(role: str = "customer", email: str | None = None, full_name: str = "Test User") -> Actor:
    uid = uuid.uuid4()
    email = email or f"{role}-{uid.hex[:8]}@example.test"
    async with async_session() as s:
        s.add(User(id=uid, email=email, full_name=full_name, role=role))
        await s.commit()
    return Actor(id=uid, email=email, role=role, headers=auth_headers(uid, email))


@pytest_asyncio.fixture
async def customer() -> Actor:
    return await create_actor("customer", full_name="Casey Customer")


@pytest_asyncio.fixture
async def other_customer() -> Actor:
    return await create_actor("customer", full_name="Olive Other")


@pytest_asyncio.fixture
async def admin() -> Actor:
    return await create_actor("admin", full_name="Ada Admin")


@pytest_asyncio.fixture
async def dispatcher() -> Actor:
    return await create_actor("dispatcher", full_name="Dee Dispatcher")


@pytest_asyncio.fixture
async def operator() -> Actor:
    return await create_actor("operator", full_name="Otto Operator")


async def create_product(**overrides) -> Product:
    data = {
        "sku": f"SKU-{uuid.uuid4().hex[:8].upper()}",
        "name": "Yamalube 4M 10W-30 Marine Engine Oil 4L",
        "brand": "Yamaha",
        "category": "Engine Parts",
        "sub_category": "Oil & Lubricants",
        "price_cents": 6290,
        "stock_quantity": 50,
        "weight_grams": 4200,
        "fitment_scope": "unspecified",
    }
    data.update(overrides)
    async with async_session() as s:
        product = Product(**data)
        s.add(product)
        await s.commit()
        await s.refresh(product)
        return product


async def add_fitment_rule(product_id: uuid.UUID, **overrides) -> ProductCompatibility:
    data = {
        "engine_make": "Yamaha",
        "engine_model": "F150",
        "verification_status": "verified",
        "confidence_score": 0.9,
        "data_source": "synthetic_fixture",
    }
    data.update(overrides)
    async with async_session() as s:
        rule = ProductCompatibility(product_id=product_id, **data)
        s.add(rule)
        await s.commit()
        await s.refresh(rule)
        return rule


async def create_vessel(owner_id: uuid.UUID, **overrides) -> Vessel:
    data = {
        "nickname": "My Stabi",
        "make": "Stabicraft",
        "model": "2050 Supercab",
        "year": 2022,
        "hull_type": "aluminium",
        "propulsion_type": "outboard",
        "engine_make": "Yamaha",
        "engine_model": "F150",
        "engine_year": 2022,
        "engine_hours": 150,
        "is_primary": True,
    }
    data.update(overrides)
    async with async_session() as s:
        vessel = Vessel(user_id=owner_id, **data)
        s.add(vessel)
        await s.commit()
        await s.refresh(vessel)
        return vessel


@pytest_asyncio.fixture
async def product() -> Product:
    return await create_product()


@pytest_asyncio.fixture
async def vessel(customer: Actor) -> Vessel:
    return await create_vessel(customer.id)
