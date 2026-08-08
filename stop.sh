#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

export PATH="/opt/miniconda3/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

RUN_DIR="$(pwd)/data/run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_TOKEN_FILE="$RUN_DIR/backend-instance-token"

terminate_tree() {
    local pid="$1"
    local children
    children="$(pgrep -P "$pid" 2>/dev/null || true)"
    for child in $children; do
        terminate_tree "$child"
    done
    kill "$pid" >/dev/null 2>&1 || true
}

force_kill_tree() {
    local pid="$1"
    local children
    children="$(pgrep -P "$pid" 2>/dev/null || true)"
    for child in $children; do
        force_kill_tree "$child"
    done
    kill -9 "$pid" >/dev/null 2>&1 || true
}

stop_pid_file() {
    local label="$1"
    local file="$2"
    if [ ! -f "$file" ]; then
        echo "$label 未记录 PID，跳过"
        return 0
    fi

    local pid
    pid="$(tr -d '[:space:]' < "$file")"
    if [ -z "$pid" ]; then
        rm -f "$file"
        echo "$label PID 为空，已清理"
        return 0
    fi

    if ! kill -0 "$pid" >/dev/null 2>&1; then
        rm -f "$file"
        echo "$label 已不在运行，已清理"
        return 0
    fi

    echo "正在停止 $label (PID $pid)..."
    terminate_tree "$pid"
    for _ in $(seq 1 8); do
        if ! kill -0 "$pid" >/dev/null 2>&1; then
            rm -f "$file"
            echo "$label 已停止"
            return 0
        fi
        sleep 0.5
    done

    echo "$label 未正常退出，强制停止..."
    force_kill_tree "$pid"
    rm -f "$file"
}

stop_pid_file "前端" "$FRONTEND_PID_FILE"
stop_pid_file "后端" "$BACKEND_PID_FILE"
rm -f "$BACKEND_TOKEN_FILE"

echo "完成"
