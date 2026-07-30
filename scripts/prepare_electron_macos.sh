#!/bin/bash
set -euo pipefail

# macOS 26 may abort while registering an invalid development Electron bundle
# with AppKit. Electron is already ad-hoc signed, so leave a valid installation
# untouched. Re-signing the whole nested bundle on every launch can itself fail
# halfway through and leave one of Electron's Helper apps unavailable.
if [[ "$(uname -s)" != "Darwin" ]]; then
  exit 0
fi

ELECTRON_APP="$(pwd)/node_modules/electron/dist/Electron.app"
ELECTRON_BIN="$ELECTRON_APP/Contents/MacOS/Electron"

if [[ ! -x "$ELECTRON_BIN" ]]; then
  echo "未找到 Electron 运行时：$ELECTRON_APP" >&2
  echo "请先在 frontend 目录执行 npm install" >&2
  exit 1
fi

# A healthy npm Electron bundle needs no mutation. This also makes repeated
# desktop launches idempotent instead of rewriting every nested signature.
if codesign --verify --deep --strict "$ELECTRON_APP" >/dev/null 2>&1; then
  exit 0
fi

echo "检测到 Electron 签名不完整，正在修复..."
if ! codesign --force --deep --sign - "$ELECTRON_APP" >/dev/null; then
  # A failed deep-sign can leave a partially updated nested bundle. Retrying
  # completes the repair reliably without downloading or replacing Electron.
  echo "首次修复未完成，正在重试..."
  codesign --force --deep --sign - "$ELECTRON_APP" >/dev/null
fi

codesign --verify --deep --strict "$ELECTRON_APP" >/dev/null
