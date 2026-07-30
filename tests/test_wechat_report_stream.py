from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.wechat_reports as report_router


def test_report_stream_forwards_progress_and_completion(monkeypatch):
    def fake_generate(group_id, report_type, *, progress_callback=None, **_kwargs):
        assert group_id == "campus"
        assert report_type == "weekly"
        progress_callback({
            "stage": "report_facts",
            "message": "事实卡已完成 2/2",
            "progress": 36,
            "level": "info",
        })
        return {"source_count": 2, "generation_mode": "campus_clustered"}

    monkeypatch.setattr(report_router, "generate_report", fake_generate)
    blocks = list(report_router._report_event_stream("campus", "weekly"))
    events = [json.loads(block.removeprefix("data: ").strip()) for block in blocks]

    assert events[0]["event"] == "progress"
    assert events[0]["stage"] == "report_facts"
    assert events[-1]["event"] == "complete"
    assert events[-1]["result"]["source_count"] == 2


def test_report_stream_surfaces_generation_error(monkeypatch):
    def fake_generate(*_args, **_kwargs):
        raise ValueError("有 1 篇文章未能完成校园事实提取")

    monkeypatch.setattr(report_router, "generate_report", fake_generate)
    blocks = list(report_router._report_event_stream("campus", "weekly"))
    event = json.loads(blocks[0].removeprefix("data: ").strip())

    assert event == {
        "event": "error",
        "message": "有 1 篇文章未能完成校园事实提取",
    }


def test_custom_range_is_forwarded_without_history_context(monkeypatch):
    start = datetime(2026, 7, 16, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    end = datetime(2026, 7, 18, 11, 30, tzinfo=timezone(timedelta(hours=8)))

    def fake_generate(group_id, report_type, **kwargs):
        assert group_id == "campus"
        assert report_type == "range"
        assert kwargs["window_start"] == start
        assert kwargs["window_end"] == end
        assert kwargs["include_history_context"] is False
        return {"source_count": 3}

    monkeypatch.setattr(report_router, "generate_report", fake_generate)
    blocks = list(report_router._report_event_stream(
        "campus",
        "range",
        window_start=start,
        window_end=end,
        include_history_context=False,
    ))
    event = json.loads(blocks[0].removeprefix("data: ").strip())

    assert event["event"] == "complete"
    assert event["result"]["source_count"] == 3


def test_custom_report_range_requires_both_timezone_aware_ordered_bounds():
    start = datetime(2026, 7, 16, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    with pytest.raises(ValidationError, match="必须提供开始时间和结束时间"):
        report_router.ReportRequest(report_type="range")

    with pytest.raises(ValidationError, match="必须同时提供"):
        report_router.ReportRequest(report_type="range", window_start=start)

    with pytest.raises(ValidationError, match="结束时间必须晚于开始时间"):
        report_router.ReportRequest(
            report_type="range",
            window_start=start,
            window_end=start,
        )

    with pytest.raises(ValidationError, match="必须包含时区"):
        report_router.ReportRequest(
            report_type="range",
            window_start=start.replace(tzinfo=None),
            window_end=(start + timedelta(hours=1)).replace(tzinfo=None),
        )

    request = report_router.ReportRequest(
        report_type="range",
        window_start=start,
        window_end=start + timedelta(days=2),
    )
    assert request.window_end.date().isoformat() == "2026-07-18"
