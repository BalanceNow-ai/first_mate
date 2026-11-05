# shellcheck shell=bash
# Shared helpers for deploy/*.sh (sourced, not executed). Never prints secret values.

HELM_ROOT="${HELM_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HELM_ENV_FILE="${HELM_ENV_FILE:-$HELM_ROOT/.env.prod}"
HELM_COMPOSE_FILE="${HELM_COMPOSE_FILE:-$HELM_ROOT/docker-compose.prod.yml}"

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
warn() { printf '[%s] WARNING: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die()  { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; exit 1; }

compose() {
  docker compose --env-file "$HELM_ENV_FILE" -f "$HELM_COMPOSE_FILE" "$@"
}

# Export KEY=VALUE lines of the env file without evaluating them. Variables already set
# in the calling environment win (the same precedence docker compose applies).
load_env_file() {
  [ -f "$HELM_ENV_FILE" ] || die "$HELM_ENV_FILE not found — copy .env.prod.example to .env.prod and fill it in"
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"
    # strip one level of matching quotes
    if [[ "$value" =~ ^\"(.*)\"$ ]] || [[ "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
    [ -n "${!key+x}" ] || export "$key=$value"
  done < "$HELM_ENV_FILE"
}

# require_vars NAME... : fail listing (names only) every variable that is unset/empty.
require_vars() {
  local missing=() name
  for name in "$@"; do
    [ -n "${!name:-}" ] || missing+=("$name")
  done
  [ "${#missing[@]}" -eq 0 ] || die "required variables are empty in $(basename "$HELM_ENV_FILE"): ${missing[*]}"
}
