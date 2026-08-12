#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
PREVIEW_PROFILE="$(/usr/bin/mktemp -d "${TMPDIR:-/private/tmp}/knowledgehub-desktop-preview.XXXXXX")"
PORT_OWNER=""

cleanup() {
  /bin/rm -rf "$PREVIEW_PROFILE"
}
trap cleanup EXIT

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "KnowledgeHub 桌面预览仅支持 macOS。" >&2
  exit 1
fi

if [[ ! -x "$FRONTEND_DIR/node_modules/.bin/electron" ]]; then
  echo "未找到 Electron 依赖。请先在 frontend 目录执行 npm install。" >&2
  exit 1
fi

PORT_OWNER="$(/usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | /usr/bin/head -n 1 || true)"
if [[ -n "$PORT_OWNER" ]]; then
  echo "本机端口 8000 正被进程 $PORT_OWNER 占用。"
  echo "请先退出已安装的 KnowledgeHub 或其他占用该端口的服务，再重新双击本脚本。"
  exit 1
fi

echo "正在构建 KnowledgeHub 桌面预览…"
cd "$FRONTEND_DIR"
npm run build

echo "正在以临时 Electron 配置启动真实桌面端…"
echo "临时配置目录：$PREVIEW_PROFILE"
echo "Electron 配置使用临时目录；源码后端继续使用仓库 data 目录，以便预览现有开发数据。"
echo "关闭预览后会删除临时配置，不会读写已安装版的 Application Support 数据。"

export KNOWLEDGEHUB_USER_DATA_DIR="$PREVIEW_PROFILE"
export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"

bash ../scripts/prepare_electron_macos.sh
node_modules/.bin/electron electron/main.cjs
