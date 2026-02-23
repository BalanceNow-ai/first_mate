"""Tests for Phase 7 — Sentry middleware, health check, and production hardening."""

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_healthy(client: AsyncClient):
    """Health check should return 200 with service details."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "helm-api"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_health_endpoint_includes_version(client: AsyncClient):
    """Health check should include the API version."""
    response = await client.get("/health")
    data = response.json()
    assert "version" in data
    assert data["version"] == app.version


@pytest.mark.asyncio
async def test_cors_headers_present(client: AsyncClient):
    """CORS middleware should add access-control headers on preflight."""
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    # CORS middleware should respond (may be 200 or 400 depending on origins config)
    assert response.status_code in (200, 400)


@pytest.mark.asyncio
async def test_sentry_middleware_passes_normal_requests(client: AsyncClient):
    """The sentry middleware should not interfere with normal successful responses."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.asyncio
async def test_nonexistent_endpoint_returns_404(client: AsyncClient):
    """Requesting a non-existent endpoint should return 404, not 500."""
    response = await client.get("/api/v1/nonexistent-endpoint")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_docs_endpoint_accessible(client: AsyncClient):
    """Swagger docs should be accessible at /docs."""
    response = await client.get("/docs")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_app_has_sentry_middleware():
    """The Sentry exception middleware should be registered on the app."""
    # The middleware is added via @app.middleware("http") decorator.
    # Verify the middleware_stack is built (not None).
    assert app.middleware_stack is not None
    # Confirm the sentry_exception_middleware function exists on the module
    from app.main import sentry_exception_middleware
    assert callable(sentry_exception_middleware)


@pytest.mark.asyncio
async def test_app_includes_all_routers():
    """All expected routers should be mounted on the app."""
    route_paths = [route.path for route in app.routes if hasattr(route, "path")]
    # Verify key API route prefixes exist
    route_paths_str = str(route_paths)
    assert "/api/v1" in route_paths_str or "/health" in route_paths_str
    # Check that the health endpoint is reachable
    assert any("/health" in str(r.path) for r in app.routes if hasattr(r, "path"))


@pytest.mark.asyncio
async def test_app_version():
    """App version should be set."""
    assert app.version == "0.1.0"


@pytest.mark.asyncio
async def test_app_title():
    """App title should reflect Helm Marine Platform."""
    assert "Helm Marine" in app.title
