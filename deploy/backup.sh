#!/usr/bin/env bash
# =============================================================================
# Helm — verified PostgreSQL backup (pg_dump custom format)
#
#   deploy/backup.sh [--label NAME]
#
# Writes  $HELM_BACKUP_DIR/helm-<label>-<UTC timestamp>.dump  (+ .sha256), mode 600.
# Verification: the dump is non-empty, `pg_restore --list` can read it, and the
# SHA-256 checksum file matches. Exit status is non-zero on any failure; the path of the
# verified backup is the only line printed on stdout.
# The dump runs inside the db container (credentials stay in the container).
# =============================================================================
# $POSTGRES_* expand inside the db container, on purpose:
# shellcheck disable=SC2016
set -euo pipefail
# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

label="manual"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --label) label="${2:?--label needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[[ "$label" =~ ^[A-Za-z0-9._-]+$ ]] || die "label may contain only letters, digits, . _ -"

load_env_file
require_vars HELM_BACKUP_DIR POSTGRES_USER POSTGRES_DB

umask 077
mkdir -p "$HELM_BACKUP_DIR"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
out="$HELM_BACKUP_DIR/helm-${label}-${ts}.dump"
partial="$out.partial"
trap 'rm -f "$partial"' EXIT

compose ps --status running --services 2>/dev/null | grep -qx db || die "the db service is not running"

log "backup: pg_dump (custom format) -> $out"
compose exec -T db sh -c 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=6 --no-password' > "$partial" \
  || die "pg_dump failed"
[ -s "$partial" ] || die "pg_dump produced an empty file"

log "backup: verifying archive with pg_restore --list"
listing="$(compose exec -T db pg_restore --list < "$partial")" || die "pg_restore could not read the archive"
entries="$(grep -cv '^;' <<<"$listing" || true)"
if [ "${entries:-0}" -eq 0 ]; then
  # Only acceptable for a brand-new, empty database (first installation).
  tables="$(compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('"'pg_catalog','information_schema'"')"')"
  [ "${tables//[[:space:]]/}" = "0" ] || die "archive has no entries but the database has tables — backup is not valid"
  log "backup: database is empty (first installation); archive contains no objects"
fi

mv "$partial" "$out"
(cd "$HELM_BACKUP_DIR" && sha256sum "$(basename "$out")" > "$(basename "$out").sha256")
(cd "$HELM_BACKUP_DIR" && sha256sum --check --quiet "$(basename "$out").sha256") || die "checksum verification failed"
trap - EXIT

log "backup: verified ($(wc -c < "$out") bytes, $entries archive entries, sha256 $(cut -c1-16 "$out.sha256")…)"
printf '%s\n' "$out"
