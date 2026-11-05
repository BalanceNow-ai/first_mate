#!/bin/sh
# Helm backend container entrypoint. The first argument selects the role:
#
#   api       gunicorn + uvicorn workers (never runs migrations)
#   api-dev   uvicorn with --reload (development image only)
#   migrate   one-shot `alembic upgrade head`; exits non-zero on failure
#   worker    Celery worker on the default, search and notifications queues
#   beat      Celery beat with a writable schedule file
#   cli       `python -m app.cli ...` (e.g. `cli grant-role EMAIL admin`)
#   <other>   executed as-is (e.g. `python -m pytest`)
set -eu

role="${1:-api}"
[ "$#" -gt 0 ] && shift

case "$role" in
  api)
    exec gunicorn -c /app/gunicorn.conf.py "$@" app.main:app
    ;;
  api-dev)
    exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --reload \
      --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" "$@"
    ;;
  migrate)
    echo "migrate: current revision (before):"
    alembic current
    echo "migrate: alembic upgrade head"
    alembic upgrade head "$@"
    echo "migrate: current revision (after):"
    alembic current
    echo "migrate: complete"
    ;;
  worker)
    exec celery -A app.celery_app worker \
      --loglevel="${CELERY_LOG_LEVEL:-info}" \
      --queues="${CELERY_QUEUES:-default,search,notifications}" \
      --concurrency="${CELERY_CONCURRENCY:-2}" \
      --hostname="worker@%h" \
      "$@"
    ;;
  beat)
    schedule="${CELERY_BEAT_SCHEDULE:-/var/lib/helm/beat/celerybeat-schedule}"
    mkdir -p "$(dirname "$schedule")"
    exec celery -A app.celery_app beat \
      --loglevel="${CELERY_LOG_LEVEL:-info}" \
      --schedule="$schedule" \
      --pidfile= \
      "$@"
    ;;
  cli)
    exec python -m app.cli "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
