from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from config import settings


SETTINGS_FILE = "media_tools.json"
TOOL_KEYS = {"ffmpeg": "ffmpeg_path", "yt-dlp": "yt_dlp_path"}


def _settings_path() -> Path:
    return settings.data_dir / SETTINGS_FILE


def _saved() -> dict[str, str]:
    try:
        value = json.loads(_settings_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_tool(name: str) -> str | None:
    key = TOOL_KEYS[name]
    configured = str(_saved().get(key) or getattr(settings, key, "") or "").strip()
    if configured and _is_executable(configured):
        return configured
    return shutil.which(name)


def media_tool_status() -> dict:
    saved = _saved()
    result = {}
    for name, key in TOOL_KEYS.items():
        configured = str(saved.get(key) or getattr(settings, key, "") or "").strip()
        resolved = resolve_tool(name)
        result[key] = {"configured_path": configured, "resolved_path": resolved or "", "available": bool(resolved)}
    return result


def save_media_tools(*, ffmpeg_path: str, yt_dlp_path: str) -> dict:
    values = {"ffmpeg_path": ffmpeg_path.strip(), "yt_dlp_path": yt_dlp_path.strip()}
    for value in values.values():
        if value and not _is_executable(value):
            raise ValueError(f"工具路径不可执行：{value}")
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    return media_tool_status()


def _is_executable(value: str) -> bool:
    path = Path(value).expanduser()
    return path.is_file() and os.access(path, os.X_OK)
