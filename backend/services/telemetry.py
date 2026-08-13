"""Minimal, default-enabled, privacy-preserving local telemetry queue."""

from __future__ import annotations

import json
import os
import platform
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock, Timer
from typing import Any

from config import ensure_private_data_directory, ensure_private_data_file, settings

EVENT_FIELDS: dict[str, frozenset[str]] = {
    "app_started": frozenset(),
    "workspace_opened": frozenset({"view"}),
    "import_started": frozenset({"input_kind"}),
    "import_completed": frozenset({"result"}),
    "task_enqueued": frozenset({"processing_mode"}),
    "pipeline_stage_reached": frozenset({"stage"}),
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
    "export_completed": frozenset({"export_kind", "result"}),
}

# A notice version is a material disclosure boundary, not a cosmetic copy
# revision.  The v3 boundary records that new installations start with the
# fixed diagnostic catalog enabled and can opt out at any time.
SCHEMA_VERSION = 1
PRIVACY_NOTICE_VERSION = "2026-08-telemetry-v3"
MAX_PENDING_EVENTS = 10_000
MAX_EVENT_AGE_DAYS = 14
DEFAULT_ENABLED = "default_enabled"
EXPLICIT_ENABLED = "explicit_enabled"
EXPLICIT_DISABLED = "explicit_disabled"
ERROR_DISABLED = "error_disabled"
_ENABLED_PREFERENCES = frozenset({DEFAULT_ENABLED, EXPLICIT_ENABLED})
_PREFERENCE_FILE_NAME = "telemetry-preference"

_ENUM_VALUES: dict[str, frozenset[str]] = {
    "action": frozenset({"retry", "pause", "resume", "cancel"}),
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
_upload_gate = Lock()
_pending_events: list[tuple[str, str, str, str]] = []
_pending_events_path: Path | None = None
_flush_timer: Timer | None = None
_flush_timer_path: Path | None = None
_enabled_cache: bool | None = None
_enabled_cache_path: Path | None = None
_preference_cache: str | None = None
_upload_generation = 0
FLUSH_INTERVAL_SECONDS = 2.0
FLUSH_BATCH_SIZE = 20


def _path() -> Path:
    return settings.data_dir / "telemetry.sqlite"


def _preference_path() -> Path:
    return settings.data_dir / _PREFERENCE_FILE_NAME


def _connect() -> sqlite3.Connection:
    database_path = _path()
    ensure_private_data_directory(database_path.parent)
    ensure_private_data_file(database_path, create=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 1000")
        connection.execute("CREATE TABLE IF NOT EXISTS telemetry_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS telemetry_events (id TEXT PRIMARY KEY, event_name TEXT NOT NULL, occurred_at TEXT NOT NULL, properties TEXT NOT NULL)"
        )
        ensure_private_data_file(database_path)
        ensure_private_data_file(Path(f"{database_path}-wal"))
        ensure_private_data_file(Path(f"{database_path}-shm"))
        return connection
    except Exception:
        connection.close()
        raise


@contextmanager
def _managed_connection() -> Iterator[sqlite3.Connection]:
    """Commit or roll back a short transaction, then close every SQLite handle."""
    connection = _connect()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


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


def _current_enabled(connection: sqlite3.Connection) -> bool:
    return (
        _setting(connection, "enabled") == "true"
        and _setting(connection, "privacy_notice_version") == PRIVACY_NOTICE_VERSION
        and _setting(connection, "preference") in _ENABLED_PREFERENCES
    )


def _write_disabled_preference() -> None:
    path = _preference_path()
    ensure_private_data_directory(path.parent)
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(f"{EXPLICIT_DISABLED}\n", encoding="utf-8")
    ensure_private_data_file(temporary_path)
    os.replace(temporary_path, path)
    ensure_private_data_file(path)


def _remove_disabled_preference() -> None:
    _preference_path().unlink(missing_ok=True)


def _delete_database_files() -> bool:
    """Best-effort removal of every SQLite artifact after all handles close."""
    database_path = _path()
    removed_all = True
    for candidate in (
        Path(f"{database_path}-journal"),
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
        database_path,
    ):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            # The durable opt-out marker remains authoritative. Keep trying the
            # other artifacts so one locked sidecar cannot preserve the main DB.
            removed_all = False
    return removed_all


def _cancel_flush_timer_locked() -> None:
    global _flush_timer, _flush_timer_path
    if _flush_timer is not None:
        _flush_timer.cancel()
    _flush_timer = None
    _flush_timer_path = None


def _discard_pending_locked() -> None:
    global _pending_events_path
    _cancel_flush_timer_locked()
    _pending_events.clear()
    _pending_events_path = None


def _prepare_runtime_path_locked(cache_path: Path) -> None:
    """Never let an in-memory event or timer cross application data roots."""
    global _enabled_cache, _enabled_cache_path, _preference_cache, _upload_generation
    if _enabled_cache_path is not None and _enabled_cache_path != cache_path:
        _discard_pending_locked()
        _enabled_cache = None
        _enabled_cache_path = None
        _preference_cache = None
        _upload_generation += 1
    elif _pending_events_path is not None and _pending_events_path != cache_path:
        _discard_pending_locked()


def _set_runtime_state_locked(cache_path: Path, enabled: bool, preference: str) -> None:
    global _enabled_cache, _enabled_cache_path, _preference_cache, _upload_generation
    changed = (
        _enabled_cache_path != cache_path
        or _enabled_cache is not enabled
        or _preference_cache != preference
    )
    _enabled_cache = enabled
    _enabled_cache_path = cache_path
    _preference_cache = preference
    if changed:
        _upload_generation += 1


def _mark_storage_error_locked(cache_path: Path) -> None:
    _discard_pending_locked()
    _set_runtime_state_locked(cache_path, False, ERROR_DISABLED)


def _activate_connection(
    connection: sqlite3.Connection,
    *,
    preference: str,
    rotate_installation: bool,
) -> None:
    if rotate_installation:
        connection.execute("DELETE FROM telemetry_events")
    connection.execute("INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('enabled', 'true')")
    connection.execute(
        "INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('privacy_notice_version', ?)",
        (PRIVACY_NOTICE_VERSION,),
    )
    connection.execute(
        "INSERT OR REPLACE INTO telemetry_settings(key, value) VALUES ('preference', ?)",
        (preference,),
    )
    if rotate_installation:
        connection.execute("DELETE FROM telemetry_settings WHERE key = 'installation_id'")
    if not _setting(connection, "installation_id"):
        connection.execute(
            "INSERT INTO telemetry_settings(key, value) VALUES ('installation_id', ?)",
            (str(uuid.uuid4()),),
        )


def _bootstrap_locked() -> str:
    """Resolve the durable preference before any event can be recorded."""
    global _upload_generation
    database_path = _path()
    cache_path = database_path.expanduser().resolve()
    _prepare_runtime_path_locked(cache_path)
    if _preference_path().exists():
        _discard_pending_locked()
        _delete_database_files()
        _set_runtime_state_locked(cache_path, False, EXPLICIT_DISABLED)
        return EXPLICIT_DISABLED

    if (
        _enabled_cache_path == cache_path
        and _enabled_cache is not None
        and _preference_cache is not None
        and _preference_cache != ERROR_DISABLED
        and (not _enabled_cache or database_path.exists())
    ):
        return _preference_cache

    try:
        if not database_path.exists():
            # A vanished queue rotates the pseudonymous installation identity;
            # events buffered for the previous database must not follow it.
            _discard_pending_locked()
            with _managed_connection() as connection:
                _activate_connection(
                    connection,
                    preference=DEFAULT_ENABLED,
                    rotate_installation=True,
                )
            _upload_generation += 1
            _set_runtime_state_locked(cache_path, True, DEFAULT_ENABLED)
            return DEFAULT_ENABLED

        should_disable = False
        notice_changed = False
        with _managed_connection() as connection:
            stored_enabled = _setting(connection, "enabled") == "true"
            stored_preference = _setting(connection, "preference")
            if not stored_enabled or stored_preference == EXPLICIT_DISABLED:
                should_disable = True
            else:
                # A pre-v3 database could only exist after an explicit opt-in.
                # Preserve that choice, but never relabel or upload old-notice
                # events: clear the queue and rotate its pseudonymous ID.
                preference = stored_preference if stored_preference in _ENABLED_PREFERENCES else EXPLICIT_ENABLED
                notice_changed = _setting(connection, "privacy_notice_version") != PRIVACY_NOTICE_VERSION
                _activate_connection(
                    connection,
                    preference=preference,
                    rotate_installation=notice_changed,
                )
        if should_disable:
            _write_disabled_preference()
            _discard_pending_locked()
            _delete_database_files()
            _set_runtime_state_locked(cache_path, False, EXPLICIT_DISABLED)
            return EXPLICIT_DISABLED
        if notice_changed:
            _discard_pending_locked()
            _upload_generation += 1
    except (OSError, sqlite3.Error):
        _mark_storage_error_locked(cache_path)
        return ERROR_DISABLED

    _set_runtime_state_locked(cache_path, True, preference)
    return preference


def bootstrap() -> str:
    """Initialize a fresh installation or restore its explicit preference."""
    global _enabled_cache, _enabled_cache_path, _preference_cache, _upload_generation
    with _lock:
        try:
            return _bootstrap_locked()
        except (OSError, sqlite3.Error, RuntimeError, ValueError):
            # A malformed/unavailable data root is not allowed to prevent the
            # local application from starting. Leave no queued work and retry
            # storage resolution on the next call instead of caching forever.
            _discard_pending_locked()
            _enabled_cache = False
            _enabled_cache_path = None
            _preference_cache = ERROR_DISABLED
            _upload_generation += 1
            return ERROR_DISABLED


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
    if set(payload) != allowed:
        raise ValueError("遥测事件字段与固定目录不一致")
    sanitized: dict[str, str] = {}
    for key, value in payload.items():
        choices = _ENUM_VALUES[key]
        normalized = value if isinstance(value, str) else "other"
        sanitized[key] = normalized if normalized in choices else "other"
    return sanitized


def telemetry_stage_bucket(value: object) -> str:
    """Map internal pipeline steps to the public, fixed telemetry catalog."""
    stage = str(value or "").strip().lower()
    mapped = {
        "queued": "queued",
        "parse": "prepare",
        "info": "prepare",
        "extract": "prepare",
        "download": "download",
        "extract_audio": "prepare",
        "wait_for_ocr": "ocr",
        "ocr": "ocr",
        "transcribe": "transcribe",
        "asr": "asr",
        "analyze": "analyze",
        "cover_generate": "analyze",
        "summarize": "summary",
        "summary": "summary",
        "save": "export",
        "export": "export",
        "executor": "executor",
    }
    if not stage:
        return "unknown"
    return mapped.get(stage, "other")


def _flush_locked(cache_path: Path) -> None:
    global _pending_events_path
    if not _pending_events:
        _pending_events_path = None
        return
    if (
        _pending_events_path != cache_path
        or _enabled_cache_path != cache_path
        or not _enabled_cache
        or _preference_path().exists()
        or not _path().exists()
    ):
        _discard_pending_locked()
        return
    try:
        with _managed_connection() as connection:
            if not _current_enabled(connection):
                _discard_pending_locked()
                return
            connection.executemany(
                "INSERT INTO telemetry_events(id, event_name, occurred_at, properties) VALUES (?, ?, ?, ?)",
                _pending_events,
            )
            # Prune after insertion so the documented 10,000-row limit is a
            # hard bound rather than MAX_PENDING_EVENTS + one memory batch.
            _prune(connection)
            _pending_events.clear()
            _pending_events_path = None
    except (OSError, sqlite3.Error):
        # Telemetry must never delay processing; retain the bounded batch for a
        # later flush and drop excess only if local storage stays unavailable.
        del _pending_events[:-FLUSH_BATCH_SIZE]
        if not _pending_events:
            _pending_events_path = None


def flush() -> None:
    with _lock:
        try:
            cache_path = _path().expanduser().resolve()
        except (OSError, RuntimeError):
            _discard_pending_locked()
            return
        if _pending_events_path is not None and _pending_events_path != cache_path:
            _discard_pending_locked()
            return
        _cancel_flush_timer_locked()
        _flush_locked(cache_path)


def _flush_for_path(expected_path: Path) -> None:
    global _flush_timer, _flush_timer_path, _pending_events_path
    with _lock:
        if _flush_timer_path == expected_path:
            _flush_timer = None
            _flush_timer_path = None
        try:
            current_path = _path().expanduser().resolve()
        except (OSError, RuntimeError):
            if _pending_events_path == expected_path:
                _pending_events.clear()
                _pending_events_path = None
            return
        if current_path != expected_path or _pending_events_path != expected_path:
            if _pending_events_path == expected_path:
                _pending_events.clear()
                _pending_events_path = None
            return
        _flush_locked(expected_path)


def _schedule_flush_locked(cache_path: Path) -> None:
    global _flush_timer, _flush_timer_path
    if _flush_timer is not None and _flush_timer_path != cache_path:
        _cancel_flush_timer_locked()
    if _flush_timer is None:
        _flush_timer_path = cache_path
        _flush_timer = Timer(FLUSH_INTERVAL_SECONDS, _flush_for_path, args=(cache_path,))
        _flush_timer.daemon = True
        _flush_timer.start()


def _status_payload(*, enabled: bool, pending_events: int, preference: str) -> dict[str, object]:
    return {
        "enabled": enabled,
        "pending_events": pending_events if enabled else 0,
        "event_catalog_size": len(EVENT_FIELDS),
        "privacy_notice_version": PRIVACY_NOTICE_VERSION,
        "requires_consent": False,
        "notice_required": enabled,
        "preference_source": preference,
    }


def status() -> dict[str, object]:
    preference = bootstrap()
    if preference in _ENABLED_PREFERENCES:
        flush()
    with _lock:
        try:
            cache_path = _path().expanduser().resolve()
        except (OSError, RuntimeError):
            return _status_payload(enabled=False, pending_events=0, preference=ERROR_DISABLED)
        current_preference = (
            _preference_cache
            if _enabled_cache_path == cache_path and _preference_cache is not None
            else preference
        )
        if (
            current_preference not in _ENABLED_PREFERENCES
            or _enabled_cache_path != cache_path
            or not _enabled_cache
            or _preference_path().exists()
            or not _path().exists()
        ):
            return _status_payload(enabled=False, pending_events=0, preference=current_preference)
        try:
            with _managed_connection() as connection:
                enabled = _current_enabled(connection)
                pending = int(connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]) if enabled else 0
        except (OSError, sqlite3.Error):
            _mark_storage_error_locked(cache_path)
            return _status_payload(enabled=False, pending_events=0, preference=ERROR_DISABLED)
        if not enabled:
            _mark_storage_error_locked(cache_path)
            return _status_payload(enabled=False, pending_events=0, preference=ERROR_DISABLED)
        return _status_payload(enabled=True, pending_events=pending, preference=current_preference)


def set_enabled(enabled: bool, *, notice_version: str = "") -> dict[str, object]:
    global _upload_generation
    if enabled and notice_version != PRIVACY_NOTICE_VERSION:
        raise ValueError("请先阅读当前隐私与诊断说明")
    with _upload_gate, _lock:
        database_path = _path()
        cache_path = database_path.expanduser().resolve()
        _prepare_runtime_path_locked(cache_path)
        if enabled:
            marker_existed = _preference_path().exists()
            if marker_existed:
                _delete_database_files()
            try:
                with _managed_connection() as connection:
                    was_enabled = _current_enabled(connection)
                    _activate_connection(
                        connection,
                        preference=EXPLICIT_ENABLED,
                        rotate_installation=not was_enabled,
                    )
                    if not was_enabled:
                        connection.execute(
                            "INSERT INTO telemetry_events(id, event_name, occurred_at, properties) VALUES (?, ?, ?, ?)",
                            (str(uuid.uuid4()), "telemetry_consent_changed", _now(), '{"state":"enabled"}'),
                        )
                _remove_disabled_preference()
            except (OSError, sqlite3.Error):
                if marker_existed:
                    _delete_database_files()
                _mark_storage_error_locked(cache_path)
                raise
            _upload_generation += 1
            _set_runtime_state_locked(cache_path, True, EXPLICIT_ENABLED)
        else:
            # Persist the marker before removing anything. If this write fails,
            # the previous enabled state remains truthful and the request fails.
            _write_disabled_preference()
            _upload_generation += 1
            _discard_pending_locked()
            cleanup_complete = _delete_database_files()
            _set_runtime_state_locked(cache_path, False, EXPLICIT_DISABLED)
            if not cleanup_complete:
                raise OSError("匿名诊断已关闭，但本地遥测文件尚未完全清除；应用将在下次检查时重试")
    return status()


def record(event_name: str, properties: dict[str, Any] | None = None) -> bool:
    global _pending_events_path
    payload = _sanitize_properties(event_name, properties)
    preference = bootstrap()
    if preference not in _ENABLED_PREFERENCES:
        return False
    with _lock:
        try:
            cache_path = _path().expanduser().resolve()
        except (OSError, RuntimeError):
            return False
        if (
            _enabled_cache_path != cache_path
            or not _enabled_cache
            or _preference_cache not in _ENABLED_PREFERENCES
            or _preference_path().exists()
            or not _path().exists()
        ):
            return False
        if _pending_events_path is not None and _pending_events_path != cache_path:
            _discard_pending_locked()
        _pending_events_path = cache_path
        _pending_events.append((str(uuid.uuid4()), event_name, _now(), json.dumps(payload, ensure_ascii=True, sort_keys=True)))
        if len(_pending_events) >= FLUSH_BATCH_SIZE:
            _cancel_flush_timer_locked()
            _flush_locked(cache_path)
        else:
            _schedule_flush_locked(cache_path)
    return True


def _event_payload_snapshot(limit: int) -> tuple[int, list[dict[str, object]]]:
    if bootstrap() not in _ENABLED_PREFERENCES:
        with _lock:
            return _upload_generation, []
    flush()
    with _lock:
        try:
            cache_path = _path().expanduser().resolve()
        except (OSError, RuntimeError):
            return _upload_generation, []
        generation = _upload_generation
        if (
            _enabled_cache_path != cache_path
            or not _enabled_cache
            or _preference_cache not in _ENABLED_PREFERENCES
            or _preference_path().exists()
            or not _path().exists()
        ):
            return generation, []
        try:
            with _managed_connection() as connection:
                if not _current_enabled(connection):
                    return generation, []
                installation_id = _setting(connection, "installation_id")
                rows = connection.execute(
                    "SELECT id, event_name, occurred_at, properties FROM telemetry_events ORDER BY occurred_at LIMIT ?",
                    (max(1, min(limit, 100)),),
                ).fetchall()
            events = [
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
        except (OSError, sqlite3.Error, TypeError, ValueError):
            _mark_storage_error_locked(cache_path)
            return _upload_generation, []
        return generation, events


def event_payloads_for_upload(limit: int = 100) -> list[dict[str, object]]:
    """Expose sanitized queue payloads to the official HTTPS uploader only."""
    return _event_payload_snapshot(limit)[1]


def _batch_from_events(events: list[dict[str, object]]) -> dict[str, object] | None:
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


def upload_batch_snapshot(limit: int = 100) -> tuple[int, dict[str, object]] | None:
    """Build one batch and atomically capture the opt-out generation."""
    generation, events = _event_payload_snapshot(limit)
    batch = _batch_from_events(events)
    return (generation, batch) if batch is not None else None


def upload_batch(limit: int = 100) -> dict[str, object] | None:
    snapshot = upload_batch_snapshot(limit=limit)
    return snapshot[1] if snapshot is not None else None


@contextmanager
def upload_send_permission(generation: int) -> Iterator[bool]:
    """Serialize opt-out with the network send without holding the DB lock."""
    with _upload_gate:
        with _lock:
            allowed = False
            try:
                preference = _bootstrap_locked()
                cache_path = _path().expanduser().resolve()
                allowed = (
                    generation == _upload_generation
                    and preference in _ENABLED_PREFERENCES
                    and _enabled_cache_path == cache_path
                    and bool(_enabled_cache)
                    and not _preference_path().exists()
                    and _path().exists()
                )
            except (OSError, sqlite3.Error, RuntimeError):
                allowed = False
        yield allowed


def acknowledge_uploaded_events(event_ids: list[str]) -> int:
    """Delete only event IDs confirmed by the official collector."""
    normalized = tuple(dict.fromkeys(str(event_id) for event_id in event_ids if event_id))
    if not normalized:
        return 0
    placeholders = ",".join("?" for _ in normalized)
    with _lock:
        try:
            cache_path = _path().expanduser().resolve()
        except (OSError, RuntimeError):
            return 0
        if (
            _preference_path().exists()
            or not _path().exists()
            or _enabled_cache_path != cache_path
            or not _enabled_cache
        ):
            return 0
        try:
            with _managed_connection() as connection:
                if not _current_enabled(connection):
                    return 0
                cursor = connection.execute(f"DELETE FROM telemetry_events WHERE id IN ({placeholders})", normalized)
                return max(0, int(cursor.rowcount))
        except (OSError, sqlite3.Error):
            _mark_storage_error_locked(cache_path)
            return 0
