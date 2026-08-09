from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock


_CAPTURE_STATE_LOCK = Lock()
_CAPTURE_STATE = {
    "active": False,
    "provider": "",
    "stage": "空闲",
    "waiting_count": 0,
    "last_list_checks": {"douyin": {}, "bilibili": {}, "xiaohongshu": {}},
}


def creator_capture_status() -> dict:
    with _CAPTURE_STATE_LOCK:
        status = dict(_CAPTURE_STATE)
        status["last_list_checks"] = {
            provider: dict(value) for provider, value in _CAPTURE_STATE["last_list_checks"].items()
        }
        return status


def wait_for_creator_browser(provider: str) -> None:
    with _CAPTURE_STATE_LOCK:
        _CAPTURE_STATE["waiting_count"] += 1
        if not _CAPTURE_STATE["active"]:
            _CAPTURE_STATE["provider"] = provider
            _CAPTURE_STATE["stage"] = "等待内置浏览器"


def begin_creator_browser_capture(provider: str) -> None:
    with _CAPTURE_STATE_LOCK:
        _CAPTURE_STATE["waiting_count"] = max(0, int(_CAPTURE_STATE["waiting_count"]) - 1)
        _CAPTURE_STATE["active"] = True
        _CAPTURE_STATE["provider"] = provider
        _CAPTURE_STATE["stage"] = "准备采集"


def set_creator_capture_stage(stage: str) -> None:
    with _CAPTURE_STATE_LOCK:
        if _CAPTURE_STATE["active"]:
            _CAPTURE_STATE["stage"] = stage


def finish_creator_browser_capture() -> None:
    with _CAPTURE_STATE_LOCK:
        _CAPTURE_STATE["active"] = False
        _CAPTURE_STATE["provider"] = ""
        _CAPTURE_STATE["stage"] = "等待内置浏览器" if _CAPTURE_STATE["waiting_count"] else "空闲"


def record_creator_list_check(provider: str, *, state: str, detail: str) -> None:
    if provider not in {"douyin", "bilibili"}:
        return
    with _CAPTURE_STATE_LOCK:
        _CAPTURE_STATE["last_list_checks"][provider] = {
            "state": state,
            "detail": str(detail)[:300],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
