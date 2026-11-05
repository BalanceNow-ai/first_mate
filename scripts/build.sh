#!/usr/bin/env bash
# Helm Marine — Flutter release builds
#
#   API_BASE_URL=https://app.example.co.nz/api/v1 SUPABASE_URL=https://P.supabase.co \
#   SUPABASE_ANON_KEY=... APP_ENV=production [SENTRY_DSN=...] ./scripts/build.sh <android|ios|web>
#
# Client configuration is compiled in with --dart-define. The build refuses an empty
# API_BASE_URL, and a localhost/127.0.0.1 API or Supabase URL unless APP_ENV=development.
# For the containerised web image use frontend/Dockerfile (same checks); for the local
# stack use scripts/local_stack.sh (points the client at the local proxy).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")/frontend"

usage() {
  sed -n '2,10p' "$0"
  exit 1
}

target="${1:-}"
[ -n "$target" ] || usage

APP_ENV="${APP_ENV:-production}"
API_BASE_URL="${API_BASE_URL:-}"
SUPABASE_URL="${SUPABASE_URL:-}"
SUPABASE_ANON_KEY="${SUPABASE_ANON_KEY:-}"
SENTRY_DSN="${SENTRY_DSN:-}"

[ -n "$API_BASE_URL" ] || { echo "ERROR: API_BASE_URL is required" >&2; exit 1; }
if [ "$APP_ENV" != "development" ]; then
  for v in "$API_BASE_URL" "$SUPABASE_URL"; do
    case "$v" in *localhost*|*127.0.0.1*|*0.0.0.0*)
      echo "ERROR: local URL '$v' with APP_ENV=$APP_ENV (only allowed for development)" >&2; exit 1 ;;
    esac
  done
  [ -n "$SUPABASE_URL" ] && [ -n "$SUPABASE_ANON_KEY" ] \
    || { echo "ERROR: SUPABASE_URL and SUPABASE_ANON_KEY are required for APP_ENV=$APP_ENV" >&2; exit 1; }
fi

DEFINES=(
  "--dart-define=API_BASE_URL=$API_BASE_URL"
  "--dart-define=SUPABASE_URL=$SUPABASE_URL"
  "--dart-define=SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY"
  "--dart-define=APP_ENV=$APP_ENV"
  "--dart-define=SENTRY_DSN=$SENTRY_DSN"
)

cd "$PROJECT_DIR"

case "$target" in
  android)
    echo "Building Android App Bundle (release, APP_ENV=$APP_ENV)..."
    flutter build appbundle --release "${DEFINES[@]}"
    echo "Build complete: build/app/outputs/bundle/release/app-release.aab"
    ;;
  ios)
    echo "Building iOS IPA (release, APP_ENV=$APP_ENV)..."
    flutter build ipa --release "${DEFINES[@]}"
    echo "Build complete: build/ios/ipa/"
    ;;
  web)
    echo "Building Web (release, APP_ENV=$APP_ENV)..."
    flutter build web --release "${DEFINES[@]}"
    echo "Build complete: build/web/"
    ;;
  *)
    usage
    ;;
esac
