"""Fixed-window rate limiting shared across workers (Redis) or per-process (memory).

Keys are the verified token subject when available, otherwise the client address as
seen by the ASGI server (run uvicorn/gunicorn with ``--forwarded-allow-ips`` set to the
reverse proxy only, so ``X-Forwarded-For`` cannot be spoofed by clients).
"""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from app.config import get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)


class _MemoryBackend:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def hit(self, key: str, window: int) -> int:
        now = time.monotonic()
        async with self._lock:
            count, reset = self._counts.get(key, (0, now + window))
            if now >= reset:
                count, reset = 0, now + window
            count += 1
            self._counts[key] = (count, reset)
            if len(self._counts) > 50_000:  # bound memory
                self._counts = {k: v for k, v in self._counts.items() if v[1] > now}
            return count

    def reset(self) -> None:
        self._counts.clear()


class _RedisBackend:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis

        self._redis = redis.from_url(url, socket_timeout=1.0, socket_connect_timeout=1.0)

    async def hit(self, key: str, window: int) -> int:
        bucket = int(time.time() // window)
        rkey = f"rl:{key}:{bucket}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(rkey)
            pipe.expire(rkey, window + 1)
            count, _ = await pipe.execute()
        return int(count)


_backend: _MemoryBackend | _RedisBackend | None = None


def _get_backend() -> _MemoryBackend | _RedisBackend | None:
    global _backend
    settings = get_settings()
    if settings.rate_limit_backend == "disabled":
        return None
    if _backend is None:
        _backend = _RedisBackend(settings.redis_url) if settings.rate_limit_backend == "redis" else _MemoryBackend()
    return _backend


def reset_rate_limits() -> None:
    """Test helper."""
    if isinstance(_backend, _MemoryBackend):
        _backend.reset()


def _client_key(request: Request) -> str:
    principal = getattr(request.state, "principal", None)
    if principal is not None:
        return f"user:{principal.subject}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


async def _enforce(scope: str, key_suffix: str, limit: Callable[[], int] | int, window_seconds: int) -> None:
    backend = _get_backend()
    if backend is None:
        return
    max_hits = limit() if callable(limit) else limit
    key = f"{scope}:{key_suffix}"
    try:
        count = await backend.hit(key, window_seconds)
    except Exception:  # pragma: no cover - backend outage
        logger.error("Rate limit backend unavailable for scope %s", scope)
        if scope.startswith("ai"):
            # Fail closed for paid model calls.
            raise AppError(503, "rate_limit_unavailable", "Service temporarily unavailable") from None
        return
    if count > max_hits:
        raise AppError(
            429,
            "rate_limited",
            "Too many requests. Please wait and try again.",
            headers={"Retry-After": str(window_seconds)},
        )


def rate_limit(scope: str, limit: Callable[[], int] | int, window_seconds: int = 60):
    """Dependency factory: limit by client address (for unauthenticated endpoints)."""

    async def _dependency(request: Request) -> None:
        await _enforce(scope, _client_key(request), limit, window_seconds)

    return _dependency


def user_rate_limit(scope: str, limit: Callable[[], int] | int, window_seconds: int = 60):
    """Dependency factory: limit by verified token subject."""
    from app.middleware.auth import Principal, get_principal

    async def _dependency(principal: Annotated[Principal, Depends(get_principal)]) -> None:
        await _enforce(scope, f"user:{principal.subject}", limit, window_seconds)

    return _dependency


def auth_limit():
    return rate_limit("auth", lambda: get_settings().rate_limit_auth_per_minute)


def mutation_limit():
    return user_rate_limit("mutation", lambda: get_settings().rate_limit_mutation_per_minute)
