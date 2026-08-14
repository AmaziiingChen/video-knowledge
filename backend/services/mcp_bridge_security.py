"""Least-privilege, per-session authorization for the local MCP bridge."""

from __future__ import annotations

import json
import os
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlsplit

MCP_TOKEN_HEADER = "X-KnowledgeHub-MCP-Token"
MCP_TOKEN_ENV = "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN"
MCP_TOKEN_FILE_ENV = "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE"
MCP_LEASE_FILE_ENV = "KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE"
MCP_SESSION_ID_ENV = "KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID"
MCP_LEASE_TTL_SECONDS = 15.0
MCP_LEASE_FILENAME = "mcp-bridge-lease.json"

_SEGMENT = r"[A-Za-z0-9._~-]+"
MCP_ALLOWED_API_TEMPLATES = (
    ("POST", "/api/ingest/link"),
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/{segment}"),
    ("POST", "/api/tasks/{segment}/retry"),
    ("GET", "/api/search"),
    ("GET", "/api/openclaw-gateway"),
    ("GET", "/api/agent/workspace-overview"),
    ("GET", "/api/wechat-report-groups"),
    ("POST", "/api/openclaw/report-tasks"),
    ("GET", "/api/openclaw/report-tasks/{segment}"),
    ("POST", "/api/openclaw/report-tasks/{segment}/draft"),
    ("GET", "/api/openclaw/conversation-tasks"),
    ("POST", "/api/openclaw/conversation-tasks"),
    ("POST", "/api/openclaw/conversation-tasks/claim-notification"),
    ("POST", "/api/openclaw/conversation-turns"),
    ("GET", "/api/markdown/content/{segment}/export"),
    ("GET", "/api/wechat-subscriptions/accounts/{segment}/search"),
    ("GET", "/api/wechat-subscriptions"),
    ("POST", "/api/wechat-subscriptions"),
    ("GET", "/api/wechat-feed/articles.json"),
    ("GET", "/api/wechat-feed/article/{segment}.md"),
)


def _route_pattern(template: str) -> re.Pattern[str]:
    escaped = re.escape(template)
    return re.compile(escaped.replace(re.escape("{segment}"), _SEGMENT))


_ALLOWED_ROUTES = tuple(
    (method, _route_pattern(template))
    for method, template in MCP_ALLOWED_API_TEMPLATES
)


class McpBridgeUnavailable(RuntimeError):
    """Raised when the local bridge session cannot be authenticated safely."""


def is_mcp_api_request_allowed(method: str, path: str) -> bool:
    """Match one canonical HTTP method and API path; query strings are excluded."""
    if not path.startswith("/api/"):
        return False
    if "%" in path or "\\" in path or "//" in path:
        return False
    if any(segment in {"", ".", ".."} for segment in path.split("/")[1:]):
        return False
    normalized_method = method.upper()
    return any(
        normalized_method == allowed_method and pattern.fullmatch(path)
        for allowed_method, pattern in _ALLOWED_ROUTES
    )


def validated_mcp_api_base(
    value: str | None = None,
    *,
    expected_port: int | None = 8000,
) -> str:
    """Accept only a direct loopback HTTP API base before attaching a capability."""
    raw = (value if value is not None else "http://127.0.0.1:8000/api").strip()
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise McpBridgeUnavailable("KnowledgeHub MCP 的本机 API 地址无效") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/api"
        or port is None
        or (expected_port is not None and port != expected_port)
    ):
        raise McpBridgeUnavailable("KnowledgeHub MCP 仅允许连接本机回环 API")
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}/api"


def expected_backend_api_base() -> str:
    host = os.environ.get("KNOWLEDGEHUB_BACKEND_HOST", "127.0.0.1").strip()
    if host == "localhost":
        host = "127.0.0.1"
    raw_port = os.environ.get("KNOWLEDGEHUB_BACKEND_PORT", "8000").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise McpBridgeUnavailable("KnowledgeHub MCP 的本机 API 端口无效") from exc
    literal_host = "[::1]" if host == "::1" else host
    return validated_mcp_api_base(
        f"http://{literal_host}:{port}/api",
        expected_port=port,
    )


def _read_secure_file(path_value: str, *, max_bytes: int) -> bytes:
    path = Path(path_value)
    if not path.is_absolute():
        raise McpBridgeUnavailable("KnowledgeHub MCP capability 路径必须是绝对路径")
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        directory_descriptor = os.open(path.parent, directory_flags)
    except OSError as exc:
        raise McpBridgeUnavailable("KnowledgeHub MCP bridge 尚未就绪") from exc
    try:
        parent_stat = os.fstat(directory_descriptor)
    except OSError as exc:
        os.close(directory_descriptor)
        raise McpBridgeUnavailable("KnowledgeHub MCP bridge 尚未就绪") from exc
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or (current_uid is not None and parent_stat.st_uid != current_uid)
        or parent_stat.st_mode & 0o077
    ):
        os.close(directory_descriptor)
        raise McpBridgeUnavailable("KnowledgeHub MCP bridge 目录不安全")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path.name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        os.close(directory_descriptor)
        raise McpBridgeUnavailable("KnowledgeHub MCP bridge 尚未就绪") from exc
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_nlink != 1
            or (current_uid is not None and file_stat.st_uid != current_uid)
            or file_stat.st_mode & 0o077
            or file_stat.st_size <= 0
            or file_stat.st_size > max_bytes
        ):
            raise McpBridgeUnavailable("KnowledgeHub MCP capability 文件不安全")
        payload = os.read(descriptor, max_bytes + 1)
        if len(payload) > max_bytes or os.read(descriptor, 1):
            raise McpBridgeUnavailable("KnowledgeHub MCP capability 文件无效")
        return payload
    finally:
        os.close(descriptor)
        os.close(directory_descriptor)


def read_mcp_bridge_token(path_value: str | None = None) -> str:
    """Read one bounded token from the secure per-session file descriptor."""
    configured_path = path_value or os.environ.get(MCP_TOKEN_FILE_ENV, "")
    if not configured_path:
        raise McpBridgeUnavailable(
            "KnowledgeHub MCP bridge 尚未就绪。请保持 KnowledgeHub 打开，等待本机服务连接完成后重试。"
        )
    try:
        raw = _read_secure_file(configured_path, max_bytes=160).decode("ascii")
    except UnicodeDecodeError as exc:
        raise McpBridgeUnavailable("KnowledgeHub MCP capability 文件无效") from exc
    token = raw.strip()
    if not 32 <= len(token) <= 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise McpBridgeUnavailable("KnowledgeHub MCP capability 文件无效")
    return token


def read_mcp_bridge_api_base(token_path_value: str | None = None) -> str:
    """Read the loopback API endpoint issued by the trusted session owner."""
    configured_token_path = token_path_value or os.environ.get(MCP_TOKEN_FILE_ENV, "")
    if not configured_token_path:
        raise McpBridgeUnavailable(
            "KnowledgeHub MCP bridge 尚未就绪。请保持 KnowledgeHub 打开，等待本机服务连接完成后重试。"
        )
    lease_path = Path(configured_token_path).with_name(MCP_LEASE_FILENAME)
    try:
        payload = json.loads(_read_secure_file(str(lease_path), max_bytes=512))
        api_base = validated_mcp_api_base(str(payload["api_base"]), expected_port=None)
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise McpBridgeUnavailable("KnowledgeHub MCP bridge 地址无效") from exc
    return api_base


def mcp_bridge_lease_is_valid(*, now: float | None = None) -> bool:
    """Reject an orphan backend after the Electron/source parent stops heartbeating."""
    session_id = os.environ.get(MCP_SESSION_ID_ENV, "").strip()
    lease_path = os.environ.get(MCP_LEASE_FILE_ENV, "").strip()
    if not session_id or not lease_path:
        return False
    try:
        payload = json.loads(_read_secure_file(lease_path, max_bytes=512))
        updated_at = float(payload["updated_at"])
    except (McpBridgeUnavailable, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    if payload.get("session_id") != session_id:
        return False
    try:
        if validated_mcp_api_base(str(payload["api_base"]), expected_port=None) != expected_backend_api_base():
            return False
    except (KeyError, McpBridgeUnavailable):
        return False
    current = time.time() if now is None else now
    age = current - updated_at
    return -5.0 <= age <= MCP_LEASE_TTL_SECONDS
