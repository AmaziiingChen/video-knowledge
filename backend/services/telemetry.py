"""Minimal, opt-in, privacy-preserving local telemetry queue."""

from __future__ import annotations

import json
import platform
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Timer
from typing import Any

from config import settings


EVENT_FIELDS: dict[str, frozenset[str]] = {
    "app_started": frozenset(),
    "workspace_opened": frozenset({"view"}),
    "import_started": frozenset({"input_kind"}),
    "import_completed": frozenset({"result"}),
    "task_enqueued": frozenset({"processing_mode"}),
    "pipeline_stage_completed": frozenset({"stage"}),
    "pipeline_stage_failed": frozenset({"stage"}),
    "task_finished": frozenset({"result", "stage"}),
    "task_control_used": frozenset({"action"}),
    "paddle_ocr_completed": frozenset({"result"}),
    "obsidian_sync_completed": frozenset({"result"}),
    "search_completed": frozenset({"result_count_bucket"}),
    "clipboard_listener_changed": frozenset({"state"}),
    "update_check_completed": frozenset({"result"}),
    "telemetry_consent_changed": frozenset({"state"}),
    "update_download_page_opened": frozenset(),
    "media_download_completed": frozenset({"result", "duration_bucket"}),
    "asr_completed": frozenset({"backend", "result", "duration_bucket"}),
    "ai_summary_completed": frozenset({"result", "duration_bucket"}),
    "export_completed": frozenset({"export_kind", "result"}),
}

_lock = Lock()
_pending_events: list[tuple[str, str, str, str]] = []
_flush_timer: Timer | None = None
_enabled_cache: bool | None = None
FLUSH_INTERVAL_SECONDS = 2.0
FLUSH_BATCH_SIZE = 20


def _path() -> Path:
    return settings.data_dir / "telemetry.sqlite"


def _connect() -> sqlite3.Connection:
    database_path = _path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 1000")
    connection.execute("CREATE TABLE IF NOT EXISTS telemetry_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS telemetry_events (id TEXT PRIMARY KEY, event_name TEXT NOT NULL, occurred_at TEXT NOT NULL, properties TEXT NOT NULL)"
    )
    return connection


def _setting(connection: sqlite3.Connection, key: str, default: str = "") -> str:
    row = connection.execute("SELECT value FROM telemetry_settings WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flush_locked() -> None:
    global _flush_timer
    _flush_timer = None
    if not _pending_events or not _path().exists():
        return
    try:
        with _connect() as connection:
            if _setting(connection, "enabled") != "true":
                _pending_events.clear()
                return
            connection.executemany(
                "INSERT INTO telemetry_events(id, event_name, occurred_at, properties) VALUES (?, ?, ?, ?)",
                _pending_events,
            )
            _pending_events.clear()
    except sqlite3.Error:
        # Telemetry must never delay processing; retain the bounded batch for a
        # later flush and drop excess only if local storage stays unavailable.
        del _pending_events[:-FLUSH_BATCH_SIZE]


def flush() -> None:
    with _lock:
        _flush_locked()


def _schedule_flush_locked() -> None:
    global _flush_timer
    if _flush_timer is None:
        _flush_timer = Timer(FLUSH_INTERVAL_SECONDS, flush)
        _flush_timer.daemon = True
        _flush_timer.start()


def status() -> dict[str, object]:
    flush()
    if not _path().exists():
        return {"enabled": False, "pending_events": 0, "event_catalog_size": len(EVENT_FIELDS)}
    with _lock, _connect() as connection:
        enabled = _setting(connection, "enabled") == "true"
        pending = int(connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]) if enabled else 0
        return {"enabled": enabled, "pending_events": pending, "event_catalog_size": len(EVENT_FIELDS)}


def set_enabled(enabled: bool) -> dict[str, object]:
    global _enabled_cache, _flush_timer
    database_path = _path()
    with _lock:
        if enabled:
            with _connect() as connection:
                connection.execute("INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('enabled', 'true')")
                if not _setting(connection, "installation_id"):
                    connection.execute(
                        "INSERT INTO telemetry_settings(key, value) VALUES ('installation_id', ?)", (str(uuid.uuid4()),)
                    )
                connection.execute(
                    "INSERT INTO telemetry_events(id, event_name, occurred_at, properties) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), "telemetry_consent_changed", _now(), '{"state":"enabled"}'),
                )
            _enabled_cache = True
        elif database_path.exists():
            _pending_events.clear()
            if _flush_timer is not None:
                _flush_timer.cancel()
                _flush_timer = None
            database_path.unlink()
        if not enabled:
            _enabled_cache = False
    return status()


def record(event_name: str, properties: dict[str, Any] | None = None) -> bool:
    global _enabled_cache
    allowed = EVENT_FIELDS.get(event_name)
    if allowed is None:
        raise ValueError("未知遥测事件")
    payload = properties or {}
    if set(payload) - allowed:
        raise ValueError("遥测事件包含未允许字段")
    # Only short fixed values are accepted; free text, URLs, paths and content
    # cannot enter this queue through this API.
    if any(not isinstance(value, str) or len(value) > 40 for value in payload.values()):
        raise ValueError("遥测属性必须是短枚举值")
    if not _path().exists():
        return False
    with _lock:
        if _enabled_cache is None:
            try:
                with _connect() as connection:
                    _enabled_cache = _setting(connection, "enabled") == "true"
            except sqlite3.Error:
                return False
        if not _enabled_cache:
            return False
        _pending_events.append((str(uuid.uuid4()), event_name, _now(), json.dumps(payload, ensure_ascii=True, sort_keys=True)))
        if len(_pending_events) >= FLUSH_BATCH_SIZE:
            _flush_locked()
        else:
            _schedule_flush_locked()
    return True


def event_payloads_for_upload(limit: int = 100) -> list[dict[str, object]]:
    """Expose sanitized queue payloads to a future official HTTPS uploader only."""
    if not _path().exists():
        return []
    flush()
    with _lock, _connect() as connection:
        if _setting(connection, "enabled") != "true":
            return []
        installation_id = _setting(connection, "installation_id")
        rows = connection.execute(
            "SELECT id, event_name, occurred_at, properties FROM telemetry_events ORDER BY occurred_at LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
    return [
        {
            "event_id": row[0],
            "event_name": row[1],
            "occurred_at": row[2],
            "installation_id": installation_id,
            "app_version": settings.app_version,
            "platform": platform.system().lower(),
            "properties": json.loads(row[3]),
        }
        for row in rows
    ]
