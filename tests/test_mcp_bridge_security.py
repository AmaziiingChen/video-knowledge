from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from services.mcp_bridge_security import (
    MCP_ALLOWED_API_TEMPLATES,
    McpBridgeUnavailable,
    is_mcp_api_request_allowed,
    mcp_bridge_lease_is_valid,
    read_mcp_bridge_api_base,
    read_mcp_bridge_token,
    validated_mcp_api_base,
)

ALLOWED_REQUESTS = (
    ("POST", "/api/ingest/link"),
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/task-1"),
    ("POST", "/api/tasks/task-1/retry"),
    ("GET", "/api/search"),
    ("GET", "/api/openclaw-gateway"),
    ("GET", "/api/agent/workspace-overview"),
    ("GET", "/api/wechat-report-groups"),
    ("POST", "/api/openclaw/report-tasks"),
    ("GET", "/api/openclaw/report-tasks/task-1"),
    ("POST", "/api/openclaw/report-tasks/task-1/draft"),
    ("GET", "/api/openclaw/conversation-tasks"),
    ("POST", "/api/openclaw/conversation-tasks"),
    ("POST", "/api/openclaw/conversation-tasks/claim-notification"),
    ("POST", "/api/openclaw/conversation-turns"),
    ("GET", "/api/markdown/content/item-1/export"),
    ("GET", "/api/wechat-subscriptions/accounts/account-1/search"),
    ("GET", "/api/wechat-subscriptions"),
    ("POST", "/api/wechat-subscriptions"),
    ("GET", "/api/wechat-feed/articles.json"),
    ("GET", "/api/wechat-feed/article/article-1.md"),
)


@pytest.mark.parametrize(("method", "path"), ALLOWED_REQUESTS)
def test_mcp_allowlist_covers_only_the_declared_method_and_path(method, path):
    assert is_mcp_api_request_allowed(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("DELETE", "/api/tasks/task-1"),
        ("POST", "/api/tasks"),
        ("GET", "/api/tasks/task-1/retry"),
        ("GET", "/api/config"),
        ("GET", "/api/media"),
        ("GET", "/api/tasks/task-1/extra"),
        ("GET", "/api/tasks/../config"),
        ("GET", "/api/tasks//task-1"),
        ("GET", "/api/tasks/task%2F1"),
        ("GET", "http://127.0.0.1:8000/api/tasks"),
    ),
)
def test_mcp_allowlist_rejects_wrong_methods_and_ambiguous_paths(method, path):
    assert not is_mcp_api_request_allowed(method, path)


def _write_secure(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def test_bridge_token_reader_rejects_symlinks_and_wide_permissions(tmp_path):
    token_file = tmp_path / "run" / "token"
    _write_secure(token_file, "a" * 43)
    assert read_mcp_bridge_token(str(token_file)) == "a" * 43

    token_file.chmod(0o644)
    with pytest.raises(McpBridgeUnavailable, match="不安全"):
        read_mcp_bridge_token(str(token_file))

    token_file.unlink()
    target = tmp_path / "target"
    target.write_text("b" * 43, encoding="utf-8")
    token_file.symlink_to(target)
    with pytest.raises(McpBridgeUnavailable, match="尚未就绪"):
        read_mcp_bridge_token(str(token_file))


def test_bridge_lease_requires_matching_fresh_session(tmp_path, monkeypatch):
    lease_file = tmp_path / "run" / "lease.json"
    _write_secure(
        lease_file,
        json.dumps(
            {
                "session_id": "session-1",
                "updated_at": 100.0,
                "api_base": "http://127.0.0.1:8000/api",
            }
        ),
    )
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID", "session-1")
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE", str(lease_file))

    assert mcp_bridge_lease_is_valid(now=110.0)
    assert not mcp_bridge_lease_is_valid(now=116.0)
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID", "session-2")
    assert not mcp_bridge_lease_is_valid(now=110.0)


@pytest.mark.parametrize(
    "value",
    (
        "https://127.0.0.1:8000/api",
        "http://localhost:8000/api",
        "http://example.com:8000/api",
        "http://127.0.0.1:8000/private",
        "http://user@127.0.0.1:8000/api",
        "http://127.0.0.1:8000/api?token=x",
    ),
)
def test_mcp_api_base_rejects_any_noncanonical_loopback_target(value):
    with pytest.raises(McpBridgeUnavailable, match="回环|无效"):
        validated_mcp_api_base(value)


def test_mcp_api_base_accepts_ipv4_and_explicit_ipv6_loopback():
    assert validated_mcp_api_base("http://127.0.0.1:8000/api/") == "http://127.0.0.1:8000/api"
    assert validated_mcp_api_base("http://[::1]:8000/api") == "http://[::1]:8000/api"


def test_mcp_api_base_rejects_another_loopback_service_port():
    with pytest.raises(McpBridgeUnavailable, match="回环"):
        validated_mcp_api_base("http://127.0.0.1:8123/api")


def test_mcp_client_reads_the_api_endpoint_from_the_private_session_lease(tmp_path):
    token_file = tmp_path / "run" / "mcp-bridge-token"
    lease_file = tmp_path / "run" / "mcp-bridge-lease.json"
    _write_secure(token_file, "a" * 43)
    _write_secure(
        lease_file,
        json.dumps(
            {
                "session_id": "session-1",
                "updated_at": 100.0,
                "api_base": "http://127.0.0.1:8123/api",
            }
        ),
    )

    assert read_mcp_bridge_api_base(str(token_file)) == "http://127.0.0.1:8123/api"


def _request_path_template(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return f"/api{node.value}"
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            parts.append(value.value if isinstance(value, ast.Constant) else "{segment}")
        return f"/api{''.join(parts)}"
    raise AssertionError(f"unsupported MCP request path expression: {ast.dump(node)}")


def test_every_mcp_tool_request_is_explicitly_covered_by_the_shared_policy():
    source = (Path(__file__).resolve().parents[1] / "backend" / "mcp_server.py").read_text()
    tree = ast.parse(source)
    requests = {
        (call.args[0].value, _request_path_template(call.args[1]))
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_request"
        and len(call.args) >= 2
        and isinstance(call.args[0], ast.Constant)
    }

    assert requests == set(MCP_ALLOWED_API_TEMPLATES)
