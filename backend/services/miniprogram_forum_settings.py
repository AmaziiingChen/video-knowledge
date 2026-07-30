from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from config import settings
from services.macos_miniprogram import DEFAULT_WINDOW_PATTERN
from services.miniprogram_forum_collector import miniprogram_forum_collector


DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "interval_minutes": 360,
    "idle_seconds_required": 120,
    "source_key": "campus_forum",
    "window_pattern": DEFAULT_WINDOW_PATTERN,
    "max_posts": 300,
    "max_feed_scrolls": 500,
    "max_detail_scrolls": 120,
    "known_post_stop": 20,
    "page_wait_seconds": 1.2,
    "last_attempt_at": "",
    "last_status": "",
    "last_message": "",
}
ALLOWED_INTERVALS = {30, 60, 180, 360, 720, 1440}
_settings_lock = Lock()


def settings_path() -> Path:
    return settings.data_dir / "miniprogram_forum_settings.json"


def load_miniprogram_forum_settings() -> dict[str, Any]:
    with _settings_lock:
        return _read_unlocked()


def update_miniprogram_forum_settings(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "enabled", "interval_minutes", "idle_seconds_required", "window_pattern",
        "max_posts", "max_feed_scrolls", "max_detail_scrolls", "known_post_stop",
        "page_wait_seconds",
    }
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"不支持的小程序采集设置：{', '.join(sorted(unknown))}")
    with _settings_lock:
        current = _read_unlocked()
        current.update(values)
        current = _validated(current)
        _write_unlocked(current)
        return current


def record_scheduler_attempt(*, status: str, message: str) -> dict[str, Any]:
    with _settings_lock:
        current = _read_unlocked()
        current.update(
            {
                "last_attempt_at": datetime.now(timezone.utc).isoformat(),
                "last_status": status,
                "last_message": str(message or "")[:300],
            }
        )
        _write_unlocked(current)
        return current


class MiniProgramForumScheduler:
    def __init__(self) -> None:
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if not settings.miniprogram_forum_capture_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="miniprogram-forum-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def run_once(self) -> bool:
        if not settings.miniprogram_forum_capture_enabled:
            return False
        config = load_miniprogram_forum_settings()
        if not config["enabled"] or miniprogram_forum_collector.is_active() or not _is_due(config):
            return False
        try:
            environment = miniprogram_forum_collector.permission_status(
                str(config["window_pattern"]), prompt=False
            )
            if not environment.get("selected_window"):
                record_scheduler_attempt(status="waiting", message="等待微信小程序窗口")
                return False
            if not environment.get("accessibility_granted") or not environment.get("screen_capture_granted"):
                record_scheduler_attempt(status="waiting", message="等待系统采集权限")
                return False
            idle_seconds = float(environment.get("user_idle_seconds") or 0)
            if idle_seconds < int(config["idle_seconds_required"]):
                return False
            miniprogram_forum_collector.start(
                {
                    **config,
                    "mode": "incremental",
                    "prompt_permissions": False,
                }
            )
            record_scheduler_attempt(status="started", message="空闲时自动增量采集已启动")
            return True
        except Exception as exc:
            record_scheduler_attempt(status="error", message=str(exc))
            return False

    def _loop(self) -> None:
        while not self._stop.wait(30):
            self.run_once()


def _is_due(config: dict[str, Any]) -> bool:
    value = str(config.get("last_attempt_at") or "")
    if not value:
        return True
    try:
        previous = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - previous.astimezone(timezone.utc)
    return elapsed.total_seconds() >= int(config["interval_minutes"]) * 60


def _read_unlocked() -> dict[str, Any]:
    path = settings_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    return _validated({**DEFAULTS, **(value if isinstance(value, dict) else {})})


def _write_unlocked(value: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validated(value: dict[str, Any]) -> dict[str, Any]:
    interval = int(value.get("interval_minutes") or 360)
    if interval not in ALLOWED_INTERVALS:
        raise ValueError("不支持的自动采集频率")
    window_pattern = str(value.get("window_pattern") or DEFAULT_WINDOW_PATTERN).strip()
    if window_pattern == "微信|WeChat":
        window_pattern = DEFAULT_WINDOW_PATTERN
    return {
        **DEFAULTS,
        **value,
        "enabled": bool(value.get("enabled")),
        "interval_minutes": interval,
        "window_pattern": window_pattern,
        "idle_seconds_required": max(30, min(int(value.get("idle_seconds_required") or 120), 3600)),
        "max_posts": max(1, min(int(value.get("max_posts") or 300), 5000)),
        "max_feed_scrolls": max(1, min(int(value.get("max_feed_scrolls") or 500), 5000)),
        "max_detail_scrolls": max(1, min(int(value.get("max_detail_scrolls") or 120), 1000)),
        "known_post_stop": max(1, min(int(value.get("known_post_stop") or 20), 200)),
        "page_wait_seconds": max(0.4, min(float(value.get("page_wait_seconds") or 1.2), 8.0)),
    }


miniprogram_forum_scheduler = MiniProgramForumScheduler()


__all__ = [
    "ALLOWED_INTERVALS",
    "MiniProgramForumScheduler",
    "load_miniprogram_forum_settings",
    "miniprogram_forum_scheduler",
    "record_scheduler_attempt",
    "update_miniprogram_forum_settings",
]
