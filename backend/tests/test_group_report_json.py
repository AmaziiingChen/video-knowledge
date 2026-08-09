from __future__ import annotations

import json

from config import settings
from services.group_report_json import (
    decode_json_payload,
    is_json_payload,
    parse_json,
    save_failed_json_output,
    save_planner_trace,
)


def test_json_recovery_accepts_only_unescaped_controls_in_json_strings():
    recovered, valid, recovered_control = decode_json_payload(
        '{"brief":"第一行\n第二行"}'
    )

    assert recovered == {"brief": "第一行\n第二行"}
    assert valid is True
    assert recovered_control is True
    assert parse_json('{"brief":"ok"}') == {"brief": "ok"}
    assert is_json_payload('{"brief":"ok"}') is True
    assert parse_json('{"brief":"ok" "missing":true}') == {}
    assert is_json_payload('{"brief":"ok" "missing":true}') is False


def test_json_diagnostics_are_local_private_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    invalid_path = save_failed_json_output("栏目/规划", "not json")
    trace_path = save_planner_trace(
        "栏目/规划",
        {"reasoning_content": "reasoning", "content": '{"ok":true}'},
    )

    assert invalid_path.parent == tmp_path / "diagnostics" / "group-report-plans"
    assert invalid_path.read_text(encoding="utf-8") == "not json"
    assert invalid_path.stat().st_mode & 0o777 == 0o600
    assert trace_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(trace_path.read_text(encoding="utf-8"))["content"] == '{"ok":true}'
