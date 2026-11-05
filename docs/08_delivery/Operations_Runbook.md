# Helm — Operations Runbook

Build, local acceptance stack, production deployment, backup/restore and rollback for
the Helm marine commerce platform. Companion to `Repair_Programme.md` (decisions D2 and
D5 in particular). Every command below is run from the repository root.

**Deployment boundary.** Nothing deploys automatically. There is no CI/CD pipeline and
no webhook: a git push or a merge changes nothing on any server. A release reaches
production only when an operator runs `deploy/deploy.sh` on the production host.

## 1. Artefacts

| Artefact | Source | Notes |
|---|---|---|
| Backend image (API, migrate, worker, beat) | `backend/Dockerfile.prod` (target `production`) | Python 3.11 slim, dependencies from `backend/requirements.lock` (hash-pinned), non-root uid 10001, no compiler, read-only root FS friendly, `HEALTHCHECK` (role-aware: `/health` for the API, `celery inspect ping` for the worker) |
| Backend test image | `backend/Dockerfile.prod` (target `test`) | runtime + `requirements-dev.lock` + `app/tests`; needs `TEST_DATABASE_URL`; never deployed |
| Backend dev image | `backend/Dockerfile` | dev lock, `api-dev` role = uvicorn `--reload`; mount `backend/` at `/app` |
| Web image | `frontend/Dockerfile` | Flutter 3.47.9 SDK (cloned at the tag), `flutter build web --release` with dart-defines, non-root nginx (uid 101, port 8080) |
| Proxy configuration | `deploy/nginx/{local,prod}.conf`, `deploy/nginx/snippets/` | mounted into the web container |

Container roles (first argument of `backend/docker/entrypoint.sh`):

| Role | Command | Behaviour |
|---|---|---|
| `api` | `gunicorn -c gunicorn.conf.py app.main:app` (uvicorn workers) | never migrates |
| `migrate` | `alembic upgrade head` | one-shot; non-zero exit on failure |
| `worker` | `celery -A app.celery_app worker -Q default,search,notifications` | |
| `beat` | `celery -A app.celery_app beat --schedule /var/lib/helm/beat/celerybeat-schedule` | schedule file on a volume |
| `cli` | `python -m app.cli …` | e.g. `grant-role` |

Gunicorn knobs (environment): `WEB_CONCURRENCY` (workers, default 2), `GUNICORN_TIMEOUT`
(60), `GUNICORN_GRACEFUL_TIMEOUT` (30), `GUNICORN_KEEPALIVE` (5), `GUNICORN_MAX_REQUESTS`
(2000), `FORWARDED_ALLOW_IPS` (the proxy network; `*` is refused). Access logs never
contain query strings (both gunicorn/uvicorn and nginx).

### Dependency locks

```bash
cd backend
uv pip compile pyproject.toml --python-version 3.11 --python-platform linux --generate-hashes -o requirements.lock
uv pip compile pyproject.toml --extra dev --python-version 3.11 --python-platform linux --generate-hashes -o requirements-dev.lock
```

Regenerate both after any change to `pyproject.toml` and commit them with it. Images
install with `pip --require-hashes`; a dependency without a binary wheel will fail the
production build loudly (see the comment in `Dockerfile.prod`).

### Building behind a TLS-intercepting proxy

All Dockerfiles accept an optional BuildKit secret `build_ca` (a CA bundle). It is never
written to a shipped layer. Compose reads it from `HELM_BUILD_CA_FILE` (default: the
empty `deploy/no-build-ca.pem`); the file must be inside the project directory, and
`scripts/local_stack.sh` copies an outside file into `.local/` for you.

## 2. Local acceptance stack

```bash
cp .env.example .env          # local-only defaults; edit ports/subnet if they clash
scripts/local_stack.sh up     # web bundle + images + stack, waits for health checks
```

| URL | What |
|---|---|
| http://localhost:18080 | Flutter web build (or the placeholder page) |
| http://localhost:18080/api/v1 | API (through nginx) |
| http://localhost:18080/auth/v1 | local Supabase GoTrue (prefix stripped by nginx) |
| http://localhost:18080/health, /ready | liveness / readiness |
| http://localhost:18025 | Mailpit (all mail sent by GoTrue and the API) |

Services: `db` (pgvector/pgvector:pg16), `redis` (7.4), `typesense` (27.1),
`mailpit` (axllent/mailpit v1.27), `auth-db-init` (one-shot), `auth`
(supabase/gotrue **v2.197.0**), `migrate` (one-shot), `api`, `worker`, `beat`, `web`
(nginx-unprivileged 1.29). Only `web` and the Mailpit UI are published, bound to
`127.0.0.1`. The `data` and `edge` networks are `internal` (no internet route); the
local API, workers and GoTrue therefore cannot reach any external service.

Other commands: `scripts/local_stack.sh web | down | reset --yes | logs [svc] | ps |
seed | cli ARGS`. `seed` runs whichever `python -m app.cli seed-*` commands exist
(`seed-boats`, `seed-catalogue`, `seed-products`, `seed-knowledge`, `seed-checklists`,
`seed-operating-areas`, `seed-rewards`, `seed-demo`) and reports the missing ones.

**Web bundle.** `up`/`web` build Flutter on the host (in `.local/web-src`, a scratch
copy of `frontend/`; web scaffolding is generated there if the repository has none) with
`API_BASE_URL=$HELM_PUBLIC_URL/api/v1`, `SUPABASE_URL=$HELM_PUBLIC_URL`,
`APP_ENV=development` and an anon key derived from `SUPABASE_JWT_SECRET` (HS256,
`role=anon`; the API refuses such tokens). If Flutter is missing or the build fails, the
placeholder page `deploy/local/placeholder/index.html` is served and the reason is
written to `.local/web-status` / `.local/web-build.log`.

### Authentication in the local stack (decision D2)

There is no unverified bypass: GoTrue issues real HS256 access tokens and the API
verifies them exactly as in production.

| Setting | GoTrue | API |
|---|---|---|
| signing secret | `GOTRUE_JWT_SECRET=$SUPABASE_JWT_SECRET` | `AUTH_MODE=hs256`, `SUPABASE_JWT_SECRET` |
| issuer | `GOTRUE_JWT_ISSUER=$HELM_PUBLIC_URL/auth/v1` | `SUPABASE_URL=$HELM_PUBLIC_URL` → expects `$HELM_PUBLIC_URL/auth/v1` |
| audience | `GOTRUE_JWT_AUD=authenticated` | `SUPABASE_JWT_AUDIENCE=authenticated` |
| e-mail links | `API_EXTERNAL_URL=$HELM_PUBLIC_URL/auth/v1`, `GOTRUE_MAILER_URLPATHS_*=/auth/v1/verify` | — |

GoTrue migrates its own schema `auth` in a separate database `helm_auth` on the same
Postgres server, as role `supabase_auth_admin` (created by `deploy/local/auth-db-init.sh`,
together with a NOLOGIN `postgres` role its migrations grant to).

**Sign-up modes** (`GOTRUE_MAILER_AUTOCONFIRM` in `.env`, then `docker compose up -d auth`):

* `true` — `POST /auth/v1/signup` returns a session; `POST /api/v1/auth/provision` → 201,
  `GET /api/v1/auth/me` → 200.
* `false` (default) — sign-up returns the user without a session; password sign-in
  returns `email_not_confirmed`; Mailpit receives "Confirm your email address" with a
  link `http://localhost:18080/auth/v1/verify?token=…&type=signup&redirect_to=…`.
  Opening it confirms the address and redirects to the site with the session in the
  URL fragment; sign-in then succeeds and provisioning works.

Manual check with curl (the anon key is only needed as `apikey`):

```bash
curl -s localhost:18080/auth/v1/signup -H 'Content-Type: application/json' \
  -d '{"email":"me@example.test","password":"Correct-Horse-1"}'
curl -s 'localhost:18080/auth/v1/token?grant_type=password' -H 'Content-Type: application/json' \
  -d '{"email":"me@example.test","password":"Correct-Horse-1"}'      # -> access_token
curl -s -X POST localhost:18080/api/v1/auth/provision -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{}'                         # -> 201 (200 when repeated)
```

### Hot reload (optional)

Create an untracked `docker-compose.override.yml` (git-ignored):

```yaml
services:
  api:
    build: { context: ./backend, dockerfile: Dockerfile }
    image: helm-backend:dev
    command: ["api-dev"]
    read_only: false
    volumes: ["./backend:/app"]
```

### Backend tests in a container

```bash
docker build -f backend/Dockerfile.prod --target test -t helm-backend:test backend
docker compose exec db psql -U helm -d postgres -c 'CREATE DATABASE helm_test'
docker run --rm --network helm_data --read-only --tmpfs /tmp \
  -e TEST_DATABASE_URL=postgresql+asyncpg://helm:localdevpassword@db:5432/helm_test helm-backend:test
```

(`helm_data` is `<COMPOSE_PROJECT_NAME>_data`.) The tests truncate their database:
never point `TEST_DATABASE_URL` at a database you care about.

## 3. Production prerequisites

Single Linux host (e.g. one EC2 instance, Ubuntu 22.04/24.04, ≥ 2 vCPU / 4 GiB) prepared
with `sudo bash deploy/setup.sh` (idempotent: Docker Engine + compose plugin, ufw 22/80/443,
fail2ban, certbot, swap on small hosts, `/opt/helm-marine`, `/var/backups/helm`).

`cp .env.prod.example .env.prod && chmod 600 .env.prod`, then fill in:

* **Supabase.** `SUPABASE_URL`, `SUPABASE_ANON_KEY` (public; compiled into the web build).
  Verification: `AUTH_MODE=jwks` when the project uses asymmetric signing keys (the API
  fetches `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, ES256/RS256/EdDSA), or
  `AUTH_MODE=hs256` with the legacy **JWT secret** (`SUPABASE_JWT_SECRET`, server-only,
  ≥ 32 characters, never the anon key). Issuer is `{SUPABASE_URL}/auth/v1`, audience
  `authenticated`. In the Supabase dashboard set the Site URL and redirect URLs to
  `HELM_PUBLIC_URL`, configure SMTP (or Supabase's mailer) and decide whether e-mail
  confirmation is required.
* **Stripe.** `PAYMENT_PROVIDER=stripe`, `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`,
  and a webhook endpoint `https://<domain>/api/v1/payments/webhook` whose signing secret
  goes into `STRIPE_WEBHOOK_SECRET`. nginx passes webhook bodies unbuffered and unmodified.
  Use test keys on a staging host first.
* **Resend.** `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL` on a verified
  domain.
* **Typesense.** `TYPESENSE_API_KEY` (required; `openssl rand -hex 32`); the server runs
  internally, never published.
* **Sentry** (optional). `SENTRY_DSN` (API/worker) and `SENTRY_DSN_WEB` (web build).
* **Secrets/infra.** `SECRET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` (hex, URL-safe),
  `ALLOWED_ORIGINS`, `HELM_PUBLIC_URL` (https), `HELM_DEPLOY_REF`, `HELM_BACKUP_DIR`.
* AI (`OPENAI_API_KEY`), courier rate card, CMS, Mapbox: optional; keep the features
  `disabled` until configured. Local substitutes are refused in production (D5).

## 4. HTTPS / certificates

The proxy expects `fullchain.pem` and `privkey.pem` in `HELM_TLS_DIR` (default
`deploy/certs/`, git-ignored), readable by uid 101 (directory mode ≥ 0750 with group 101,
or 0755). TLS 1.2/1.3, HSTS (`max-age=31536000; includeSubDomains`, HTTPS responses
only), CSP for Flutter web + Stripe + Supabase + Sentry + PostHog + Mapbox (edit
`deploy/nginx/snippets/security-headers.conf` for other origins), gzip, SPA fallback,
`client_max_body_size 20m`, proxy timeouts, `X-Forwarded-*` set by nginx. Port 80 serves
ACME challenges and `/health`, and redirects everything else to HTTPS. `/ready` is only
answered for private source addresses.

First certificate (port 80 must be free, i.e. before the first deploy):

```bash
sudo certbot certonly --standalone -d app.example.co.nz
sudo RENEWED_LINEAGE=/etc/letsencrypt/live/app.example.co.nz deploy/certbot-deploy-hook.sh
```

Renewals (webroot served by the running proxy; certbot's timer runs them):

```bash
sudo certbot certonly --webroot -w /opt/helm-marine/deploy/certbot-www -d app.example.co.nz \
  --deploy-hook /opt/helm-marine/deploy/certbot-deploy-hook.sh
```

## 5. Deploying

```bash
git fetch && git checkout <release-ref>        # must equal HELM_DEPLOY_REF
deploy/deploy.sh
```

`deploy.sh` fails closed (`set -euo pipefail`; any failure exits non-zero and prints
`DEPLOY FAILED during step: …`; `Deploy complete` is printed only at the very end):

1. **preflight** — tools present; `.env.prod` exists and is not world-readable; required
   variables non-empty (conditional ones for `hs256`, `stripe`, `resend`, `openai`,
   `rate_card`); `APP_ENV=production`; https public URL; clean git tree with `HEAD` at
   `HELM_DEPLOY_REF`; TLS files present; compose configuration valid.
2. **build** — backend and web images tagged `HELM_IMAGE_TAG` = first 12 characters of
   the commit SHA (`--skip-build` reuses existing images of that tag instead).
3. **validate** — the application's own `Settings.validate_runtime()` in a throw-away
   container (prints problem names, never values).
4. **backup** — data stores started; `deploy/backup.sh` writes a verified pre-migration
   dump; abort if it fails.
5. **migrate** — one-shot `alembic upgrade head`; on failure the script stops, leaves the
   running release untouched and prints the exact `deploy/restore.sh` command.
6. **start** — `api`, `worker`, `beat`, `web`.
7. **readiness** — `/ready` must report `ready: true` within `HELM_READY_TIMEOUT` (180 s),
   then the Celery heartbeat must be newer than the deploy start within
   `HELM_WORKER_TIMEOUT` (240 s; `0` skips). Timeout → `docker compose ps`, recent logs
   and rollback instructions, exit 1.

Each success is appended to `$HELM_BACKUP_DIR/deploy-history.log` (time, release, ref,
backup file).

## 6. First administrator

Roles live only in `users.role` (D1). After the first person has signed up and been
provisioned:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm --no-deps api \
  cli grant-role owner@example.co.nz admin
# local stack: scripts/local_stack.sh cli grant-role me@example.test admin
```

The change is audited. Further role changes go through the admin endpoint.

## 7. Migrating an existing Phase-7 database

Phase-7 databases were created with `create_all()` and have no `alembic_version`. Revision
`0001` is the exact Phase-7 schema; `0002` upgrades it with data backfills (cents
conversion, unverified legacy fitment, …).

```bash
deploy/backup.sh --label pre-phase7-upgrade                     # verified backup first
docker compose --env-file .env.prod -f docker-compose.prod.yml run --rm --no-deps migrate \
  alembic stamp 0001                                           # mark the baseline as applied
deploy/deploy.sh                                               # runs 0001 -> 0002 (head)
```

Only stamp a database whose schema really is the Phase-7 schema. A brand-new database
needs nothing: `migrate` creates everything from `0001`.

## 8. Backup and restore

```bash
deploy/backup.sh --label manual            # prints the path of the verified dump
deploy/restore.sh --file /var/backups/helm/helm-<label>-<ts>.dump --confirm-restore
```

* Backups: `pg_dump --format=custom` inside the db container, mode 600, `.sha256`
  alongside, verified with `pg_restore --list` (an empty archive is accepted only for a
  database with no tables). Copy `$HELM_BACKUP_DIR` off the host (e.g. S3 with object
  lock) on a schedule; the host alone is not a backup location.
* Restore never runs automatically and refuses to run without `--file` and
  `--confirm-restore`. It verifies the checksum, stops `api/worker/beat/web`, **drops and
  recreates** the database, restores the dump in one transaction and leaves the
  application stopped so the matching release can be deployed.
* Redis (queue/rate-limit state) and Typesense (rebuilt from the database) are not backed
  up.

## 9. Rollback

* **Code-only problem** (schema unchanged or still compatible): check out the previous
  release and redeploy its images — `git checkout <prev>` then
  `HELM_DEPLOY_REF=<prev> deploy/deploy.sh --skip-build`. Images of earlier releases stay
  on the host (tagged by commit) unless pruned.
* **Schema problem.** Migration `0002` deliberately refuses to downgrade (it converts money
  to cents and rewrites data). Restore the pre-deploy backup named in the deploy output,
  then redeploy the previous release:

  ```bash
  deploy/restore.sh --file <pre-deploy backup> --confirm-restore
  git checkout <prev> && HELM_DEPLOY_REF=<prev> deploy/deploy.sh --skip-build
  ```

  Writes made between the backup and the restore are lost; announce maintenance first.

## 10. Observability

* `GET /health` — process liveness (also on plain HTTP for load balancers).
* `GET /ready` — `{"ready": bool, "checks": {"database": {"ok", "migration"}, "redis":
  {"ok"}, "workers": {"celery": {"last_seen_at", "fresh"}}}}`; 503 when the database or
  Redis is down. The `workers.celery` heartbeat is written by the `app.tasks.ops.heartbeat`
  task that beat schedules every 60 s and a worker executes, so a fresh heartbeat proves
  **both** are running; `fresh` turns false after `WORKER_HEARTBEAT_STALE_SECONDS` (180).
* Logs: `docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f api worker beat web`
  (json-file driver, rotated 5 × 20 MB per container).
* Container health: `docker compose … ps` (API `/health`, worker `celery inspect ping`,
  nginx `/health`, data-store probes).
* Sentry (when `SENTRY_DSN` is set) for API/worker exceptions.

## 11. Environment variable reference

Every application setting is a field of `Settings` in `backend/app/config.py`; the
environment variable is the upper-cased field name. Generated from the code at the time of
writing — the code is authoritative. "Refused outside dev/test" means
`Settings.validate_runtime()` stops the API/worker when `APP_ENV` is `staging`/`production`.

Compose/deploy-only variables (not read by the application): `HELM_PUBLIC_URL`,
`HELM_WEB_PORT`, `HELM_MAIL_UI_PORT`, `HELM_BIND_ADDRESS`, `HELM_EDGE_SUBNET`,
`HELM_BUILD_CA_FILE`, `HELM_WEB_ROOT`, `POSTGRES_USER/PASSWORD/DB`, `REDIS_PASSWORD`,
`GOTRUE_DB_PASSWORD`, `GOTRUE_MAILER_AUTOCONFIRM`, `HELM_DEPLOY_REF`, `HELM_TLS_DIR`,
`HELM_BACKUP_DIR`, `HELM_IMAGE_REPO`, `HELM_IMAGE_TAG` (set by deploy.sh),
`HELM_HTTP_PORT`, `HELM_HTTPS_PORT`, `HELM_READY_TIMEOUT`, `HELM_WORKER_TIMEOUT`,
`SENTRY_DSN_WEB`, resource limits `HELM_*_CPUS` / `HELM_*_MEMORY`; process sizing
`WEB_CONCURRENCY`, `GUNICORN_*`, `FORWARDED_ALLOW_IPS`, `CELERY_CONCURRENCY`,
`CELERY_QUEUES`, `CELERY_LOG_LEVEL`, `CELERY_BEAT_SCHEDULE`.

| Variable | Code default | Notes |
|---|---|---|
| `APP_ENV` | `development` | `production` in .env.prod; local stack fixes `development` |
| `SECRET_KEY` | (placeholder) | required outside dev/test, >= 32 random chars |
| `ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:8080` | production origins only (no localhost / `*`) |
| `API_V1_PREFIX` | `/api/v1` |  |
| `PUBLIC_BASE_URL` | `http://localhost:8080` |  |
| `LOG_SQL` | `False` |  |
| `DATABASE_URL` | `postgresql+asyncpg://helm:password@localhost:5432/helm_db` | built by the compose files from POSTGRES_* |
| `DATABASE_POOL_SIZE` | `10` |  |
| `DATABASE_MAX_OVERFLOW` | `10` |  |
| `REDIS_URL` | `redis://localhost:6379/0` | built by the compose files (prod includes REDIS_PASSWORD) |
| `AUTH_MODE` | `jwks` | `jwks` (recommended) or `hs256`; local stack: `hs256` |
| `SUPABASE_URL` | "" | issuer = `{SUPABASE_URL}/auth/v1`; local: `http://localhost:18080` |
| `SUPABASE_ANON_KEY` | "" | public; used by the web build, never to verify tokens |
| `SUPABASE_SERVICE_ROLE_KEY` | "" |  |
| `SUPABASE_JWT_SECRET` | "" | hs256 only; server-only legacy secret, never the anon key |
| `SUPABASE_JWT_ISSUER` | "" |  |
| `SUPABASE_JWT_AUDIENCE` | `authenticated` |  |
| `SUPABASE_JWKS_URL` | "" |  |
| `SUPABASE_REQUIRE_EMAIL_CONFIRMATION` | `True` | declared but not read by the API yet |
| `JWT_LEEWAY_SECONDS` | `30` |  |
| `RATE_LIMIT_BACKEND` | `memory` | `redis` required outside dev/test (compose sets it) |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `20` |  |
| `RATE_LIMIT_AI_PER_MINUTE` | `10` |  |
| `RATE_LIMIT_AI_PER_DAY` | `200` |  |
| `RATE_LIMIT_MUTATION_PER_MINUTE` | `120` |  |
| `RATE_LIMIT_WEBHOOK_PER_MINUTE` | `600` |  |
| `PAYMENT_PROVIDER` | `disabled` | `stripe` in production; `local` refused outside dev/test |
| `STRIPE_SECRET_KEY` | "" | required with `stripe` |
| `STRIPE_PUBLISHABLE_KEY` | "" |  |
| `STRIPE_WEBHOOK_SECRET` | "" | required with `stripe` |
| `LOCAL_PAYMENT_WEBHOOK_SECRET` | (placeholder) | local substitute only |
| `RESERVATION_MINUTES` | `30` |  |
| `MIN_CHARGE_CENTS` | `50` |  |
| `AFTERPAY_ENABLED` | `False` |  |
| `LAYBUY_ENABLED` | `False` |  |
| `LAYBUY_API_KEY` | "" |  |
| `LAYBUY_API_SECRET` | "" |  |
| `LAYBUY_SANDBOX` | `True` |  |
| `COURIER_RATE_MODE` | `disabled` | `rate_card` needs COURIER_RATE_CARD in production |
| `COURIER_RATE_CARD` | "" |  |
| `COURIER_SERVICE_NAME` | `Standard courier` |  |
| `COURIER_ESTIMATED_DAYS` | `3` |  |
| `COURIER_BOOKING_ENABLED` | `False` | must stay false (not implemented) |
| `FREE_SHIPPING_THRESHOLD_CENTS` | `15000` |  |
| `QUOTE_TTL_MINUTES` | `20` |  |
| `CLICK_AND_COLLECT_ENABLED` | `True` |  |
| `CLICK_AND_COLLECT_LOCATION` | `Helm Marine, Westhaven Marina, Auckland` |  |
| `DANGEROUS_GOODS_DELIVERY_TYPES` | `click_and_collect` |  |
| `HELM_DASH_ENABLED` | `False` |  |
| `WAREHOUSE_LAT` | `-36.8406` |  |
| `WAREHOUSE_LNG` | `174.753` |  |
| `HELM_DASH_BASE_FEE_CENTS` | `2500` |  |
| `HELM_DASH_PER_NM_FEE_CENTS` | `800` |  |
| `HELM_DASH_SPEED_KNOTS` | `25.0` |  |
| `HELM_DASH_OPERATOR_SHARE_BPS` | `None` |  |
| `HELM_DASH_LIVE_PAYOUTS_ENABLED` | `False` | must stay false (not implemented) |
| `NZPOST_CLIENT_ID` | "" |  |
| `NZPOST_CLIENT_SECRET` | "" |  |
| `NZPOST_ACCOUNT_NUMBER` | "" |  |
| `ARAMEX_API_KEY` | "" |  |
| `ARAMEX_ACCOUNT_NUMBER` | "" |  |
| `MAPBOX_ACCESS_TOKEN` | "" |  |
| `AI_ENABLED` | `False` |  |
| `LLM_PROVIDER` | `disabled` | `local_extractive` refused outside dev/test |
| `EMBEDDING_PROVIDER` | `disabled` | `local_hash` refused outside dev/test |
| `OPENAI_API_KEY` | "" |  |
| `OPENAI_CHAT_MODEL` | `gpt-4.1-mini` |  |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` |  |
| `EMBEDDING_DIMENSIONS` | `1536` |  |
| `AI_MAX_MESSAGE_CHARS` | `2000` |  |
| `AI_HISTORY_MESSAGES` | `10` |  |
| `AI_MAX_CONVERSATION_MESSAGES` | `200` |  |
| `AI_MAX_TOOL_ITERATIONS` | `4` |  |
| `AI_MAX_OUTPUT_TOKENS` | 900 |  |
| `AI_REQUEST_TIMEOUT_SECONDS` | `30.0` |  |
| `RAG_TOP_K` | `5` |  |
| `RAG_MIN_SIMILARITY_OPENAI` | `0.35` |  |
| `RAG_MIN_SIMILARITY_LOCAL` | `0.18` |  |
| `FITMENT_MIN_CONFIDENCE` | `0.7` |  |
| `CMS_PROVIDER` | `disabled` | `local_fixture` refused outside dev/test |
| `STRAPI_URL` | "" |  |
| `STRAPI_API_TOKEN` | "" |  |
| `CMS_CACHE_SECONDS` | `300` |  |
| `SEARCH_BACKEND` | `postgres` | `typesense` in both stacks |
| `TYPESENSE_HOST` | `localhost` | set by compose (`typesense`) |
| `TYPESENSE_PORT` | `8108` |  |
| `TYPESENSE_PROTOCOL` | `http` |  |
| `TYPESENSE_API_KEY` | "" | required by both compose files |
| `TYPESENSE_SEARCH_ONLY_KEY` | "" |  |
| `TYPESENSE_COLLECTION` | `products` |  |
| `EMAIL_PROVIDER` | `log_sink` | `resend` in production; `smtp_sink` refused outside dev/test |
| `RESEND_API_KEY` | "" |  |
| `RESEND_FROM_EMAIL` | `noreply@helmmarine.co.nz` |  |
| `SMTP_SINK_HOST` | `localhost` | local stack: `mailpit` |
| `SMTP_SINK_PORT` | `1025` | local stack: `1025` |
| `PUSH_PROVIDER` | `log_sink` |  |
| `FIREBASE_PROJECT_ID` | "" |  |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | "" |  |
| `NOTIFICATION_MAX_ATTEMPTS` | `6` |  |
| `AWS_ACCESS_KEY_ID` | "" |  |
| `AWS_SECRET_ACCESS_KEY` | "" |  |
| `AWS_S3_BUCKET` | `helm-marine-assets` |  |
| `AWS_REGION` | `ap-southeast-2` |  |
| `POSTHOG_API_KEY` | "" |  |
| `POSTHOG_HOST` | `https://app.posthog.com` |  |
| `SENTRY_DSN` | "" | server-side DSN (optional) |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` |  |
| `WORKER_HEARTBEAT_STALE_SECONDS` | `180` | `/ready` marks the celery heartbeat stale after this |
