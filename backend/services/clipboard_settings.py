"""Persistent, non-secret settings for the local clipboard watcher."""
from __future__ import annotations

import json
from typing import Any

from config import settings


_FILE_NAME = "clipboard_watcher_settings.json"
_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "whisper_model": None,
    "asr_backend": None,
    "asr_model_strategy": None,
    "asr_short_video_model": None,
    "asr_long_video_model": None,
    "asr_beam_size": None,
    "asr_vad_filter": None,
    "asr_fallback_enabled": None,
    "ai_model": None,
    "use_cache": True,
    "poll_interval": 2.5,
    "capture_mode": "task",
}


def load_clipboard_watcher_settings() -> dict[str, Any]:
    try:
        raw = json.loads((settings.data_dir / _FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    raw = raw if isinstance(raw, dict) else {}
    values = dict(_DEFAULTS)
    values.update({key: raw[key] for key in _DEFAULTS if key in raw})
    values["enabled"] = bool(values["enabled"])
    values["use_cache"] = bool(values["use_cache"])
    values["poll_interval"] = _poll_interval(values["poll_interval"])
    values["capture_mode"] = values["capture_mode"] if values["capture_mode"] in {"inbox", "task"} else "task"
    return values


def save_clipboard_watcher_settings(updates: dict[str, Any]) -> dict[str, Any]:
    values = load_clipboard_watcher_settings()
    values.update({key: value for key, value in updates.items() if key in _DEFAULTS})
    values["enabled"] = bool(values["enabled"])
    values["use_cache"] = bool(values["use_cache"])
    values["poll_interval"] = _poll_interval(values["poll_interval"])
    values["capture_mode"] = values["capture_mode"] if values["capture_mode"] in {"inbox", "task"} else "task"
    path = settings.data_dir / _FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return values


def _poll_interval(value: Any) -> float:
    try:
        return max(1.0, min(float(value), 10.0))
    except (TypeError, ValueError):
        return 2.5
