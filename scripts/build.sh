#!/usr/bin/env bash
# Helm Marine — Flutter production build scripts
# Usage: ./scripts/build.sh <android|ios|web>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")/frontend"

cd "$PROJECT_DIR"

case "${1:-}" in
  android)
    echo "Building Android App Bundle (release)..."
    flutter build appbundle --release
    echo "Build complete: build/app/outputs/bundle/release/app-release.aab"
    ;;
  ios)
    echo "Building iOS IPA (release)..."
    flutter build ipa --release
    echo "Build complete: build/ios/ipa/"
    ;;
  web)
    echo "Building Web (release)..."
    flutter build web --release
    echo "Build complete: build/web/"
    ;;
  *)
    echo "Usage: $0 <android|ios|web>"
    echo ""
    echo "Commands:"
    echo "  android   Build Android App Bundle (release)"
    echo "  ios       Build iOS IPA (release)"
    echo "  web       Build Flutter Web (release)"
    exit 1
    ;;
esac
