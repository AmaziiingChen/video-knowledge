from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = _load("macos_desktop_runtime")
smoke = _load("smoke_macos_desktop")
idle = _load("measure_macos_idle")


def test_port_probe_allows_restart_reuse_but_rejects_an_active_listener(monkeypatch):
    calls: list[tuple[object, ...]] = []

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def setsockopt(self, *args):
            calls.append(("setsockopt", *args))

        def bind(self, address):
            calls.append(("bind", address))
            raise OSError("address already in use")

    monkeypatch.setattr(runtime.socket, "socket", Socket)

    with pytest.raises(RuntimeError, match="端口 8000 已被占用"):
        runtime.require_port_available(8000)
    assert calls == [
        ("setsockopt", runtime.socket.SOL_SOCKET, runtime.socket.SO_REUSEADDR, 1),
        ("bind", ("127.0.0.1", 8000)),
    ]


def test_desktop_smoke_uses_the_renderer_auth_path_without_exposing_a_capability():
    expression = smoke.renderer_expression("return true")
    restart_source = Path(smoke.__file__).read_text(encoding="utf-8")

    assert "http://127.0.0.1:8000/api/health" in expression
    assert "window.knowledgeHubDesktop" not in expression
    assert "X-KnowledgeHub-Token" not in expression
    assert 'button[aria-label="搜索资料"]' in restart_source
    assert 'input[aria-label="搜索资料库内容"]' in restart_source
    assert runtime.redact({"token": "private-value"}, "private-value") == {"token": "[redacted]"}


def test_desktop_smoke_import_then_restart_and_open(monkeypatch, tmp_path):
    class Process:
        pid = 123
        def poll(self): return None

    class Client:
        def close(self): pass

    launches: list[object] = []
    monkeypatch.setattr(smoke, "app_executable", lambda _app: tmp_path / "KnowledgeHub")
    monkeypatch.setattr(smoke, "require_port_available", lambda _port: None)
    monkeypatch.setattr(smoke, "wait_for_port_available", lambda _port: None)
    monkeypatch.setattr(smoke, "free_loopback_port", lambda: 9229)
    monkeypatch.setattr(smoke, "launch_app", lambda *_args: launches.append(Process()) or launches[-1])
    monkeypatch.setattr(smoke, "open_renderer", lambda *_args: Client())
    monkeypatch.setattr(smoke, "import_fixture", lambda _client: {"id": "fixture-1", "title": smoke.FIXTURE_TITLE})
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(smoke, "verify_persisted_and_open", lambda _client, item: seen.append(item))
    monkeypatch.setattr(smoke, "close_desktop_app", lambda _client, _process: True)
    monkeypatch.setattr(smoke, "terminate", lambda _process: True)

    report = smoke.run_smoke(tmp_path)

    assert len(launches) == 2
    assert seen == [{"id": "fixture-1", "title": smoke.FIXTURE_TITLE}]
    assert report["restart_persistence"] == "ok"
    assert report["first_shutdown"] == "graceful"


def test_idle_process_tree_and_aggregation():
    rows = [
        {"pid": 10, "ppid": 1, "cpu_percent": 1.0, "rss_bytes": 100, "threads": 2, "command": "KnowledgeHub"},
        {"pid": 11, "ppid": 10, "cpu_percent": 2.0, "rss_bytes": 200, "threads": 3, "command": "Helper"},
        {"pid": 12, "ppid": 99, "cpu_percent": 99.0, "rss_bytes": 999, "threads": 9, "command": "other"},
    ]
    assert [row["pid"] for row in idle.descendant_rows(10, rows)] == [10, 11]

    summary = idle.aggregate([
        {"cpu_percent": 2, "rss_bytes": 300, "threads": 5, "disk_read_delta_bytes": 10, "disk_write_delta_bytes": 20},
        {"cpu_percent": 4, "rss_bytes": 500, "threads": 7, "disk_read_delta_bytes": 30, "disk_write_delta_bytes": 40},
    ], 5)
    assert summary["cpu_percent"] == {"average": 3.0, "peak": 4.0}
    assert summary["rss_bytes"] == {"average": 400, "peak": 500.0}
    assert summary["disk_read_bytes_per_second"] == {"average": 4.0, "peak": 6.0}


def test_idle_rejects_invalid_sampling_parameters(tmp_path):
    with pytest.raises(ValueError, match="必须有效"):
        idle.run_measurement(tmp_path, warmup_seconds=0, sample_seconds=0, interval_seconds=5)
