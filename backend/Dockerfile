# syntax=docker/dockerfile:1.7
# =============================================================================
# Helm backend — DEVELOPMENT image (hot reload, dev dependencies, test suite)
#
#   docker build -t helm-backend:dev backend
#   docker run --rm -v "$PWD/backend:/app" ... helm-backend:dev          # api-dev (reload)
#   docker run --rm ... helm-backend:dev python -m pytest -q             # needs TEST_DATABASE_URL
#
# Installs from the hashed lock requirements-dev.lock. Same entrypoint roles as the
# production image (api, api-dev, migrate, worker, beat, cli). Not for deployment —
# use Dockerfile.prod.
# Optional build secret `build_ca`: extra CA bundle for TLS-intercepting proxies.
# =============================================================================
ARG PYTHON_IMAGE=python:3.11.18-slim-trixie
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    CELERY_BEAT_SCHEDULE=/tmp/celerybeat-schedule

COPY requirements-dev.lock /tmp/requirements-dev.lock
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    python -m venv /opt/venv \
    && pip install --require-hashes -r /tmp/requirements-dev.lock \
    && rm -f /tmp/requirements-dev.lock \
    && groupadd --gid 10001 helm \
    && useradd --uid 10001 --gid helm --no-create-home --home-dir /nonexistent \
         --shell /usr/sbin/nologin helm

WORKDIR /app
COPY . /app/
RUN chmod 0755 /app/docker/entrypoint.sh /app/docker/healthcheck.py

USER helm:helm
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["api-dev"]
