from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "manage_mcp_bridge_session.py"
SPEC = importlib.util.spec_from_file_location("manage_mcp_bridge_session", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


def test_source_bridge_session_is_private_fresh_and_removable(tmp_path):
    run_dir = tmp_path / "run"
    session = bridge.create_session(run_dir)

    assert run_dir.stat().st_mode & 0o777 == 0o700
    assert (run_dir / "mcp-bridge-token").stat().st_mode & 0o777 == 0o600
    assert (run_dir / "mcp-bridge-lease.json").stat().st_mode & 0o777 == 0o600
    assert bridge.validate_session(run_dir)
    assert session["token"] not in (run_dir / "mcp-bridge-lease.json").read_text()
    assert json.loads((run_dir / "mcp-bridge-lease.json").read_text())["api_base"] == (
        "http://127.0.0.1:8000/api"
    )

    bridge.cleanup_session(run_dir)
    assert not (run_dir / "mcp-bridge-token").exists()
    assert not (run_dir / "mcp-bridge-lease.json").exists()


def test_source_bridge_session_rejects_symlink_and_expired_lease(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    target = tmp_path / "target"
    target.write_text("do-not-touch", encoding="utf-8")
    (run_dir / "mcp-bridge-token").symlink_to(target)

    with pytest.raises(RuntimeError, match="拒绝覆盖不安全"):
        bridge.create_session(run_dir)
    assert target.read_text(encoding="utf-8") == "do-not-touch"

    (run_dir / "mcp-bridge-token").unlink()
    bridge.create_session(run_dir)
    lease_file = run_dir / "mcp-bridge-lease.json"
    lease = json.loads(lease_file.read_text(encoding="utf-8"))
    lease["updated_at"] = 1
    lease_file.write_text(json.dumps(lease), encoding="utf-8")
    lease_file.chmod(0o600)
    assert not bridge.validate_session(run_dir)


def test_stale_heartbeat_cannot_overwrite_a_new_session_lease(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    old_session = bridge.create_session(run_dir)
    new_session = bridge.create_session(run_dir)
    lease_file = run_dir / "mcp-bridge-lease.json"
    monkeypatch.setattr(bridge.time, "sleep", lambda _interval: None)

    bridge.heartbeat(
        lease_file,
        old_session["session_id"],
        "http://127.0.0.1:8000/api",
        0.01,
    )

    payload = json.loads(lease_file.read_text(encoding="utf-8"))
    assert payload["session_id"] == new_session["session_id"]


def test_source_bridge_session_rejects_a_remote_api_endpoint(tmp_path):
    with pytest.raises(RuntimeError, match="本机回环地址"):
        bridge.create_session(tmp_path / "run", "https://attacker.invalid/api")
