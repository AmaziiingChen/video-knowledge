"""Smoke-test the packaged MCP stdio entry against an isolated local backend."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import anyio
from manage_mcp_bridge_session import (
    atomic_write,
    cleanup_session,
    create_session,
    lease_content,
)
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def backend_in_app(app: Path) -> Path:
    executable = (
        app.expanduser().resolve()
        / "Contents"
        / "Resources"
        / "backend"
        / "knowledgehub-backend"
        / "knowledgehub-backend"
    )
    if not executable.is_file():
        raise RuntimeError("KnowledgeHub.app 缺少打包后的 MCP/backend 可执行文件")
    return executable


def free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_backend(port: int, instance_token: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"隔离后端提前退出：{output[-2000:]}")
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/health",
                headers={"X-KnowledgeHub-Token": instance_token},
            )
            with urllib.request.urlopen(request, timeout=1) as response:
                payload = json.loads(response.read())
            if payload.get("instance_token") == instance_token:
                return
        except (OSError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.25)
    raise RuntimeError("隔离后端 60 秒内未就绪")


async def call_list_tasks(
    *,
    command: str,
    prefix_args: list[str],
    cwd: Path,
    environment: dict[str, str],
) -> tuple[bool, int, str]:
    parameters = StdioServerParameters(
        command=command,
        args=[*prefix_args, "--mcp-stdio"],
        env=environment,
        cwd=cwd,
    )
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
        async with (
            stdio_client(parameters, errlog=errors) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool(
                "knowledgehub_list_tasks",
                {"params": {"limit": 1, "response_format": "json"}},
            )
        errors.seek(0)
        diagnostics = f"{errors.read()}\nresult={result.content!r}"
        return not bool(result.isError), len(tools.tools), diagnostics


def _mcp_case(
    *,
    command: str,
    prefix_args: list[str],
    cwd: Path,
    token_file: Path,
) -> tuple[bool, int, str]:
    async def run_case() -> tuple[bool, int, str]:
        return await call_list_tasks(
            command=command,
            prefix_args=prefix_args,
            cwd=cwd,
            environment={
                "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE": str(token_file),
            },
        )

    return anyio.run(run_case)


def run_smoke(
    *,
    command: str,
    prefix_args: list[str],
    cwd: Path,
) -> dict[str, Any]:
    port = free_loopback_port()
    instance_token = "release-smoke-instance-token"
    wrong_token = "release-smoke-wrong-mcp-token-value"
    with tempfile.TemporaryDirectory(prefix="knowledgehub-mcp-smoke-") as temporary:
        root = Path(temporary)
        api_base = f"http://127.0.0.1:{port}/api"
        session = create_session(root / "run", api_base)
        wrong_file = root / "run" / "wrong-token"
        missing_file = root / "run" / "missing-token"
        atomic_write(wrong_file, f"{wrong_token}\n")
        stop_heartbeat = threading.Event()

        def heartbeat() -> None:
            while not stop_heartbeat.wait(5):
                atomic_write(
                    Path(session["lease_file"]),
                    lease_content(session["session_id"], api_base),
                )

        heartbeat_thread = threading.Thread(target=heartbeat, name="mcp-smoke-lease", daemon=True)
        heartbeat_thread.start()
        environment = os.environ.copy()
        environment.update(
            {
                "DATA_DIR": str(root / "data"),
                "KNOWLEDGEHUB_ENV_FILE": str(root / "settings.env"),
                "KNOWLEDGEHUB_BACKEND_HOST": "127.0.0.1",
                "KNOWLEDGEHUB_BACKEND_PORT": str(port),
                "KNOWLEDGEHUB_INSTANCE_TOKEN": instance_token,
                "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN": session["token"],
                "KNOWLEDGEHUB_MCP_BRIDGE_SESSION_ID": session["session_id"],
                "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE": session["token_file"],
                "KNOWLEDGEHUB_MCP_BRIDGE_LEASE_FILE": session["lease_file"],
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
            }
        )
        backend = subprocess.Popen(
            [command, *prefix_args],
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        backend_output = ""
        try:
            wait_for_backend(port, instance_token, backend)
            valid, tool_count, valid_errors = _mcp_case(
                command=command,
                prefix_args=prefix_args,
                cwd=cwd,
                token_file=Path(session["token_file"]),
            )
            missing, _, missing_errors = _mcp_case(
                command=command,
                prefix_args=prefix_args,
                cwd=cwd,
                token_file=missing_file,
            )
            wrong, _, wrong_errors = _mcp_case(
                command=command,
                prefix_args=prefix_args,
                cwd=cwd,
                token_file=wrong_file,
            )
            if not valid or missing or wrong:
                safe_diagnostics = valid_errors.replace(session["token"], "[redacted]")
                safe_diagnostics = safe_diagnostics.replace(wrong_token, "[redacted]")
                raise RuntimeError(
                    "MCP capability smoke 结果异常："
                    f"valid={valid}, missing={missing}, wrong={wrong}, tools={tool_count}；"
                    "有效 capability 必须成功，缺失和错误 capability 必须失败。"
                    f"有效请求诊断：{safe_diagnostics[-1200:]}"
                )
            combined_errors = valid_errors + missing_errors + wrong_errors
            if session["token"] in combined_errors or wrong_token in combined_errors:
                raise RuntimeError("MCP stdio 日志泄露了 capability")
            report = {
                "status": "ok",
                "transport": "stdio",
                "tool_count": tool_count,
                "valid_capability": "accepted",
                "missing_capability": "rejected",
                "wrong_capability": "rejected",
                "fixture": "isolated-empty-task-list",
            }
            serialized = json.dumps(report, ensure_ascii=False)
            if session["token"] in serialized or wrong_token in serialized:
                raise RuntimeError("MCP smoke 报告泄露了 capability")
            return report
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=2)
            if backend.poll() is None:
                backend.terminate()
                try:
                    backend.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    backend.kill()
                    backend.wait(timeout=5)
            if backend.stdout:
                backend_output = backend.stdout.read()
            cleanup_session(root / "run")
            if session["token"] in backend_output or wrong_token in backend_output:
                raise RuntimeError("隔离后端日志泄露了 MCP capability")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    executable = backend_in_app(arguments.app)
    report = run_smoke(command=str(executable), prefix_args=[], cwd=executable.parent)
    destination = arguments.report.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
