from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from services import openclaw_gateway

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPT_PATH = ROOT / "scripts" / "smoke_macos_mcp.py"
SPEC = importlib.util.spec_from_file_location("smoke_macos_mcp", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_source_stdio_bridge_enforces_the_real_backend_capability_boundary():
    report = smoke.run_smoke(
        command=sys.executable,
        prefix_args=[str(ROOT / "backend" / "desktop_server.py")],
        cwd=ROOT / "backend",
    )

    assert report["status"] == "ok"
    assert report["transport"] == "stdio"
    assert report["tool_count"] >= 21
    assert report["valid_capability"] == "accepted"
    assert report["missing_capability"] == "rejected"
    assert report["wrong_capability"] == "rejected"


def test_runtime_status_probe_initializes_the_exact_source_stdio_entry(tmp_path):
    assert openclaw_gateway._probe_mcp_stdio(
        sys.executable,
        [str(ROOT / "backend" / "desktop_server.py"), "--mcp-stdio"],
        {"KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE": str(tmp_path / "missing-token")},
    )
