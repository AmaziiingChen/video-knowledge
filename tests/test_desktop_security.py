from __future__ import annotations

import json
import time

import pytest
from desktop_server import backend_host
from fastapi.testclient import TestClient
from main import app
from routers import runtime_components


def _configure_mcp_bridge(monkeypatch, tmp_path, *, token: str = "mcp-bridge-token-value-1234567890"):
    run_dir = tmp_path / "mcp-run"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    lease_file = run_dir / "lease.json"
    lease_file.write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "updated_at": time.time(),
                "api_base": "http://127.0.0.1:8000/api",
            }
        ),
        encoding="utf-8",
    )
    lease_file.chmod(0o600)
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN", token)
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID", "session-1")
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE", str(lease_file))
    return token


def test_custom_desktop_origin_is_allowed_to_call_the_local_api():
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "knowledgehub://app",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "knowledgehub://app"


def test_health_identifies_the_exact_desktop_backend_instance(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")

    with TestClient(app) as client:
        hidden = client.get("/api/health")
        response = client.get(
            "/api/health",
            headers={"X-KnowledgeHub-Token": "desktop-launch-token"},
        )

    assert hidden.json()["instance_token"] == ""
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "knowledgehub-backend",
        "version": "0.1.2",
        "instance_token": "desktop-launch-token",
    }


def test_private_local_api_requires_the_desktop_instance_token(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")
    monkeypatch.setattr(runtime_components, "install_browser", lambda: {"state": "ready"})

    with TestClient(app) as client:
        read_rejected = client.get("/api/config")
        media_rejected = client.get("/api/media?path=/tmp/managed-media.mp4")
        rejected = client.post("/api/runtime-components/browser/install")
        read_accepted = client.get(
            "/api/config",
            headers={
                "Origin": "knowledgehub://app",
                "X-KnowledgeHub-Token": "desktop-launch-token",
            },
        )
        accepted = client.post(
            "/api/runtime-components/browser/install",
            headers={
                "Origin": "knowledgehub://app",
                "X-KnowledgeHub-Token": "desktop-launch-token",
            },
        )

    assert read_rejected.status_code == 401
    assert media_rejected.status_code == 401
    assert rejected.status_code == 401
    assert read_accepted.status_code == 200
    assert accepted.status_code == 200
    assert accepted.json() == {"state": "ready"}


def test_source_mode_never_allows_an_unconfigured_mutating_api(monkeypatch):
    monkeypatch.delenv("KNOWLEDGEHUB_INSTANCE_TOKEN", raising=False)
    monkeypatch.delenv("KNOWLEDGEHUB_ALLOW_UNAUTHENTICATED_LOCAL_API", raising=False)

    with TestClient(app) as client:
        response = client.post("/api/runtime-components/browser/install")

    assert response.status_code == 503


def test_private_local_api_rejects_an_untrusted_browser_origin(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")

    with TestClient(app) as client:
        response = client.get(
            "/api/config",
            headers={
                "Origin": "https://attacker.invalid",
                "X-KnowledgeHub-Token": "desktop-launch-token",
            },
        )

    assert response.status_code == 403


def test_mcp_capability_allows_only_declared_originless_routes(monkeypatch, tmp_path):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")
    token = _configure_mcp_bridge(monkeypatch, tmp_path)
    headers = {"X-KnowledgeHub-MCP-Token": token}

    with TestClient(app) as client:
        allowed_read = client.get("/api/tasks", headers=headers)
        allowed_query = client.get("/api/search?q=test&ignored=value", headers=headers)
        denied_query_method = client.post("/api/search?q=test", headers=headers)
        allowed_write = client.post(
            "/api/openclaw/conversation-turns",
            headers=headers,
            json={"conversation_key": "session-a", "role": "user", "text": "测试"},
        )
        denied_scope = client.get("/api/config", headers=headers)
        denied_origin = client.get(
            "/api/tasks",
            headers={**headers, "Origin": "knowledgehub://app"},
        )

    assert allowed_read.status_code == 200
    assert allowed_query.status_code == 200
    assert denied_query_method.status_code == 403
    assert allowed_write.status_code == 200
    assert allowed_write.json()["stored"] is False
    assert denied_scope.status_code == 403
    assert denied_origin.status_code == 403


def test_mcp_capability_rejects_missing_wrong_and_expired_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")
    token = _configure_mcp_bridge(monkeypatch, tmp_path)

    with TestClient(app) as client:
        missing = client.get("/api/tasks")
        wrong = client.get(
            "/api/tasks",
            headers={"X-KnowledgeHub-MCP-Token": "wrong-mcp-token-value-1234567890"},
        )
        monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID", "different-session")
        expired = client.get(
            "/api/tasks",
            headers={"X-KnowledgeHub-MCP-Token": token},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert expired.status_code == 403


def test_desktop_server_refuses_to_listen_on_a_network_interface(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_BACKEND_HOST", "0.0.0.0")

    with pytest.raises(SystemExit, match="仅允许监听本机回环地址"):
        backend_host()


def test_desktop_server_accepts_the_explicit_ipv6_loopback_host(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_BACKEND_HOST", "::1")

    assert backend_host() == "::1"
