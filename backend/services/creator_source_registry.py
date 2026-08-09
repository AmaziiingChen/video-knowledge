from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings
from services.creator_sync_models import CreatorSyncError
from services.creator_sync_policy import (
    creator_error_category,
    creator_retry_minutes,
    effective_processing_mode,
    valid_interval,
    valid_processing_mode,
)
from services.database import connect, initialize_database, utc_now_iso
from services.repository import new_id


def list_creator_sources() -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, provider, source_url, source_kind, creator_key, creator_name,
                   library_folder_id, enabled, auto_process, processing_mode, sync_interval_minutes,
                   sync_limit, queue_limit, last_sync_at, next_sync_at, last_seen_published_at,
                   last_error, last_error_category, consecutive_failure_count,
                   last_discovered_count, last_created_count,
                   created_at, updated_at
            FROM creator_sources
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [serialize_creator_source(row) for row in rows]


def get_creator_source(source_id: str) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise LookupError(source_id)
    return serialize_creator_source(row)


def list_creator_sync_runs(source_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT status, error_category, message, discovered_count, created_count, created_at
               FROM creator_sync_runs WHERE source_id=? ORDER BY created_at DESC LIMIT ?""",
            (source_id, max(1, min(int(limit), 30))),
        ).fetchall()
    return [dict(row) for row in rows]


def update_creator_source(
    source_id: str,
    *,
    enabled: bool | None = None,
    auto_process: bool | None = None,
    processing_mode: str | None = None,
    sync_interval_minutes: int | None = None,
) -> dict[str, Any]:
    if all(value is None for value in (enabled, auto_process, processing_mode, sync_interval_minutes)):
        raise CreatorSyncError("至少提供一个需要更新的订阅设置")
    if sync_interval_minutes is not None:
        valid_interval(sync_interval_minutes)
    if processing_mode is not None:
        valid_processing_mode(processing_mode)
    initialize_database()
    with connect() as connection:
        current = connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
        if not current:
            raise LookupError(source_id)
        next_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        next_interval = valid_interval(sync_interval_minutes if sync_interval_minutes is not None else current["sync_interval_minutes"])
        next_mode = effective_processing_mode(current, processing_mode, auto_process)
        next_sync_at = utc_now_iso() if enabled is True else current["next_sync_at"]
        connection.execute(
            """UPDATE creator_sources
               SET enabled=?, auto_process=?, processing_mode=?, sync_interval_minutes=?,
                   next_sync_at=?, updated_at=? WHERE id=?""",
            (
                int(next_enabled),
                int(next_mode != "metadata"),
                next_mode,
                next_interval,
                next_sync_at,
                utc_now_iso(),
                source_id,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
    return serialize_creator_source(row)


def delete_creator_source(source_id: str) -> None:
    initialize_database()
    with connect() as connection:
        cursor = connection.execute("DELETE FROM creator_sources WHERE id=?", (source_id,))
        connection.commit()
    if not cursor.rowcount:
        raise LookupError(source_id)


def source_row(connection, *, source_id: str | None, source_identity: str):
    if source_id:
        return connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
    return connection.execute("SELECT * FROM creator_sources WHERE source_identity=?", (source_identity,)).fetchone()


def creator_source_item_ids(source_id: str) -> set[str]:
    """Return the durable membership anchor for an incremental check."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT remote_item_id FROM creator_source_items WHERE source_id=?",
            (source_id,),
        ).fetchall()
    return {str(row["remote_item_id"]).strip() for row in rows if str(row["remote_item_id"] or "").strip()}


def source_identity(provider: str, source_kind: str, creator_key: str) -> str:
    return f"{provider}:{source_kind}:{creator_key}"


def due_creator_source_ids(now: str) -> list[str]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT id FROM creator_sources
               WHERE enabled=1 AND (next_sync_at IS NULL OR next_sync_at='' OR next_sync_at<=?)
               ORDER BY COALESCE(next_sync_at, created_at), created_at""",
            (now,),
        ).fetchall()
    return [str(row["id"]) for row in rows]


def serialize_creator_source(row) -> dict[str, Any]:
    source = dict(row)
    source["enabled"] = bool(source.get("enabled", True))
    source["auto_process"] = bool(source.get("auto_process", True))
    source["processing_mode"] = valid_processing_mode(source.get("processing_mode") or ("full" if source["auto_process"] else "metadata"))
    source["sync_interval_minutes"] = valid_interval(
        source.get("sync_interval_minutes", settings.creator_default_interval_minutes)
    )
    # These fields remain in SQLite solely for migration compatibility. They
    # are intentionally not exposed or used by the incremental-sync contract.
    source["consecutive_failure_count"] = max(0, int(source.get("consecutive_failure_count") or 0))
    source["last_discovered_count"] = max(0, int(source.get("last_discovered_count") or 0))
    source["last_created_count"] = max(0, int(source.get("last_created_count") or 0))
    return source


def record_sync_success(
    source_id: str,
    *,
    interval_minutes: int,
    discovered_count: int,
    created_count: int,
    last_seen_published_at: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    next_sync = now + timedelta(minutes=interval_minutes)
    with connect() as connection:
        connection.execute(
            """UPDATE creator_sources
               SET last_sync_at=?, next_sync_at=?, last_seen_published_at=?, last_error=NULL,
                   last_error_category=NULL, consecutive_failure_count=0,
                   last_discovered_count=?, last_created_count=?, updated_at=?
               WHERE id=?""",
            (
                now.isoformat(),
                next_sync.isoformat(),
                last_seen_published_at,
                max(0, int(discovered_count)),
                max(0, int(created_count)),
                now.isoformat(),
                source_id,
            ),
        )
        connection.execute(
            """INSERT INTO creator_sync_runs
               (id, source_id, status, message, discovered_count, created_count, created_at)
               VALUES (?, ?, 'succeeded', '', ?, ?, ?)""",
            (new_id(), source_id, max(0, int(discovered_count)), max(0, int(created_count)), now.isoformat()),
        )
        connection.commit()


def record_sync_error(source_id: str, message: str) -> None:
    now = datetime.now(timezone.utc)
    with connect() as connection:
        row = connection.execute(
            "SELECT sync_interval_minutes, consecutive_failure_count FROM creator_sources WHERE id=?", (source_id,)
        ).fetchone()
        if not row:
            return
        category = creator_error_category(message)
        failures = max(0, int(row["consecutive_failure_count"] or 0)) + 1
        retry_minutes = creator_retry_minutes(category, failures, valid_interval(row["sync_interval_minutes"]))
        connection.execute(
            """UPDATE creator_sources
               SET last_error=?, last_error_category=?, consecutive_failure_count=?, next_sync_at=?, updated_at=? WHERE id=?""",
            (str(message or "同步失败")[:500], category, failures, (now + timedelta(minutes=retry_minutes)).isoformat(), now.isoformat(), source_id),
        )
        connection.execute(
            """INSERT INTO creator_sync_runs (id, source_id, status, error_category, message, created_at)
               VALUES (?, ?, 'failed', ?, ?, ?)""",
            (new_id(), source_id, category, str(message or "同步失败")[:500], now.isoformat()),
        )
        connection.commit()
