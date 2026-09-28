#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT_ROOT="$(mktemp -d /tmp/ax-linux-frontend.XXXXXX)"
trap 'rm -rf "$AUDIT_ROOT"' EXIT

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  NODE_BIN="$(dirname "$(command -v node)")"
else
  command -v curl >/dev/null 2>&1 || {
    echo "curl is required when Linux Node.js is unavailable" >&2
    exit 1
  }
  curl -fsSLo "$AUDIT_ROOT/SHASUMS256.txt" \
    https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt
  NODE_ARCHIVE="$(awk '/linux-x64\.tar\.xz$/ { print $2; exit }' "$AUDIT_ROOT/SHASUMS256.txt")"
  test -n "$NODE_ARCHIVE"
  curl -fsSLo "$AUDIT_ROOT/$NODE_ARCHIVE" \
    "https://nodejs.org/dist/latest-v22.x/$NODE_ARCHIVE"
  (
    cd "$AUDIT_ROOT"
    grep "  $NODE_ARCHIVE$" SHASUMS256.txt | sha256sum -c -
  )
  tar -xJf "$AUDIT_ROOT/$NODE_ARCHIVE" -C "$AUDIT_ROOT"
  NODE_BIN="$AUDIT_ROOT/${NODE_ARCHIVE%.tar.xz}/bin"
fi

export PATH="$NODE_BIN:$PATH"
mkdir "$AUDIT_ROOT/console"
tar \
  --exclude=node_modules \
  --exclude=dist \
  --exclude=artifacts \
  -C "$ROOT/results_console" -cf - . \
  | tar -C "$AUDIT_ROOT/console" -xf -

cd "$AUDIT_ROOT/console"
node --version
npm --version
npm ci
npm test
npm run typecheck
npm run build
