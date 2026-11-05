#!/bin/sh
# Local stack only: create (idempotently) the role and database the local Supabase
# GoTrue service migrates itself. Runs as a one-shot container from the database image
# before `auth` starts, so it also works on an existing data volume.
#
# Env: PGHOST, PGUSER, PGPASSWORD (database superuser), GOTRUE_DB_PASSWORD,
#      GOTRUE_DB_NAME (default helm_auth)
set -eu
db_name="${GOTRUE_DB_NAME:-helm_auth}"

psql -v ON_ERROR_STOP=1 -v pw="$GOTRUE_DB_PASSWORD" -d postgres <<'SQL'
SELECT 'CREATE ROLE supabase_auth_admin NOINHERIT CREATEROLE LOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') \gexec
ALTER ROLE supabase_auth_admin WITH LOGIN PASSWORD :'pw';
-- GoTrue migrations grant read access on auth.* to the Supabase `postgres` role, which
-- does not exist when POSTGRES_USER is not "postgres". A NOLOGIN placeholder suffices.
SELECT 'CREATE ROLE postgres NOLOGIN'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'postgres') \gexec
ALTER ROLE supabase_auth_admin SET search_path = auth;
SQL

psql -v ON_ERROR_STOP=1 -v db="$db_name" -d postgres <<'SQL'
SELECT format('CREATE DATABASE %I OWNER supabase_auth_admin', :'db')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SQL

psql -v ON_ERROR_STOP=1 -d "$db_name" <<'SQL'
CREATE SCHEMA IF NOT EXISTS auth AUTHORIZATION supabase_auth_admin;
SQL
echo "auth-db-init: role supabase_auth_admin and database ${db_name} ready"
