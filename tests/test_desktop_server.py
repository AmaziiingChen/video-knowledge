from __future__ import annotations

import desktop_server


def test_desktop_entrypoint_handles_frozen_multiprocessing_before_uvicorn(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(desktop_server.mp, "freeze_support", lambda: calls.append("freeze"))
    monkeypatch.setattr(desktop_server, "run_api", lambda: calls.append("uvicorn"))

    desktop_server.main([])

    assert calls == ["freeze", "uvicorn"]


def test_desktop_entrypoint_runs_only_the_stdio_bridge_in_mcp_mode(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(desktop_server.mp, "freeze_support", lambda: calls.append("freeze"))
    monkeypatch.setattr(desktop_server, "run_api", lambda: calls.append("uvicorn"))
    monkeypatch.setattr(desktop_server, "run_mcp_stdio", lambda: calls.append("mcp"))

    desktop_server.main(["--mcp-stdio"])

    assert calls == ["freeze", "mcp"]
