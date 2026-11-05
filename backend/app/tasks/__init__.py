"""Celery tasks. Each module owns one domain; async work runs via ``run_async``."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

T = TypeVar("T")


def run_async(fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Run ``fn(session)`` in a fresh event loop with its own engine; commit on success."""

    async def _main() -> T:
        engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                try:
                    result = await fn(session)
                    await session.commit()
                    return result
                except Exception:
                    await session.rollback()
                    raise
        finally:
            await engine.dispose()

    return asyncio.run(_main())
