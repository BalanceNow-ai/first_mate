#!/usr/bin/env bash
# ============================================================
# Helm Marine — Deploy / Update script
# Usage:  bash deploy/deploy.sh          (from repo root)
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ---------- Pre-flight checks ----------
if [ ! -f .env.prod ]; then
  echo "ERROR: .env.prod not found."
  echo "Copy .env.prod.example to .env.prod and fill in your secrets."
  exit 1
fi

echo "=== Helm Marine — Deploying ==="

# ---------- Pull latest code (if in a git repo) ----------
if [ -d .git ]; then
  echo "Pulling latest changes..."
  git pull --ff-only || echo "Warning: git pull failed, deploying current code"
fi

# ---------- Build & start services ----------
echo "Building containers..."
docker compose -f docker-compose.prod.yml build

echo "Starting services..."
docker compose -f docker-compose.prod.yml up -d

# ---------- Run database migrations ----------
echo "Running database migrations..."
docker compose -f docker-compose.prod.yml exec -T api \
  python -m alembic upgrade head || echo "Warning: migrations skipped (may not be configured yet)"

# ---------- Health check ----------
echo "Waiting for API to be ready..."
for i in $(seq 1 30); do
  if curl -sf http://localhost/health > /dev/null 2>&1; then
    echo "API is healthy!"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "Warning: health check timed out — check logs with: docker compose -f docker-compose.prod.yml logs api"
  fi
  sleep 2
done

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Useful commands:"
echo "  docker compose -f docker-compose.prod.yml logs -f        # tail all logs"
echo "  docker compose -f docker-compose.prod.yml logs -f api    # tail API logs"
echo "  docker compose -f docker-compose.prod.yml ps             # service status"
echo "  docker compose -f docker-compose.prod.yml restart api    # restart API"
echo ""
