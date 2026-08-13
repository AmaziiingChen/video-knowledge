#!/bin/bash
set -euo pipefail
umask 077

cd "$(dirname "$0")"

export PATH="/opt/miniconda3/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

ROOT_DIR="$(pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
RUN_DIR="$ROOT_DIR/data/run"
LOG_DIR="$ROOT_DIR/data/logs"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
BACKEND_TOKEN_FILE="$RUN_DIR/backend-instance-token"
MCP_TOKEN_FILE="$RUN_DIR/mcp-bridge-token"
MCP_LEASE_FILE="$RUN_DIR/mcp-bridge-lease.json"
MCP_HEARTBEAT_PID_FILE="$RUN_DIR/mcp-bridge-heartbeat.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_URL="http://127.0.0.1:8000"
FRONTEND_URL="http://127.0.0.1:5173"
INSTANCE_TOKEN=""
MCP_TOKEN=""
MCP_SESSION_ID=""
MCP_SESSION_STARTED=0
MCP_HEARTBEAT_PID=""
STARTED_BACKEND_PID=""
STARTED_FRONTEND_PID=""
STARTUP_COMPLETE=0

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

read_instance_token() {
    if [ -f "$BACKEND_TOKEN_FILE" ]; then
        INSTANCE_TOKEN="$(tr -d '[:space:]' < "$BACKEND_TOKEN_FILE")"
    fi
}

generate_instance_token() {
    "$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))'
}

write_instance_token() {
    printf '%s\n' "$INSTANCE_TOKEN" > "$BACKEND_TOKEN_FILE"
    chmod 600 "$BACKEND_TOKEN_FILE"
}

stop_stale_mcp_heartbeat() {
    local pid="" command_line=""
    if [ -L "$MCP_HEARTBEAT_PID_FILE" ]; then
        echo "MCP bridge 心跳 PID 文件不安全，请先检查 $MCP_HEARTBEAT_PID_FILE"
        return 1
    fi
    if [ -f "$MCP_HEARTBEAT_PID_FILE" ]; then
        pid="$(tr -d '[:space:]' < "$MCP_HEARTBEAT_PID_FILE")"
    fi
    if ! is_pid_alive "$pid"; then
        rm -f "$MCP_HEARTBEAT_PID_FILE"
        return 0
    fi
    command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    case "$command_line" in
        *manage_mcp_bridge_session.py*heartbeat*"$MCP_LEASE_FILE"*) ;;
        *)
            echo "PID $pid 不是 KnowledgeHub MCP bridge 心跳，拒绝终止"
            return 1
            ;;
    esac
    kill "$pid" >/dev/null 2>&1 || true
    for _ in $(seq 1 20); do
        if ! is_pid_alive "$pid"; then
            rm -f "$MCP_HEARTBEAT_PID_FILE"
            return 0
        fi
        sleep 0.1
    done
    echo "旧 MCP bridge 心跳未能停止，请先运行 ./stop.sh"
    return 1
}

start_mcp_bridge_session() {
    local session_json
    stop_stale_mcp_heartbeat
    session_json="$("$PYTHON_BIN" scripts/manage_mcp_bridge_session.py create \
        --run-dir "$RUN_DIR" \
        --api-base "$BACKEND_URL/api")"
    MCP_SESSION_STARTED=1
    MCP_TOKEN="$(printf '%s' "$session_json" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
    MCP_SESSION_ID="$(printf '%s' "$session_json" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"
    (
        exec "$PYTHON_BIN" scripts/manage_mcp_bridge_session.py heartbeat \
            --lease-file "$MCP_LEASE_FILE" \
            --session-id "$MCP_SESSION_ID" \
            --api-base "$BACKEND_URL/api" \
            --interval 5
    ) >> "$LOG_DIR/mcp-bridge.log" 2>&1 &
    MCP_HEARTBEAT_PID=$!
    echo "$MCP_HEARTBEAT_PID" > "$MCP_HEARTBEAT_PID_FILE"
}

cleanup_failed_start() {
    local status=$?
    if [ "$status" -ne 0 ] && [ "$STARTUP_COMPLETE" -eq 0 ]; then
        if is_pid_alive "$STARTED_FRONTEND_PID"; then
            kill "$STARTED_FRONTEND_PID" >/dev/null 2>&1 || true
            rm -f "$FRONTEND_PID_FILE"
        fi
        if is_pid_alive "$STARTED_BACKEND_PID"; then
            kill "$STARTED_BACKEND_PID" >/dev/null 2>&1 || true
            rm -f "$BACKEND_PID_FILE"
        fi
        if [ "$MCP_SESSION_STARTED" -eq 1 ]; then
            if is_pid_alive "$MCP_HEARTBEAT_PID"; then
                kill "$MCP_HEARTBEAT_PID" >/dev/null 2>&1 || true
                for _ in $(seq 1 20); do
                    is_pid_alive "$MCP_HEARTBEAT_PID" || break
                    sleep 0.1
                done
            fi
            "$PYTHON_BIN" scripts/manage_mcp_bridge_session.py cleanup --run-dir "$RUN_DIR" \
                >/dev/null 2>&1 || true
            rm -f "$MCP_HEARTBEAT_PID_FILE"
        fi
    fi
    return "$status"
}

trap cleanup_failed_start EXIT

mcp_bridge_ready() {
    local heartbeat_pid=""
    if [ -f "$MCP_HEARTBEAT_PID_FILE" ]; then
        heartbeat_pid="$(tr -d '[:space:]' < "$MCP_HEARTBEAT_PID_FILE")"
    fi
    is_pid_alive "$heartbeat_pid" \
        && "$PYTHON_BIN" scripts/manage_mcp_bridge_session.py validate --run-dir "$RUN_DIR"
}

health_matches_instance_token() {
    local base_url="$1"
    [ -n "$INSTANCE_TOKEN" ] || return 1
    curl -fsS -H "X-KnowledgeHub-Token: $INSTANCE_TOKEN" "$base_url/api/health" \
        | KNOWLEDGEHUB_EXPECTED_TOKEN="$INSTANCE_TOKEN" "$PYTHON_BIN" -c '
import json
import os
import sys
payload = json.load(sys.stdin)
raise SystemExit(0 if payload.get("instance_token") == os.environ["KNOWLEDGEHUB_EXPECTED_TOKEN"] else 1)
'
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
        read_instance_token
        if ! health_matches_instance_token "$BACKEND_URL"; then
            echo "[1/2] 后端已在运行，但不属于当前安全会话。请先运行 ./stop.sh 后重试。"
            exit 1
        fi
        if ! mcp_bridge_ready; then
            echo "[1/2] 后端仍在运行，但 MCP bridge 会话已失效。请先运行 ./stop.sh 后重试。"
            exit 1
        fi
        echo "[1/2] 后端已在运行，安全复用"
        return 0
    fi

    if port_in_use 8000; then
        echo "[1/2] 端口 8000 已被占用，但后端健康检查未通过。"
        lsof -i :8000 -sTCP:LISTEN -n -P || true
        exit 1
    fi

    echo "[1/2] 启动后端..."
    INSTANCE_TOKEN="$(generate_instance_token)"
    write_instance_token
    start_mcp_bridge_session
    : > "$BACKEND_LOG"
    (
        cd "$BACKEND_DIR"
        exec env \
            KNOWLEDGEHUB_INSTANCE_TOKEN="$INSTANCE_TOKEN" \
            KNOWLEDGEHUB_MCP_BRIDGE_TOKEN="$MCP_TOKEN" \
            KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID="$MCP_SESSION_ID" \
            KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE="$MCP_TOKEN_FILE" \
            KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE="$MCP_LEASE_FILE" \
            nohup "$PYTHON_BIN" -m uvicorn main:app --host 127.0.0.1 --port 8000
    ) >> "$BACKEND_LOG" 2>&1 &
    STARTED_BACKEND_PID=$!
    echo "$STARTED_BACKEND_PID" > "$BACKEND_PID_FILE"

    wait_for_url "后端" "$BACKEND_URL/api/health" "$BACKEND_LOG" 45
}

ensure_frontend() {
    if url_ready "$FRONTEND_URL"; then
        if ! health_matches_instance_token "$FRONTEND_URL"; then
            echo "[2/2] 前端已在运行，但不属于当前安全会话。请先运行 ./stop.sh 后重试。"
            exit 1
        fi
        echo "[2/2] 前端已在运行，安全复用"
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
        exec env KNOWLEDGEHUB_INSTANCE_TOKEN="$INSTANCE_TOKEN" nohup npm run dev -- --host 127.0.0.1
    ) >> "$FRONTEND_LOG" 2>&1 &
    STARTED_FRONTEND_PID=$!
    echo "$STARTED_FRONTEND_PID" > "$FRONTEND_PID_FILE"

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
STARTUP_COMPLETE=1
