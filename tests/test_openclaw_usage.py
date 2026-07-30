import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from main import app
from services.openclaw_usage import get_openclaw_usage


def test_openclaw_usage_aggregates_current_session_metadata_without_transcripts(tmp_path):
    main_log = tmp_path / "main.jsonl"
    wechat_log = tmp_path / "wechat.jsonl"
    main_log.write_text(
        '\n'.join([
            json.dumps({"type": "message", "message": {"role": "assistant", "content": "private", "usage": {"input": 10, "output": 2, "cacheRead": 30, "cacheWrite": 0, "totalTokens": 42, "cost": {"total": 0.01}}}}),
            json.dumps({"type": "message", "message": {"role": "user", "content": "also private"}}),
        ]),
        encoding="utf-8",
    )
    wechat_log.write_text(
        json.dumps({"type": "message", "message": {"role": "assistant", "usage": {"input": 4, "output": 1, "cacheRead": 5, "totalTokens": 10, "cost": {"total": 0.02}}}}),
        encoding="utf-8",
    )
    (tmp_path / "sessions.json").write_text(json.dumps({
        "agent:main:main": {"sessionFile": str(main_log), "modelProvider": "deepseek", "model": "deepseek-v4-flash"},
        "agent:main:openclaw-weixin:direct:private-peer": {"sessionFile": str(wechat_log), "modelProvider": "deepseek", "model": "deepseek-v4-flash"},
    }), encoding="utf-8")

    usage = get_openclaw_usage(tmp_path)

    assert usage["available"] is True
    assert usage["session_count"] == 2
    assert usage["model_response_count"] == 2
    assert usage["input_tokens"] == 14
    assert usage["output_tokens"] == 3
    assert usage["cache_read_tokens"] == 35
    assert usage["total_tokens"] == 52
    assert usage["estimated_cost_usd"] == 0.03
    assert usage["sessions"][0]["label"] == "主会话"
    assert usage["sessions"][1]["label"] == "微信"
    assert "private" not in json.dumps(usage, ensure_ascii=False)


def test_openclaw_usage_endpoint_returns_safe_empty_state_when_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr("routers.openclaw.get_openclaw_usage", lambda: get_openclaw_usage(tmp_path))

    response = TestClient(app).get("/api/openclaw/usage")

    assert response.status_code == 200
    assert response.json()["available"] is False
