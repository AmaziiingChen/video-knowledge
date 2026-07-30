"""Persistent local preferences for optional video preview downloads."""

from __future__ import annotations

import json
from pathlib import Path

from config import settings


def _path() -> Path:
    return settings.data_dir / "video_download_settings.json"


DOUYIN_QUALITY_OPTIONS = {"low", "standard", "high"}


def _normalize_douyin_quality(value: object) -> str:
    return value if isinstance(value, str) and value in DOUYIN_QUALITY_OPTIONS else "standard"


def load_video_download_settings() -> dict[str, bool | str]:
    default: dict[str, bool | str] = {
        "auto_download_bilibili_video": bool(settings.auto_download_bilibili_video),
        # The previous implementation silently selected the lowest bitrate.
        # Keep storage reasonable by default, but do not permanently hard-code
        # a quality decision into the downloader.
        "douyin_video_quality": "standard",
    }
    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(saved, dict):
        return default
    return {
        "auto_download_bilibili_video": bool(saved.get("auto_download_bilibili_video", default["auto_download_bilibili_video"])),
        "douyin_video_quality": _normalize_douyin_quality(saved.get("douyin_video_quality")),
    }


def save_video_download_settings(
    *,
    auto_download_bilibili_video: bool,
    douyin_video_quality: str = "standard",
) -> dict[str, bool | str]:
    payload: dict[str, bool | str] = {
        "auto_download_bilibili_video": bool(auto_download_bilibili_video),
        "douyin_video_quality": _normalize_douyin_quality(douyin_video_quality),
    }
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return payload


def should_auto_download_bilibili_video() -> bool:
    return load_video_download_settings()["auto_download_bilibili_video"]


def douyin_video_quality() -> str:
    return str(load_video_download_settings()["douyin_video_quality"])
