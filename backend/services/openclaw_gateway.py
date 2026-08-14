from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from services.mcp_bridge_security import (
    MCP_TOKEN_ENV,
    MCP_TOKEN_FILE_ENV,
    McpBridgeUnavailable,
    expected_backend_api_base,
    mcp_bridge_lease_is_valid,
    read_mcp_bridge_api_base,
    read_mcp_bridge_token,
    validated_mcp_api_base,
)


class OpenClawGatewayError(RuntimeError):
    pass


_STATUS_CACHE_SECONDS = 20.0
_status_cache: dict[str, Any] | None = None
_status_cache_expires_at = 0.0
_status_cache_lock = Lock()
_mcp_probe_lock = Lock()
_mcp_probe_key: tuple[Any, ...] | None = None
_mcp_probe_result = False
_mcp_probe_retry_at = 0.0


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


def _probe_mcp_stdio(
    command: str,
    arguments: list[str],
    environment: dict[str, str],
) -> bool:
    """Prove the configured entry can initialize and list tools without using an API tool."""
    from mcp.types import LATEST_PROTOCOL_VERSION

    messages = (
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "knowledgehub-status", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    payload = "".join(json.dumps(message, separators=(",", ":")) + "\n" for message in messages)
    runtime_environment_keys = {
        "PATH",
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "CONDA_PREFIX",
        "VIRTUAL_ENV",
        "SYSTEMROOT",
        "WINDIR",
    }
    child_environment = {
        key: value for key, value in os.environ.items() if key in runtime_environment_keys
    }
    child_environment.update(environment)
    try:
        result = subprocess.run(
            [command, *arguments],
            input=payload,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            env=child_environment,
            cwd=(Path(arguments[0]).parent if len(arguments) > 1 else Path(command).parent),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    responses: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        try:
            response = json.loads(line)
        except json.JSONDecodeError:
            return False
        if isinstance(response, dict) and isinstance(response.get("id"), int):
            responses[response["id"]] = response
    initialized = isinstance((responses.get(1) or {}).get("result"), dict)
    tools_result = (responses.get(2) or {}).get("result")
    tools = tools_result.get("tools") if isinstance(tools_result, dict) else None
    return result.returncode == 0 and initialized and isinstance(tools, list) and bool(tools)


def _mcp_stdio_probe_cached(
    command: str,
    arguments: list[str],
    environment: dict[str, str],
) -> bool:
    global _mcp_probe_key, _mcp_probe_result, _mcp_probe_retry_at
    try:
        command_stat = Path(command).stat()
        command_identity = (command_stat.st_size, command_stat.st_mtime_ns)
    except OSError:
        return False
    key = (
        command,
        tuple(arguments),
        tuple(sorted(environment.items())),
        command_identity,
    )
    now = time.monotonic()
    with _mcp_probe_lock:
        if key == _mcp_probe_key and (_mcp_probe_result or now < _mcp_probe_retry_at):
            return _mcp_probe_result
        result = _probe_mcp_stdio(command, arguments, environment)
        _mcp_probe_key = key
        _mcp_probe_result = result
        _mcp_probe_retry_at = 0.0 if result else now + 60.0
        return result


def _expected_mcp_entry_arguments() -> list[str]:
    arguments = ["--mcp-stdio"]
    if not getattr(sys, "frozen", False):
        arguments.insert(0, str(Path(__file__).resolve().parents[1] / "desktop_server.py"))
    return arguments


def _current_mcp_descriptor() -> dict[str, Any]:
    """Build the one safe OpenClaw entry for the running desktop session."""
    token_file = os.environ.get(MCP_TOKEN_FILE_ENV, "").strip()
    expected_token = os.environ.get(MCP_TOKEN_ENV, "").strip()
    try:
        issued_api_base = read_mcp_bridge_api_base(token_file)
        bridge_ready = bool(
            token_file
            and expected_token
            and hmac.compare_digest(read_mcp_bridge_token(token_file), expected_token)
            and issued_api_base == expected_backend_api_base()
            and mcp_bridge_lease_is_valid()
        )
    except McpBridgeUnavailable as exc:
        raise OpenClawGatewayError("KnowledgeHub MCP bridge 尚未就绪，请先保持应用运行") from exc
    if not bridge_ready:
        raise OpenClawGatewayError("KnowledgeHub MCP bridge 尚未就绪，请先保持应用运行")
    return {
        "command": str(Path(sys.executable).resolve()),
        "args": _expected_mcp_entry_arguments(),
        "env": {
            MCP_TOKEN_FILE_ENV: token_file,
            "KNOWLEDGEHUB_API_BASE": issued_api_base,
        },
    }


def _clear_status_cache() -> None:
    global _status_cache, _status_cache_expires_at
    with _status_cache_lock:
        _status_cache = None
        _status_cache_expires_at = 0.0


def _mcp_status() -> dict[str, Any]:
    servers = ((_openclaw_config().get("mcp") or {}).get("servers") or {})
    descriptor = servers.get("knowledgehub") if isinstance(servers, dict) else None
    if not isinstance(descriptor, dict):
        return {
            "state": "missing",
            "configured": False,
            "detail": "尚未配置 KnowledgeHub MCP",
        }
    command = str(descriptor.get("command") or "").strip()
    arguments = descriptor.get("args")
    environment = descriptor.get("env")
    resolved_command = ""
    if command:
        candidate = Path(command).expanduser()
        if candidate.is_absolute() or "/" in command:
            resolved_command = (
                str(candidate.resolve())
                if candidate.is_file() and os.access(candidate, os.X_OK)
                else ""
            )
        else:
            discovered = shutil.which(command) or ""
            resolved_command = str(Path(discovered).resolve()) if discovered else ""
    expected_command = str(Path(sys.executable).resolve())
    expected_arguments = _expected_mcp_entry_arguments()
    valid_command = resolved_command == expected_command
    valid_arguments = arguments == expected_arguments
    allowed_environment_keys = {MCP_TOKEN_FILE_ENV, "KNOWLEDGEHUB_API_BASE"}
    valid_environment = (
        isinstance(environment, dict)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in environment.items())
        and set(environment).issubset(allowed_environment_keys)
    )
    expected_token_file = os.environ.get(MCP_TOKEN_FILE_ENV, "").strip()
    configured_token_file = (
        str(environment.get(MCP_TOKEN_FILE_ENV) or "").strip()
        if isinstance(environment, dict)
        else ""
    )
    expected_token = os.environ.get(MCP_TOKEN_ENV, "").strip()
    try:
        configured_api_base = (
            str(environment.get("KNOWLEDGEHUB_API_BASE") or "").strip()
            if isinstance(environment, dict)
            else ""
        )
        issued_api_base = read_mcp_bridge_api_base(configured_token_file)
        api_base_ready = issued_api_base == expected_backend_api_base()
        if configured_api_base:
            api_base_ready = (
                validated_mcp_api_base(configured_api_base) == issued_api_base
                and api_base_ready
            )
        file_token = read_mcp_bridge_token(configured_token_file)
        capability_ready = bool(
            expected_token_file
            and configured_token_file == expected_token_file
            and expected_token
            and hmac.compare_digest(file_token, expected_token)
            and api_base_ready
            and mcp_bridge_lease_is_valid()
        )
    except McpBridgeUnavailable:
        capability_ready = False
    static_ready = bool(valid_command and valid_arguments and valid_environment and capability_ready)
    callable_ready = bool(
        static_ready
        and _mcp_stdio_probe_cached(
            resolved_command,
            list(arguments),
            {MCP_TOKEN_FILE_ENV: configured_token_file},
        )
    )
    configured = callable_ready
    return {
        "state": "configured" if configured else "invalid",
        "configured": configured,
        "detail": (
            "KnowledgeHub MCP 已通过本机 stdio 握手与 bridge capability 检查"
            if configured
            else "KnowledgeHub MCP 配置存在，但命令或 bridge capability 无效"
        ),
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
    from services.openclaw_conversations import (
        get_conversation_settings,
        list_conversations,
    )

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


def repair_openclaw_mcp() -> dict[str, Any]:
    """Replace only the KnowledgeHub MCP entry and retire cached Gateway runtimes."""
    descriptor = _current_mcp_descriptor()
    serialized_descriptor = json.dumps(descriptor, ensure_ascii=False, separators=(",", ":"))
    _ensure_command_succeeded(
        _run_openclaw_cli("mcp", "set", "knowledgehub", serialized_descriptor, timeout=20),
        "MCP 配置更新",
    )
    # `openclaw mcp reload` disposes runtimes only in that short-lived CLI
    # process.  The WeChat channel runs inside the persistent Gateway
    # LaunchAgent, so an unchanged descriptor can otherwise leave its existing
    # conversation bound to a stale MCP process after KnowledgeHub rotates the
    # bridge session.  Restart the managed Gateway after this explicit repair
    # action so the next turn rebuilds every MCP runtime from the current file.
    _ensure_command_succeeded(
        _run_openclaw("restart", "--json", timeout=30),
        "Gateway 重启",
    )
    _clear_status_cache()
    status = get_openclaw_status(force_refresh=True)
    if not status["mcp"]["configured"]:
        raise OpenClawGatewayError(status["mcp"]["detail"])
    return status
