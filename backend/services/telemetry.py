"""Minimal, opt-in, privacy-preserving local telemetry queue."""

from __future__ import annotations

import json
import platform
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
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

# A notice version is a consent boundary, not a cosmetic copy revision.  New
# events or fields must advance it, which makes an installed older consent
# inactive until the person has read the updated, non-modal notice.
SCHEMA_VERSION = 1
PRIVACY_NOTICE_VERSION = "2026-08-telemetry-v1"
MAX_PENDING_EVENTS = 10_000
MAX_EVENT_AGE_DAYS = 14

_ENUM_VALUES: dict[str, frozenset[str]] = {
    "action": frozenset({"retry", "pause", "resume", "cancel"}),
    "backend": frozenset({"faster_whisper", "mlx", "other"}),
    "duration_bucket": frozenset({"0_1m", "1_10m", "10_60m", "60m_plus", "other"}),
    "export_kind": frozenset({"markdown", "other"}),
    "input_kind": frozenset({"link", "other"}),
    "processing_mode": frozenset({"full", "transcript", "other"}),
    "result": frozenset({"accepted", "available", "conflict", "disabled", "empty", "failed", "succeeded", "unavailable", "up_to_date", "other"}),
    "result_count_bucket": frozenset({"0", "1_5", "6_20", "21_100", "101_plus", "other"}),
    "stage": frozenset({"analyze", "asr", "download", "executor", "export", "ocr", "prepare", "queued", "summary", "transcribe", "unknown", "other"}),
    "state": frozenset({"enabled", "disabled", "other"}),
    "view": frozenset({"campus", "creator", "knowledge", "library", "prompts", "reports", "rss", "wechat", "other"}),
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


def _os_major() -> int:
    try:
        return max(0, int((platform.mac_ver()[0] or "0").split(".", 1)[0]))
    except ValueError:
        return 0


def _architecture() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64", "x64"}:
        return "x64"
    return "other"


def _current_consent(connection: sqlite3.Connection) -> bool:
    return (
        _setting(connection, "enabled") == "true"
        and _setting(connection, "privacy_notice_version") == PRIVACY_NOTICE_VERSION
    )


def _prune(connection: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=MAX_EVENT_AGE_DAYS)).isoformat()
    connection.execute("DELETE FROM telemetry_events WHERE occurred_at < ?", (cutoff,))
    overflow = connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0] - MAX_PENDING_EVENTS
    if overflow > 0:
        connection.execute(
            "DELETE FROM telemetry_events WHERE id IN (SELECT id FROM telemetry_events ORDER BY occurred_at LIMIT ?)",
            (overflow,),
        )


def _sanitize_properties(event_name: str, properties: dict[str, Any] | None) -> dict[str, str]:
    allowed = EVENT_FIELDS.get(event_name)
    if allowed is None:
        raise ValueError("未知遥测事件")
    payload = properties or {}
    if set(payload) - allowed:
        raise ValueError("遥测事件包含未允许字段")
    sanitized: dict[str, str] = {}
    for key, value in payload.items():
        choices = _ENUM_VALUES[key]
        normalized = value if isinstance(value, str) else "other"
        sanitized[key] = normalized if normalized in choices else "other"
    return sanitized


def _flush_locked() -> None:
    global _flush_timer
    _flush_timer = None
    if not _pending_events or not _path().exists():
        return
    try:
        with _connect() as connection:
            if not _current_consent(connection):
                _pending_events.clear()
                return
            _prune(connection)
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
        return {
            "enabled": False,
            "pending_events": 0,
            "event_catalog_size": len(EVENT_FIELDS),
            "privacy_notice_version": PRIVACY_NOTICE_VERSION,
            "requires_consent": True,
        }
    with _lock, _connect() as connection:
        enabled = _current_consent(connection)
        if not enabled and _setting(connection, "enabled") == "true":
            # A new notice version must never silently inherit older consent or
            # upload events gathered under it.
            connection.execute("DELETE FROM telemetry_events")
            connection.execute("INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('enabled', 'false')")
        pending = int(connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]) if enabled else 0
        return {
            "enabled": enabled,
            "pending_events": pending,
            "event_catalog_size": len(EVENT_FIELDS),
            "privacy_notice_version": PRIVACY_NOTICE_VERSION,
            "requires_consent": not enabled,
        }


def set_enabled(enabled: bool, *, notice_version: str = "") -> dict[str, object]:
    global _enabled_cache, _flush_timer
    database_path = _path()
    with _lock:
        if enabled:
            if notice_version != PRIVACY_NOTICE_VERSION:
                raise ValueError("请先阅读当前隐私与诊断说明")
            with _connect() as connection:
                connection.execute("INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('enabled', 'true')")
                connection.execute(
                    "INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('privacy_notice_version', ?)",
                    (PRIVACY_NOTICE_VERSION,),
                )
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
    payload = _sanitize_properties(event_name, properties)
    if not _path().exists():
        return False
    with _lock:
        if _enabled_cache is None:
            try:
                with _connect() as connection:
                    _enabled_cache = _current_consent(connection)
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
    """Expose sanitized queue payloads to the official HTTPS uploader only."""
    if not _path().exists():
        return []
    flush()
    with _lock, _connect() as connection:
        if not _current_consent(connection):
            return []
        installation_id = _setting(connection, "installation_id")
        rows = connection.execute(
            "SELECT id, event_name, occurred_at, properties FROM telemetry_events ORDER BY occurred_at LIMIT ?", (max(1, min(limit, 100)),)
        ).fetchall()
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "privacy_notice_version": PRIVACY_NOTICE_VERSION,
            "event_id": row[0],
            "event_name": row[1],
            "occurred_at": row[2],
            "installation_id": installation_id,
            "app_version": settings.app_version,
            "platform": platform.system().lower(),
            "architecture": _architecture(),
            "os_major": _os_major(),
            "properties": json.loads(row[3]),
        }
        for row in rows
    ]


def upload_batch(limit: int = 100) -> dict[str, object] | None:
    events = event_payloads_for_upload(limit=limit)
    if not events:
        return None
    installation_id = str(events[0].pop("installation_id"))
    for event in events[1:]:
        event.pop("installation_id", None)
    return {
        "schema_version": SCHEMA_VERSION,
        "privacy_notice_version": PRIVACY_NOTICE_VERSION,
        "installation_id": installation_id,
        "events": events,
    }


def acknowledge_uploaded_events(event_ids: list[str]) -> int:
    """Delete only event IDs confirmed by the official collector."""
    normalized = tuple(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
    if not normalized:
        return 0
    placeholders = ",".join("?" for _ in normalized)
    with _lock:
        if not _path().exists():
            return 0
        with _connect() as connection:
            if not _current_consent(connection):
                return 0
            cursor = connection.execute(f"DELETE FROM telemetry_events WHERE id IN ({placeholders})", normalized)
            return max(0, int(cursor.rowcount))
