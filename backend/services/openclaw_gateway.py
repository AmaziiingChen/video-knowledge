from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from threading import Lock
import time
from typing import Any


class OpenClawGatewayError(RuntimeError):
    pass


_STATUS_CACHE_SECONDS = 20.0
_status_cache: dict[str, Any] | None = None
_status_cache_expires_at = 0.0
_status_cache_lock = Lock()


def _openclaw_path() -> str | None:
    configured = os.environ.get("OPENCLAW_BIN", "").strip()
    candidates = [configured, shutil.which("openclaw"), str(Path.home() / ".npm-global/bin/openclaw")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _run_openclaw(*args: str, timeout: float = 20) -> subprocess.CompletedProcess[str]:
    executable = _openclaw_path()
    if not executable:
        raise OpenClawGatewayError("未找到 OpenClaw CLI")
    try:
        return subprocess.run(
            [executable, "gateway", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenClawGatewayError("OpenClaw 状态检查超时") from exc
    except OSError as exc:
        raise OpenClawGatewayError(f"无法执行 OpenClaw：{exc}") from exc


def _run_openclaw_cli(*args: str, timeout: float = 12) -> subprocess.CompletedProcess[str]:
    """Run a read-only OpenClaw CLI command outside the Gateway subcommand."""
    executable = _openclaw_path()
    if not executable:
        raise OpenClawGatewayError("未找到 OpenClaw CLI")
    try:
        return subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OpenClawGatewayError("OpenClaw 状态检查超时") from exc
    except OSError as exc:
        raise OpenClawGatewayError(f"无法执行 OpenClaw：{exc}") from exc


def _read_json(output: str) -> dict:
    start = output.find("{")
    if start < 0:
        raise ValueError("未返回 JSON 状态")
    return json.loads(output[start:])


def _openclaw_config() -> dict[str, Any]:
    configured = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    path = Path(configured).expanduser() if configured else Path.home() / ".openclaw" / "openclaw.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _mcp_status() -> dict[str, Any]:
    servers = ((_openclaw_config().get("mcp") or {}).get("servers") or {})
    configured = isinstance(servers, dict) and "knowledgehub" in servers
    return {
        "state": "configured" if configured else "missing",
        "configured": configured,
        "detail": "KnowledgeHub MCP 已配置" if configured else "尚未配置 KnowledgeHub MCP",
    }


def _wechat_channel_status() -> dict[str, Any]:
    """Read OpenClaw's human-oriented channel status without exposing its config."""
    try:
        result = _run_openclaw_cli("channels", "status", "--deep")
    except OpenClawGatewayError as exc:
        return {"state": "unknown", "configured": False, "running": False, "detail": str(exc)}

    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    channel_line = next(
        (line.strip() for line in output.splitlines() if "openclaw-weixin" in line.casefold()),
        "",
    )
    normalized = channel_line.casefold()
    configured = "configured" in normalized
    running = all(word in normalized for word in ("enabled", "configured", "running"))
    if running:
        detail = "微信通道已连接，收到链接后会交给 OpenClaw"
        state = "running"
    elif channel_line:
        detail = "微信通道已配置，但当前未运行"
        state = "offline"
    else:
        detail = "未检测到 OpenClaw 微信通道"
        state = "missing"
    return {"state": state, "configured": configured, "running": running, "detail": detail}


def _backend_status() -> dict[str, Any]:
    # This code runs inside the API process, so a successful response proves
    # that the local ingest endpoint is available to the MCP bridge.
    return {"state": "running", "ready": True, "detail": "KnowledgeHub 后端可接收链接"}


def _gateway_status() -> dict[str, Any]:
    executable = _openclaw_path()
    checked_at = datetime.now(timezone.utc).isoformat()
    if not executable:
        return {
            "state": "unavailable",
            "detail": "未找到 OpenClaw CLI",
            "installed": False,
            "service_installed": False,
            "gateway_running": False,
            "version": None,
            "checked_at": checked_at,
        }

    try:
        result = _run_openclaw("status", "--json")
    except OpenClawGatewayError as exc:
        return {
            "state": "error",
            "detail": str(exc),
            "installed": True,
            "service_installed": False,
            "gateway_running": False,
            "version": None,
            "checked_at": checked_at,
        }
    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    try:
        payload = _read_json(result.stdout)
    except (ValueError, json.JSONDecodeError):
        return {
            "state": "error",
            "detail": output or "无法读取 OpenClaw Gateway 状态",
            "installed": True,
            "service_installed": False,
            "gateway_running": False,
            "version": None,
            "checked_at": checked_at,
        }

    service = payload.get("service") or {}
    runtime = service.get("runtime") or {}
    rpc = payload.get("rpc") or {}
    missing_service = bool(runtime.get("missingUnit"))
    gateway_running = bool(rpc.get("ok"))

    if gateway_running:
        state = "running"
        detail = "Gateway 与本地 RPC 已连接"
    elif missing_service:
        state = "not_installed"
        detail = "Gateway 服务尚未安装"
    else:
        state = "offline"
        detail = str(rpc.get("error") or runtime.get("detail") or "Gateway 未响应")

    return {
        "state": state,
        "detail": detail,
        "installed": True,
        "service_installed": not missing_service,
        "gateway_running": gateway_running,
        "version": (payload.get("cli") or {}).get("version"),
        "checked_at": checked_at,
    }


def get_openclaw_status(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return the whole message-to-ingest path, caching CLI work between UI polls."""
    global _status_cache, _status_cache_expires_at
    now = time.monotonic()
    with _status_cache_lock:
        if not force_refresh and _status_cache is not None and now < _status_cache_expires_at:
            return _status_cache

    gateway = _gateway_status()
    mcp = _mcp_status()
    wechat = _wechat_channel_status() if gateway["installed"] else {
        "state": "missing",
        "configured": False,
        "running": False,
        "detail": "需要先安装 OpenClaw 才能连接微信",
    }
    backend = _backend_status()
    from services.openclaw_conversations import get_conversation_settings, list_conversations

    conversation_settings = get_conversation_settings()
    conversations = list_conversations(limit=100)
    mapping = {
        "state": "ready",
        "configured": True,
        "conversation_count": len(conversations),
        "task_binding_count": sum(int(item["task_count"]) for item in conversations),
        "transcript_mirror_enabled": conversation_settings["transcript_mirror_enabled"],
        "transcript_retention_days": conversation_settings["transcript_retention_days"],
        "detail": (
            "会话—任务映射已启用；完整对话仅在你主动开启后保存"
            if not conversation_settings["transcript_mirror_enabled"]
            else f"会话—任务映射已启用；完整对话本地保留 {conversation_settings['transcript_retention_days']} 天"
        ),
    }
    automation_ready = bool(gateway["gateway_running"] and wechat["running"] and mcp["configured"] and backend["ready"])
    status = {
        **gateway,
        "automation_ready": automation_ready,
        "backend": backend,
        "mcp": mcp,
        "wechat": wechat,
        "conversation_mapping": mapping,
    }
    with _status_cache_lock:
        _status_cache = status
        _status_cache_expires_at = time.monotonic() + _STATUS_CACHE_SECONDS
    return status


def _ensure_command_succeeded(result: subprocess.CompletedProcess[str], action: str) -> None:
    if result.returncode == 0:
        return
    detail = "\n".join(part for part in [result.stderr, result.stdout] if part).strip()
    raise OpenClawGatewayError(detail or f"OpenClaw {action}失败")


def start_openclaw_gateway() -> dict:
    status = get_openclaw_status(force_refresh=True)
    if not status["installed"]:
        raise OpenClawGatewayError(status["detail"])
    if status["state"] == "error":
        raise OpenClawGatewayError(status["detail"])

    if not status["service_installed"]:
        _ensure_command_succeeded(_run_openclaw("install", "--json", timeout=30), "服务安装")

    _ensure_command_succeeded(_run_openclaw("start", "--json", timeout=30), "服务启动")
    for _ in range(8):
        status = get_openclaw_status(force_refresh=True)
        if status["gateway_running"]:
            return status
        time.sleep(0.75)
    return status
