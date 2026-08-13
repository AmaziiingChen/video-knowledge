from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from services import openclaw_gateway


def _secure_file(path, content: str) -> None:
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def test_mcp_status_rejects_config_keys_without_a_callable_session(tmp_path, monkeypatch):
    config = tmp_path / "openclaw.json"
    config.write_text(
        json.dumps({"mcp": {"servers": {"knowledgehub": {"command": "/missing"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))

    status = openclaw_gateway._mcp_status()

    assert status == {
        "state": "invalid",
        "configured": False,
        "detail": "KnowledgeHub MCP 配置存在，但命令或 bridge capability 无效",
    }


def _source_mcp_command() -> tuple[str, list[str]]:
    desktop_server = Path(openclaw_gateway.__file__).resolve().parents[1] / "desktop_server.py"
    return sys.executable, [str(desktop_server), "--mcp-stdio"]


def _write_ready_config(tmp_path, monkeypatch, *, command: str, arguments: list[str]):
    token = "mcp-status-token-value-1234567890"
    token_file = tmp_path / "run" / "mcp-bridge-token"
    lease_file = tmp_path / "run" / "mcp-bridge-lease.json"
    _secure_file(token_file, token)
    _secure_file(
        lease_file,
        json.dumps(
            {
                "session_id": "session-1",
                "updated_at": time.time(),
                "api_base": "http://127.0.0.1:8000/api",
            }
        ),
    )
    config = tmp_path / "openclaw.json"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": {
                        "knowledgehub": {
                            "command": command,
                            "args": arguments,
                            "env": {
                                "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE": str(token_file),
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(config))
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN", token)
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID", "session-1")
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE", str(lease_file))


def test_mcp_status_accepts_only_matching_command_file_token_and_fresh_lease(tmp_path, monkeypatch):
    command, arguments = _source_mcp_command()
    _write_ready_config(tmp_path, monkeypatch, command=command, arguments=arguments)
    monkeypatch.setattr(openclaw_gateway, "_mcp_stdio_probe_cached", lambda *_args: True)

    assert openclaw_gateway._mcp_status() == {
        "state": "configured",
        "configured": True,
        "detail": "KnowledgeHub MCP 已通过本机 stdio 握手与 bridge capability 检查",
    }


def test_mcp_status_rejects_another_executable_or_extra_arguments(tmp_path, monkeypatch):
    command, arguments = _source_mcp_command()
    other = tmp_path / "other-executable"
    other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    other.chmod(0o700)
    _write_ready_config(tmp_path, monkeypatch, command=str(other), arguments=arguments)
    assert not openclaw_gateway._mcp_status()["configured"]

    _write_ready_config(
        tmp_path,
        monkeypatch,
        command=command,
        arguments=[*arguments, "--unexpected"],
    )
    assert not openclaw_gateway._mcp_status()["configured"]


def test_mcp_status_accepts_the_frozen_backend_as_the_single_packaged_entry(tmp_path, monkeypatch):
    executable = tmp_path / "knowledgehub-backend"
    executable.write_text("binary", encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setattr(openclaw_gateway.sys, "frozen", True, raising=False)
    monkeypatch.setattr(openclaw_gateway.sys, "executable", str(executable))
    _write_ready_config(
        tmp_path,
        monkeypatch,
        command=str(executable),
        arguments=["--mcp-stdio"],
    )
    monkeypatch.setattr(openclaw_gateway, "_mcp_stdio_probe_cached", lambda *_args: True)

    assert openclaw_gateway._mcp_status()["configured"] is True


def test_mcp_status_requires_the_exact_entry_to_complete_a_stdio_handshake(tmp_path, monkeypatch):
    command, arguments = _source_mcp_command()
    _write_ready_config(tmp_path, monkeypatch, command=command, arguments=arguments)
    monkeypatch.setattr(openclaw_gateway, "_mcp_stdio_probe_cached", lambda *_args: False)

    status = openclaw_gateway._mcp_status()

    assert status["state"] == "invalid"
    assert status["configured"] is False


def test_mcp_status_rejects_unmanaged_child_environment_overrides(tmp_path, monkeypatch):
    command, arguments = _source_mcp_command()
    _write_ready_config(tmp_path, monkeypatch, command=command, arguments=arguments)
    config_path = tmp_path / "openclaw.json"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["mcp"]["servers"]["knowledgehub"]["env"]["PYTHONPATH"] = str(tmp_path)
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(openclaw_gateway, "_mcp_stdio_probe_cached", lambda *_args: True)

    assert openclaw_gateway._mcp_status()["configured"] is False


def test_repair_mcp_replaces_only_the_knowledgehub_cli_entry_and_rechecks_it(tmp_path, monkeypatch):
    command, arguments = _source_mcp_command()
    _write_ready_config(tmp_path, monkeypatch, command=command, arguments=arguments)
    calls: list[tuple[str, ...]] = []

    def run_cli(*args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    ready = {"mcp": {"configured": True, "detail": "KnowledgeHub MCP 已就绪"}}
    monkeypatch.setattr(openclaw_gateway, "_run_openclaw_cli", run_cli)
    monkeypatch.setattr(openclaw_gateway, "get_openclaw_status", lambda **_kwargs: ready)

    assert openclaw_gateway.repair_openclaw_mcp() == ready
    assert calls[0][:3] == ("mcp", "set", "knowledgehub")
    descriptor = json.loads(calls[0][3])
    assert descriptor == {
        "command": str(Path(sys.executable).resolve()),
        "args": arguments,
        "env": {
            "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE": str(tmp_path / "run" / "mcp-bridge-token"),
            "KNOWLEDGEHUB_API_BASE": "http://127.0.0.1:8000/api",
        },
    }
    assert calls[1] == ("mcp", "reload")


def test_repair_mcp_refuses_to_write_when_the_desktop_bridge_is_not_ready(tmp_path, monkeypatch):
    command, arguments = _source_mcp_command()
    _write_ready_config(tmp_path, monkeypatch, command=command, arguments=arguments)
    monkeypatch.delenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN", raising=False)
    monkeypatch.setattr(openclaw_gateway, "_run_openclaw_cli", lambda *_args, **_kwargs: pytest.fail("must not write config"))

    with pytest.raises(openclaw_gateway.OpenClawGatewayError, match="bridge 尚未就绪"):
        openclaw_gateway.repair_openclaw_mcp()


def test_stdio_probe_rejects_a_nonzero_process_even_with_valid_responses(monkeypatch):
    stdout = "\n".join(
        (
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "tool"}]}}),
        )
    )
    monkeypatch.setattr(
        openclaw_gateway.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 1, stdout, "failed"),
    )

    assert not openclaw_gateway._probe_mcp_stdio(
        sys.executable,
        [str(Path(openclaw_gateway.__file__).resolve().parents[1] / "desktop_server.py"), "--mcp-stdio"],
        {},
    )
