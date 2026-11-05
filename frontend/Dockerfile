# syntax=docker/dockerfile:1.7
# =============================================================================
# Helm web — Flutter web release build served by non-root nginx
#
#   docker build -f frontend/Dockerfile frontend \
#     --build-arg API_BASE_URL=https://app.example.co.nz/api/v1 \
#     --build-arg SUPABASE_URL=https://PROJECT.supabase.co \
#     --build-arg SUPABASE_ANON_KEY=... \
#     --build-arg APP_ENV=production \
#     --build-arg SENTRY_DSN=...
#
# The build FAILS when API_BASE_URL is empty or points at localhost/127.0.0.1 unless
# APP_ENV=development. Values become compile-time --dart-define constants; they are
# public client configuration (the anon key is a public key), never server secrets.
#
# There is no official Flutter image for 3.47.x, so the pinned SDK is cloned from the
# Flutter repository at FLUTTER_VERSION. Optional build secret `build_ca` (an extra CA
# bundle for builds behind a TLS-intercepting proxy) is used only in builder stages.
# =============================================================================
ARG FLUTTER_VERSION=3.47.9
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.29-alpine

# --- preflight: validate client configuration before any expensive work -------
FROM alpine:3.22 AS preflight
ARG API_BASE_URL=""
ARG SUPABASE_URL=""
ARG SUPABASE_ANON_KEY=""
ARG APP_ENV=production
RUN set -eu; \
    case "$APP_ENV" in development|test|staging|production) ;; \
      *) echo "ERROR: APP_ENV must be development, test, staging or production (got '$APP_ENV')" >&2; exit 1;; esac; \
    if [ -z "$API_BASE_URL" ]; then echo "ERROR: build arg API_BASE_URL is required" >&2; exit 1; fi; \
    if [ "$APP_ENV" != "development" ]; then \
      for v in "$API_BASE_URL" "$SUPABASE_URL"; do \
        case "$v" in *localhost*|*127.0.0.1*|*0.0.0.0*) \
          echo "ERROR: API_BASE_URL/SUPABASE_URL point at a local address but APP_ENV=$APP_ENV" >&2; exit 1;; esac; \
        case "$v" in https://*|"") ;; \
          *) echo "ERROR: API_BASE_URL/SUPABASE_URL must use https:// when APP_ENV=$APP_ENV" >&2; exit 1;; esac; \
      done; \
      if [ -z "$SUPABASE_URL" ]; then echo "ERROR: SUPABASE_URL is required when APP_ENV=$APP_ENV" >&2; exit 1; fi; \
      if [ -z "$SUPABASE_ANON_KEY" ]; then echo "ERROR: SUPABASE_ANON_KEY (public key) is required when APP_ENV=$APP_ENV" >&2; exit 1; fi; \
    fi; \
    echo "client configuration accepted (APP_ENV=$APP_ENV)" > /preflight.ok

# --- flutter SDK -------------------------------------------------------------
FROM debian:trixie-slim AS flutter-sdk
ARG FLUTTER_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git unzip xz-utils \
    && rm -rf /var/lib/apt/lists/*
# Dart only trusts the system store, so an optional build CA is added to it here. This
# stage is a builder only (never shipped) and a CA certificate is public material.
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then \
      cat /run/secrets/build_ca >> /etc/ssl/certs/ca-certificates.crt; \
    fi
RUN useradd --create-home --uid 10001 builder
ENV FLUTTER_HOME=/opt/flutter PATH=/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$PATH \
    PUB_CACHE=/home/builder/.pub-cache FLUTTER_SUPPRESS_ANALYTICS=true CI=true
RUN install -d -o builder -g builder /opt/flutter
USER builder
RUN git clone --depth 1 --branch "${FLUTTER_VERSION}" https://github.com/flutter/flutter.git /opt/flutter \
    && flutter config --no-analytics --no-cli-animations >/dev/null \
    && flutter precache --web --no-android --no-ios --no-linux --no-macos --no-windows \
    && flutter --version

# --- build -------------------------------------------------------------------
FROM flutter-sdk AS build
COPY --from=preflight /preflight.ok /tmp/preflight.ok
ARG API_BASE_URL=""
ARG SUPABASE_URL=""
ARG SUPABASE_ANON_KEY=""
ARG APP_ENV=production
ARG SENTRY_DSN=""
WORKDIR /src
COPY --chown=builder:builder pubspec.yaml pubspec.lock* ./
RUN flutter pub get
COPY --chown=builder:builder . .
# Generate the web platform scaffolding when the repository does not carry it yet.
RUN if [ ! -f web/index.html ]; then \
      echo "web/ scaffolding missing: generating it for this build"; \
      flutter create --platforms=web --project-name "$(sed -n 's/^name: *//p' pubspec.yaml)" . >/dev/null; \
    fi
RUN flutter build web --release \
      --dart-define=API_BASE_URL="${API_BASE_URL}" \
      --dart-define=SUPABASE_URL="${SUPABASE_URL}" \
      --dart-define=SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY}" \
      --dart-define=APP_ENV="${APP_ENV}" \
      --dart-define=SENTRY_DSN="${SENTRY_DSN}"

# --- runtime -----------------------------------------------------------------
FROM ${NGINX_IMAGE} AS runtime
COPY docker/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/build/web/ /usr/share/nginx/html/
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
