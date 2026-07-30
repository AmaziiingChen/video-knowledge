"""Persistent, non-secret configuration for the optional import inbox."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import settings


_FILE_NAME = "folder_import_watcher_settings.json"
_DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "folder_path": "",
    "poll_interval": 15.0,
}


def load_folder_import_watcher_settings() -> dict[str, Any]:
    try:
        raw = json.loads((settings.data_dir / _FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    values = dict(_DEFAULTS)
    if isinstance(raw, dict):
        values.update({key: raw[key] for key in _DEFAULTS if key in raw})
    values["enabled"] = bool(values["enabled"])
    values["folder_path"] = _normalize_folder_path(values["folder_path"])
    values["poll_interval"] = _poll_interval(values["poll_interval"])
    if not values["folder_path"]:
        values["enabled"] = False
    return values


def save_folder_import_watcher_settings(updates: dict[str, Any]) -> dict[str, Any]:
    values = load_folder_import_watcher_settings()
    values.update({key: value for key, value in updates.items() if key in _DEFAULTS})
    values["enabled"] = bool(values["enabled"])
    values["folder_path"] = _normalize_folder_path(values["folder_path"])
    values["poll_interval"] = _poll_interval(values["poll_interval"])
    if values["enabled"] and not values["folder_path"]:
        raise ValueError("请选择一个可访问的本地收件箱文件夹")
    path = settings.data_dir / _FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return values


def _normalize_folder_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        path = Path(text).expanduser().resolve()
        if not path.is_dir() or path == settings.data_dir.resolve():
            return ""
        return str(path)
    except OSError:
        return ""


def _poll_interval(value: Any) -> float:
    try:
        return max(10.0, min(float(value), 600.0))
    except (TypeError, ValueError):
        return 15.0
