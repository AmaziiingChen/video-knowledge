#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
DIST_INDEX="$FRONTEND_DIR/dist/index.html"

export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

# This Finder launcher starts Electron in development mode.  In that mode
# electron/main.cjs launches uvicorn with its source reloader from the checkout's
# backend directory, so backend source changes take effect without repackaging.
# Do not run PyInstaller here:
# its 900MB+ dependency analysis does not participate in this runtime and is
# reserved for the explicit desktop package commands.

cd "$FRONTEND_DIR"

# The desktop shell can use the existing production bundle directly. Rebuild
# only when source files changed, so ordinary double-click launches do not
# spend time transforming the full front-end dependency graph.
NEEDS_BUILD=0
if [[ ! -f "$DIST_INDEX" ]]; then
  NEEDS_BUILD=1
elif find src electron public -type f -newer "$DIST_INDEX" -print -quit | grep -q .; then
  NEEDS_BUILD=1
else
  for INPUT in index.html package.json package-lock.json vite.config.js; do
    if [[ -f "$INPUT" && "$INPUT" -nt "$DIST_INDEX" ]]; then
      NEEDS_BUILD=1
      break
    fi
  done
fi

if [[ "$NEEDS_BUILD" -eq 1 ]]; then
  npm run build
fi

exec npm run desktop:launch
