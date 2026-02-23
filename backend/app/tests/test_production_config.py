"""Tests for Phase 7 — Production configuration validation."""

import os

import pytest


@pytest.mark.asyncio
async def test_dockerfile_prod_exists():
    """Production Dockerfile should exist."""
    dockerfile_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "Dockerfile.prod"
    )
    assert os.path.exists(dockerfile_path), "Dockerfile.prod not found"


@pytest.mark.asyncio
async def test_dockerfile_prod_has_multistage_build():
    """Production Dockerfile should use multi-stage build."""
    dockerfile_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "Dockerfile.prod"
    )
    with open(dockerfile_path) as f:
        content = f.read()

    assert "AS builder" in content, "Missing builder stage"
    assert "AS production" in content, "Missing production stage"


@pytest.mark.asyncio
async def test_dockerfile_prod_runs_tests():
    """Builder stage should run pytest to catch regressions."""
    dockerfile_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "Dockerfile.prod"
    )
    with open(dockerfile_path) as f:
        content = f.read()

    assert "pytest" in content, "Tests not run in Dockerfile build"


@pytest.mark.asyncio
async def test_dockerfile_prod_uses_nonroot_user():
    """Production image should run as non-root user."""
    dockerfile_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "Dockerfile.prod"
    )
    with open(dockerfile_path) as f:
        content = f.read()

    assert "useradd" in content or "USER" in content, "No non-root user configured"
    assert "USER appuser" in content, "Should run as appuser"


@pytest.mark.asyncio
async def test_dockerfile_prod_uses_gunicorn():
    """Production image should use gunicorn with uvicorn workers."""
    dockerfile_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "Dockerfile.prod"
    )
    with open(dockerfile_path) as f:
        content = f.read()

    assert "gunicorn" in content, "Should use gunicorn"
    assert "UvicornWorker" in content, "Should use UvicornWorker"


@pytest.mark.asyncio
async def test_docker_compose_prod_exists():
    """Production docker-compose should exist."""
    compose_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "docker-compose.prod.yml"
    )
    assert os.path.exists(compose_path), "docker-compose.prod.yml not found"


@pytest.mark.asyncio
async def test_docker_compose_prod_uses_env_file():
    """Production compose should use .env.prod instead of hardcoded values."""
    compose_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "docker-compose.prod.yml"
    )
    with open(compose_path) as f:
        content = f.read()

    assert "env_file" in content, "Should use env_file directive"
    assert ".env.prod" in content, "Should reference .env.prod"


@pytest.mark.asyncio
async def test_docker_compose_prod_has_restart_policy():
    """Production compose services should have restart policies."""
    compose_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "docker-compose.prod.yml"
    )
    with open(compose_path) as f:
        content = f.read()

    assert "restart:" in content, "Should have restart policy"
    assert "unless-stopped" in content, "Should use unless-stopped restart policy"


@pytest.mark.asyncio
async def test_docker_compose_prod_no_volume_mounts():
    """Production compose should not mount source code volumes."""
    compose_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "docker-compose.prod.yml"
    )
    with open(compose_path) as f:
        content = f.read()

    assert "./backend:/app" not in content, "Should not mount source code in production"


@pytest.mark.asyncio
async def test_build_script_exists():
    """Build script should exist and be executable."""
    script_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "scripts", "build.sh"
    )
    assert os.path.exists(script_path), "build.sh not found"
    assert os.access(script_path, os.X_OK), "build.sh should be executable"
