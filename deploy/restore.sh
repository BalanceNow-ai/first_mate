#!/usr/bin/env bash
# =============================================================================
# Helm — restore a verified backup (DESTRUCTIVE; never run automatically)
#
#   deploy/restore.sh --file /var/backups/helm/helm-pre-deploy-....dump --confirm-restore
#
# 1. verifies the .sha256 checksum and that pg_restore can read the archive
# 2. stops api, worker, beat and web (no writes during the restore)
# 3. DROPS and recreates the application database, then restores the dump into it
#    (a full replacement: tables added by a newer migration do not survive)
# 4. leaves the application stopped; start the release that matches the restored
#    schema (see the Operations Runbook, "Rollback").
# =============================================================================
set -euo pipefail
# shellcheck source=deploy/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

file="" confirmed=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --file) file="${2:?--file needs a path}"; shift 2 ;;
    --confirm-restore) confirmed=1; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
[ -n "$file" ] || die "--file PATH is required (a backup written by deploy/backup.sh)"
[ "$confirmed" -eq 1 ] || die "restore replaces the production database; re-run with --confirm-restore"
[ -s "$file" ] || die "backup file not found or empty: $file"
[ -f "$file.sha256" ] || die "checksum file missing: $file.sha256"

load_env_file
require_vars POSTGRES_USER POSTGRES_DB

log "restore: verifying checksum"
(cd "$(dirname "$file")" && sha256sum --check --quiet "$(basename "$file").sha256") || die "checksum mismatch — refusing to restore"
compose ps --status running --services 2>/dev/null | grep -qx db || die "the db service is not running (start it: docker compose ... up -d db)"
compose exec -T db pg_restore --list < "$file" > /dev/null || die "pg_restore cannot read $file"

log "restore: stopping application services"
compose stop api worker beat web

log "restore: recreating database and restoring $file"
compose exec -T db sh -c '
  set -e
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -q \
    -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE)" \
    -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\""
' || die "could not recreate the database"
compose exec -T db sh -c 'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error --single-transaction' < "$file" \
  || die "pg_restore failed — the database is EMPTY; fix the cause and run restore again"

rev="$(compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT version_num FROM alembic_version" 2>/dev/null' || true)"
log "restore: complete (alembic revision in the restored database: ${rev:-none})"
log "the application is stopped. Deploy the release matching revision ${rev:-?}:"
log "  git checkout <previous release ref> && HELM_DEPLOY_REF=<that ref> deploy/deploy.sh --skip-build"
