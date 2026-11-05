#!/usr/bin/env bash
# =============================================================================
# Helm — local acceptance stack helper (docker-compose.yml). Development only.
#
#   scripts/local_stack.sh up        build web bundle + images, start, wait until healthy
#   scripts/local_stack.sh web       rebuild only the Flutter web bundle (.local/web)
#   scripts/local_stack.sh down      stop the stack (keeps data volumes)
#   scripts/local_stack.sh reset --yes   stop and DELETE the local volumes (database, etc.)
#   scripts/local_stack.sh logs [service...]
#   scripts/local_stack.sh ps
#   scripts/local_stack.sh seed      run the available `python -m app.cli` seed commands
#   scripts/local_stack.sh cli ARGS  run `python -m app.cli ARGS` in a one-off container
#
# Reads .env (copy .env.example). Never prints secret values.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
LOCAL_DIR="$ROOT/.local"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")

# Seed commands looked for, in order (owned by other workstreams; missing ones are
# reported, not fatal).
SEED_COMMANDS=(seed-boats seed-catalogue seed-products seed-knowledge seed-checklists seed-operating-areas seed-rewards seed-demo)

log() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

load_env() {
  [ -f "$ROOT/.env" ] || die ".env not found — run: cp .env.example .env"
  # Same precedence as docker compose: variables already set in the shell win.
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    value="${value%\"}"; value="${value#\"}"; value="${value%\'}"; value="${value#\'}"
    [ -n "${!key+x}" ] || export "$key=$value"
  done < "$ROOT/.env"
  : "${HELM_PUBLIC_URL:?HELM_PUBLIC_URL must be set in .env}"
  : "${SUPABASE_JWT_SECRET:?SUPABASE_JWT_SECRET must be set in .env}"
  export HELM_WEB_ROOT="${HELM_WEB_ROOT:-$LOCAL_DIR/web}"
  # Compose only reads build secrets from inside the project directory.
  if [ -n "${HELM_BUILD_CA_FILE:-}" ] && [ "${HELM_BUILD_CA_FILE#"$ROOT"/}" = "$HELM_BUILD_CA_FILE" ]; then
    [ -r "$HELM_BUILD_CA_FILE" ] || die "HELM_BUILD_CA_FILE is not readable"
    mkdir -p "$LOCAL_DIR"
    cp "$HELM_BUILD_CA_FILE" "$LOCAL_DIR/build-ca.pem"
    export HELM_BUILD_CA_FILE="$LOCAL_DIR/build-ca.pem"
  fi
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

# Public anon key for the local web client: HS256 JWT with role=anon signed with the
# local GoTrue secret. The API refuses role=anon tokens; GoTrue accepts it as apikey.
anon_key() {
  if [ -n "${SUPABASE_ANON_KEY:-}" ]; then printf '%s' "$SUPABASE_ANON_KEY"; return; fi
  local now header payload sig
  now="$(date +%s)"
  header="$(printf '{"alg":"HS256","typ":"JWT"}' | b64url)"
  payload="$(printf '{"iss":"helm-local","role":"anon","iat":%s,"exp":%s}' "$now" "$((now + 315360000))" | b64url)"
  sig="$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -hmac "$SUPABASE_JWT_SECRET" -binary | b64url)"
  printf '%s.%s.%s' "$header" "$payload" "$sig"
}

use_placeholder() {
  rm -rf "$HELM_WEB_ROOT"
  mkdir -p "$HELM_WEB_ROOT"
  cp "$ROOT/deploy/local/placeholder/index.html" "$HELM_WEB_ROOT/index.html"
  warn "serving the placeholder page at $HELM_PUBLIC_URL/ ($1)"
  printf 'placeholder: %s\n' "$1" > "$LOCAL_DIR/web-status"
}

# Build the Flutter web bundle on the host in a scratch copy of frontend/ (so the
# repository tree is not modified), pointing the client at the local proxy.
build_web() {
  mkdir -p "$LOCAL_DIR"
  local flutter="${FLUTTER_BIN:-$(command -v flutter || true)}"
  if [ -z "$flutter" ] && [ -x /opt/flutter/bin/flutter ]; then flutter=/opt/flutter/bin/flutter; fi
  if [ -z "$flutter" ]; then use_placeholder "flutter not installed"; return 0; fi

  local src="$LOCAL_DIR/web-src" key
  key="$(anon_key)"
  rm -rf "$src"
  mkdir -p "$src"
  (cd "$ROOT/frontend" && tar --exclude=./build --exclude=./.dart_tool -cf - .) | (cd "$src" && tar -xf -)
  log "building Flutter web bundle (API_BASE_URL=$HELM_PUBLIC_URL/api/v1, SUPABASE_URL=$HELM_PUBLIC_URL)"
  if (
    cd "$src"
    if [ ! -f web/index.html ]; then
      "$flutter" create --platforms=web --project-name "$(sed -n 's/^name: *//p' pubspec.yaml)" . >/dev/null
    fi
    "$flutter" build web --release \
      --dart-define=API_BASE_URL="$HELM_PUBLIC_URL/api/v1" \
      --dart-define=SUPABASE_URL="$HELM_PUBLIC_URL" \
      --dart-define=SUPABASE_ANON_KEY="$key" \
      --dart-define=APP_ENV=development \
      --dart-define=SENTRY_DSN=
  ) > "$LOCAL_DIR/web-build.log" 2>&1; then
    rm -rf "$HELM_WEB_ROOT"
    mkdir -p "$(dirname "$HELM_WEB_ROOT")"
    cp -r "$src/build/web" "$HELM_WEB_ROOT"
    printf 'flutter: built %s\n' "$(date -u +%FT%TZ)" > "$LOCAL_DIR/web-status"
    log "web bundle ready in $HELM_WEB_ROOT"
  else
    use_placeholder "flutter build failed — see $LOCAL_DIR/web-build.log"
  fi
}

cmd_up() {
  load_env
  build_web
  log "building images"
  "${COMPOSE[@]}" build
  log "starting the stack (waits for health checks and the one-shot migration)"
  if ! "${COMPOSE[@]}" up -d --wait --wait-timeout "${HELM_UP_TIMEOUT:-300}"; then
    "${COMPOSE[@]}" ps -a
    "${COMPOSE[@]}" logs --tail=50 migrate api auth || true
    die "stack did not become healthy"
  fi
  "${COMPOSE[@]}" ps
  cat <<EOF

Helm local stack is up:
  web / API proxy   $HELM_PUBLIC_URL        (API: $HELM_PUBLIC_URL/api/v1, auth: $HELM_PUBLIC_URL/auth/v1)
  readiness         $HELM_PUBLIC_URL/ready  (workers heartbeat appears after ~60 s)
  Mailpit           http://localhost:${HELM_MAIL_UI_PORT:-18025}
  sign-up mode      GOTRUE_MAILER_AUTOCONFIRM=${GOTRUE_MAILER_AUTOCONFIRM}
  web bundle        $(cat "$LOCAL_DIR/web-status" 2>/dev/null || echo unknown)
EOF
}

cmd_seed() {
  load_env
  local help available=() missing=() failed=()
  help="$("${COMPOSE[@]}" run --rm --no-deps -T api cli --help 2>&1 || true)"
  for c in "${SEED_COMMANDS[@]}"; do
    if grep -qw -- "$c" <<<"$help"; then available+=("$c"); else missing+=("$c"); fi
  done
  for c in "${available[@]}"; do
    log "seed: $c"
    "${COMPOSE[@]}" run --rm --no-deps -T api cli "$c" || failed+=("$c")
  done
  echo
  echo "seed commands run:      ${available[*]:-(none)}"
  echo "seed commands failed:   ${failed[*]:-(none)}"
  echo "not available (yet):    ${missing[*]:-(none)}"
  [ "${#failed[@]}" -eq 0 ]
}

case "${1:-}" in
  up) cmd_up ;;
  web) load_env; build_web ;;
  down) load_env; "${COMPOSE[@]}" down ;;
  reset)
    [ "${2:-}" = "--yes" ] || die "reset deletes the local database and volumes; run: $0 reset --yes"
    load_env; "${COMPOSE[@]}" down -v --remove-orphans ;;
  logs) load_env; shift; "${COMPOSE[@]}" logs -f --tail=200 "$@" ;;
  ps) load_env; "${COMPOSE[@]}" ps -a ;;
  seed) cmd_seed ;;
  cli) load_env; shift; "${COMPOSE[@]}" run --rm --no-deps -T api cli "$@" ;;
  *) sed -n '2,17p' "$0"; exit 2 ;;
esac
