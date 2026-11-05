#!/usr/bin/env bash
# =============================================================================
# Helm — production deploy (single host, docker compose). FAILS CLOSED.
#
#   deploy/deploy.sh                 build images for the checked-out commit and deploy
#   deploy/deploy.sh --skip-build    deploy already-built images for the checked-out
#                                    commit (used for rollback to a previous release)
#
# Steps (any failure stops the deploy with a non-zero exit; nothing later runs):
#   1. preflight   .env.prod present and not world-readable, required variables set,
#                  docker compose/curl/python3 available, git tree clean and HEAD at
#                  HELM_DEPLOY_REF, TLS certificate files present
#   2. build       backend + web images tagged with the commit (HELM_IMAGE_TAG)
#   3. validate    the application's own production configuration check
#   4. backup      verified pre-migration pg_dump (deploy/backup.sh)
#   5. migrate     one-shot `alembic upgrade head`; failure -> restore instructions
#   6. start       api, worker, beat, web
#   7. readiness   /ready must report ready, then a worker heartbeat newer than this
#                  deploy; timeout -> diagnostics + rollback instructions
# "Deploy complete" is printed only after every step succeeded.
#
# Nothing deploys automatically: there is no CI/CD hook. A git push or merge changes
# nothing on the server until an operator runs this script there.
#
# Tunables (environment): HELM_READY_TIMEOUT (default 180 s), HELM_WORKER_TIMEOUT
# (default 240 s; 0 skips the heartbeat wait), HELM_ENV_FILE, HELM_COMPOSE_FILE.
# =============================================================================
set -euo pipefail
# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$HELM_ROOT"

skip_build=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --skip-build) skip_build=1; shift ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

step="startup"
on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '\n[%s] DEPLOY FAILED during step: %s (exit %s). Deploy NOT complete.\n' \
      "$(date -u +%H:%M:%S)" "$step" "$rc" >&2
  fi
}
trap on_exit EXIT

deploy_started_epoch="$(date +%s)"

# --- 1. preflight ----------------------------------------------------------------------
step="preflight"
log "preflight"
for tool in docker curl python3 git sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || die "required tool not found: $tool"
done
docker compose version >/dev/null 2>&1 || die "docker compose (v2 plugin) is not available"

[ -f "$HELM_ENV_FILE" ] || die "$HELM_ENV_FILE not found — copy .env.prod.example to .env.prod"
perms="$(stat -c '%a' "$HELM_ENV_FILE")"
[ "${perms: -1}" = "0" ] || die "$HELM_ENV_FILE is readable by other users (mode $perms); run: chmod 600 $HELM_ENV_FILE"
load_env_file

[ "${APP_ENV:-}" = "production" ] || die "APP_ENV must be production in $(basename "$HELM_ENV_FILE")"
require_vars HELM_PUBLIC_URL HELM_DEPLOY_REF HELM_BACKUP_DIR SECRET_KEY ALLOWED_ORIGINS \
  POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB REDIS_PASSWORD \
  AUTH_MODE SUPABASE_URL SUPABASE_ANON_KEY TYPESENSE_API_KEY
case "$AUTH_MODE" in
  jwks) ;;
  hs256) require_vars SUPABASE_JWT_SECRET ;;
  *) die "AUTH_MODE must be jwks or hs256" ;;
esac
[ "${PAYMENT_PROVIDER:-disabled}" != "stripe" ] || require_vars STRIPE_SECRET_KEY STRIPE_PUBLISHABLE_KEY STRIPE_WEBHOOK_SECRET
[ "${EMAIL_PROVIDER:-}" != "resend" ] || require_vars RESEND_API_KEY
if [ "${LLM_PROVIDER:-}" = "openai" ] || [ "${EMBEDDING_PROVIDER:-}" = "openai" ]; then require_vars OPENAI_API_KEY; fi
[ "${COURIER_RATE_MODE:-disabled}" != "rate_card" ] || require_vars COURIER_RATE_CARD
case "$HELM_PUBLIC_URL" in https://*) ;; *) die "HELM_PUBLIC_URL must be an https:// origin" ;; esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "$HELM_ROOT is not a git checkout"
dirty="$(git status --porcelain --untracked-files=normal)"
[ -z "$dirty" ] || die "git working tree is not clean (commit or remove local changes first):
$dirty"
head_sha="$(git rev-parse HEAD)"
ref_sha="$(git rev-parse --verify --quiet "${HELM_DEPLOY_REF}^{commit}" || true)"
[ -n "$ref_sha" ] || die "HELM_DEPLOY_REF '$HELM_DEPLOY_REF' does not resolve to a commit"
[ "$head_sha" = "$ref_sha" ] || die "HEAD ($head_sha) is not HELM_DEPLOY_REF '$HELM_DEPLOY_REF' ($ref_sha)"
export HELM_IMAGE_TAG="${head_sha:0:12}"

tls_dir="${HELM_TLS_DIR:-$HELM_ROOT/deploy/certs}"
[ -s "$tls_dir/fullchain.pem" ] && [ -s "$tls_dir/privkey.pem" ] \
  || die "TLS certificate missing: $tls_dir/fullchain.pem and privkey.pem (see Operations Runbook, HTTPS)"
compose config --quiet || die "docker compose configuration is invalid"
log "preflight ok: release $HELM_IMAGE_TAG (ref $HELM_DEPLOY_REF)"

# --- 2. build --------------------------------------------------------------------------
step="build"
if [ "$skip_build" -eq 1 ]; then
  for img in backend web; do
    docker image inspect "${HELM_IMAGE_REPO:-helm}/$img:$HELM_IMAGE_TAG" >/dev/null 2>&1 \
      || die "--skip-build: image ${HELM_IMAGE_REPO:-helm}/$img:$HELM_IMAGE_TAG does not exist"
  done
  log "build skipped: using existing images for $HELM_IMAGE_TAG"
else
  log "building images for $HELM_IMAGE_TAG"
  compose build
fi

# --- 3. validate configuration (no database access) -------------------------------------
step="validate configuration"
log "validating production configuration with the application's own checks"
compose run --rm --no-deps -T api python -c \
  'from app.config import get_settings; get_settings().validate_runtime(); print("configuration ok")'

# --- 4. backup -------------------------------------------------------------------------
step="backup"
log "starting data stores"
compose up -d --wait --wait-timeout 120 db redis typesense
backup_file="$("$HELM_ROOT/deploy/backup.sh" --label "pre-deploy-$HELM_IMAGE_TAG")"
[ -s "$backup_file" ] || die "backup did not produce a file"
log "pre-migration backup: $backup_file"

# --- 5. migrate ------------------------------------------------------------------------
step="migrate"
log "running database migrations (one-shot)"
if ! compose run --rm -T migrate; then
  cat >&2 <<EOF

MIGRATION FAILED — the deploy has stopped. The running application was not replaced
(api/worker/beat/web from the previous release are untouched if they were running).
Inspect the error above. If the database was left in a bad state, restore the
pre-migration backup (destructive, explicit):

  deploy/restore.sh --file $backup_file --confirm-restore

EOF
  exit 1
fi

# --- 6. start --------------------------------------------------------------------------
step="start services"
log "starting api, worker, beat, web"
compose up -d --no-build --remove-orphans api worker beat web

# --- 7. readiness ----------------------------------------------------------------------
step="readiness"
ready_url="http://127.0.0.1:${HELM_HTTP_PORT:-80}/ready"
ready_timeout="${HELM_READY_TIMEOUT:-180}"
worker_timeout="${HELM_WORKER_TIMEOUT:-240}"

diagnose_and_fail() {
  local reason="$1"
  printf '\n[%s] READINESS FAILED: %s\n' "$(date -u +%H:%M:%S)" "$reason" >&2
  compose ps -a >&2 || true
  compose logs --no-color --tail=60 api worker beat web >&2 || true
  curl -sS --max-time 5 "$ready_url" >&2 || true
  cat >&2 <<EOF

The new release ($HELM_IMAGE_TAG) is running but not ready. Rollback options:
  * code-only problem (migration is compatible): check out the previous release and
      git checkout <previous-ref> && HELM_DEPLOY_REF=<previous-ref> deploy/deploy.sh --skip-build
  * schema problem: restore the pre-migration backup, then redeploy the previous release
      deploy/restore.sh --file $backup_file --confirm-restore
      git checkout <previous-ref> && HELM_DEPLOY_REF=<previous-ref> deploy/deploy.sh --skip-build
EOF
  exit 1
}

log "waiting for $ready_url (timeout ${ready_timeout}s)"
deadline=$(( $(date +%s) + ready_timeout ))
until body="$(curl -fsS --max-time 5 "$ready_url" 2>/dev/null)" \
      && python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("ready") is True else 1)' "$body"; do
  [ "$(date +%s)" -lt "$deadline" ] || diagnose_and_fail "/ready did not report ready within ${ready_timeout}s"
  sleep 3
done
log "API ready"

if [ "$worker_timeout" -gt 0 ]; then
  log "waiting for a worker heartbeat newer than this deploy (timeout ${worker_timeout}s)"
  deadline=$(( $(date +%s) + worker_timeout ))
  until body="$(curl -fsS --max-time 5 "$ready_url" 2>/dev/null)" \
        && python3 - "$body" "$deploy_started_epoch" <<'PY'
import json, sys
from datetime import datetime
body, started = json.loads(sys.argv[1]), int(sys.argv[2])
beat = body.get("checks", {}).get("workers", {}).get("celery")
ok = bool(beat) and beat.get("fresh") is True and datetime.fromisoformat(beat["last_seen_at"]).timestamp() >= started
sys.exit(0 if ok else 1)
PY
  do
    [ "$(date +%s)" -lt "$deadline" ] || diagnose_and_fail "no worker/beat heartbeat within ${worker_timeout}s"
    sleep 5
  done
  log "worker and beat heartbeat confirmed"
fi

step="record"
printf '%s release=%s ref=%s backup=%s\n' "$(date -u +%FT%TZ)" "$HELM_IMAGE_TAG" "$HELM_DEPLOY_REF" "$backup_file" \
  >> "$HELM_BACKUP_DIR/deploy-history.log"
printf '\nDeploy complete: release %s is ready (backup %s)\n' "$HELM_IMAGE_TAG" "$backup_file"
