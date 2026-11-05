"""Database connection, session management and shared model helpers."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

if settings.app_env == "test":
    # Tests run many event loops; pooled asyncpg connections must not cross loops.
    engine = create_async_engine(settings.database_url, echo=settings.log_sql, poolclass=NullPool)
else:
    engine = create_async_engine(
        settings.database_url,
        echo=settings.log_sql,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
    )

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_N_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_col() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())


def updated_at_col() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional database session (commit on success)."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
