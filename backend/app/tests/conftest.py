"""Test configuration and fixtures."""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, Text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

from app.database import Base, get_db
from app.models.user import User
from app.models.vessel import Vessel
from app.models.product import Product, ProductCompatibility
from app.models.cart import CartItem

# Register JSONB and UUID type adapters for SQLite
from sqlalchemy import JSON, String
from sqlalchemy.dialects import sqlite

sqlite.dialect.colspecs = {
    **getattr(sqlite.dialect, 'colspecs', {}),
}

# Monkey-patch JSONB to render as JSON in SQLite
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

_orig_visit = SQLiteTypeCompiler.__class__


def _visit_JSONB(self, type_, **kw):
    return "JSON"


def _visit_UUID(self, type_, **kw):
    return "VARCHAR(36)"


SQLiteTypeCompiler.visit_JSONB = _visit_JSONB
SQLiteTypeCompiler.visit_UUID = _visit_UUID


# Use SQLite for testing (in-memory)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


@event.listens_for(test_engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test and drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Mock auth to return a fixed user ID
TEST_USER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


async def mock_get_current_user_id() -> uuid.UUID:
    return TEST_USER_ID


# Import app after defining overrides to avoid import-time issues
from app.middleware.auth import get_current_user_id  # noqa: E402
from app.main import app  # noqa: E402

app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_current_user_id] = mock_get_current_user_id


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for testing."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer test-token"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a database session for test setup."""
    async with TestSessionLocal() as session:
        yield session
        await session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        id=TEST_USER_ID,
        email="skipper@helm.co.nz",
        full_name="Test Skipper",
        phone="+64211234567",
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def test_vessel(db_session: AsyncSession, test_user: User) -> Vessel:
    """Create a test vessel."""
    vessel = Vessel(
        user_id=test_user.id,
        nickname="My Stabi",
        make="Stabicraft",
        model="2250 Ultracab",
        year=2022,
        hull_type="aluminium",
        engine_make="Yamaha",
        engine_model="F200XCA",
        engine_hours=150,
        is_primary=True,
    )
    db_session.add(vessel)
    await db_session.commit()
    return vessel


@pytest_asyncio.fixture
async def test_product(db_session: AsyncSession) -> Product:
    """Create a test product."""
    product = Product(
        sku="YAM-OIL-10W30-4L",
        name="Yamalube 4M 10W-30 Marine Engine Oil 4L",
        description="Premium marine engine oil for Yamaha outboard motors",
        brand="Yamaha",
        category="Engine Parts",
        sub_category="Oil & Lubricants",
        price=62.90,
        cost_price=38.00,
        stock_quantity=50,
        weight_grams=4200,
    )
    db_session.add(product)
    await db_session.commit()

    # Add compatibility
    compat = ProductCompatibility(
        product_id=product.id,
        vessel_make="Stabicraft",
        vessel_model="2250 Ultracab",
        year_from=2018,
        year_to=2026,
        engine_make="Yamaha",
        engine_model="F200XCA",
    )
    db_session.add(compat)
    await db_session.commit()

    return product
