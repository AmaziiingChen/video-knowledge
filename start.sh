#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

export PATH="/opt/miniconda3/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

ROOT_DIR="$(pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/data/run"
LOG_DIR="$ROOT_DIR/data/logs"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:5173"

if [ -z "${PYTHON_BIN:-}" ]; then
    if command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        PYTHON_BIN="python3"
    fi
fi

mkdir -p "$RUN_DIR" "$LOG_DIR"

is_pid_alive() {
    local pid="$1"
    [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1
}

read_pid_file() {
    local file="$1"
    if [ -f "$file" ]; then
        tr -d '[:space:]' < "$file"
    fi
}

url_ready() {
    local url="$1"
    curl -s "$url" >/dev/null 2>&1
}

port_in_use() {
    local port="$1"
    lsof -i :"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

wait_for_url() {
    local label="$1"
    local url="$2"
    local log_file="$3"
    local max_seconds="${4:-45}"

    echo "  等待${label}就绪..."
    for _ in $(seq 1 "$max_seconds"); do
        if url_ready "$url"; then
            echo "  ${label}就绪"
            return 0
        fi
        sleep 1
    done

    echo "  ${label} ${max_seconds} 秒内未就绪。最近日志："
    tail -n 40 "$log_file" 2>/dev/null || true
    return 1
}

ensure_backend() {
    if url_ready "$BACKEND_URL/api/health"; then
        echo "[1/2] 后端已在运行，直接复用"
        return 0
    fi

    if port_in_use 8000; then
        echo "[1/2] 端口 8000 已被占用，但后端健康检查未通过。"
        lsof -i :8000 -sTCP:LISTEN -n -P || true
        exit 1
    fi

    echo "[1/2] 启动后端..."
    : > "$BACKEND_LOG"
    (
        cd "$BACKEND_DIR"
        exec nohup "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port 8000
    ) >> "$BACKEND_LOG" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"

    wait_for_url "后端" "$BACKEND_URL/api/health" "$BACKEND_LOG" 45
}

ensure_frontend() {
    if url_ready "$FRONTEND_URL"; then
        echo "[2/2] 前端已在运行，直接复用"
        return 0
    fi

    if port_in_use 5173; then
        echo "[2/2] 端口 5173 已被占用，但前端页面不可访问。"
        lsof -i :5173 -sTCP:LISTEN -n -P || true
        exit 1
    fi

    echo "[2/2] 启动前端..."
    : > "$FRONTEND_LOG"
    (
        cd "$FRONTEND_DIR"
        exec nohup npm run dev -- --host 127.0.0.1
    ) >> "$FRONTEND_LOG" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"

    wait_for_url "前端" "$FRONTEND_URL" "$FRONTEND_LOG" 45
}

print_status() {
    local backend_pid frontend_pid
    backend_pid="$(read_pid_file "$BACKEND_PID_FILE")"
    frontend_pid="$(read_pid_file "$FRONTEND_PID_FILE")"

    echo ""
    echo "=========================================="
    echo "  Video Knowledge 已就绪"
    echo "=========================================="
    echo "  前端:    $FRONTEND_URL"
    echo "  后端:    $BACKEND_URL"
    echo "  API文档: $BACKEND_URL/docs"
    echo "  日志:    $LOG_DIR"
    if is_pid_alive "$backend_pid"; then
        echo "  后端 PID: $backend_pid"
    fi
    if is_pid_alive "$frontend_pid"; then
        echo "  前端 PID: $frontend_pid"
    fi
    echo "=========================================="
    echo "  关闭服务: ./stop.sh"
    echo ""
}

echo "[0/2] 启动前自检..."
if ! "$PYTHON_BIN" scripts/preflight.py --skip-port-check; then
    echo ""
    echo "自检未通过，已停止启动。"
    exit 1
fi

ensure_backend
ensure_frontend

if [ "${OPEN_BROWSER:-1}" != "0" ]; then
    open "$FRONTEND_URL" >/dev/null 2>&1 || true
fi
print_status
