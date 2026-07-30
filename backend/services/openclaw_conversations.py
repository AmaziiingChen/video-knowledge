from __future__ import annotations

import hashlib
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from services.database import connect, initialize_database, utc_now_iso


TERMINAL_TASK_STATUSES = {"succeeded", "failed", "cancelled"}
MAX_MESSAGE_CHARS = 12_000
NOTIFICATION_RESERVATION_SECONDS = 120


@dataclass(frozen=True)
class ConversationSettings:
    transcript_mirror_enabled: bool
    transcript_retention_days: int
    updated_at: str


def _session_hash(session_key: str) -> str:
    key = session_key.strip()
    if not key:
        raise ValueError("会话标识不能为空")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _conversation_id(session_hash: str) -> str:
    return f"oc_{session_hash[:12]}"


def _settings(connection: sqlite3.Connection) -> ConversationSettings:
    row = connection.execute(
        """
        SELECT transcript_mirror_enabled, transcript_retention_days, updated_at
        FROM openclaw_conversation_settings WHERE id = 1
        """
    ).fetchone()
    if row is None:
        now = utc_now_iso()
        connection.execute(
            """
            INSERT INTO openclaw_conversation_settings(
                id, transcript_mirror_enabled, transcript_retention_days, updated_at
            ) VALUES (1, 0, 30, ?)
            """,
            (now,),
        )
        return ConversationSettings(False, 30, now)
    return ConversationSettings(
        transcript_mirror_enabled=bool(row["transcript_mirror_enabled"]),
        transcript_retention_days=int(row["transcript_retention_days"]),
        updated_at=str(row["updated_at"]),
    )


def _prune_messages(connection: sqlite3.Connection, settings: ConversationSettings) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.transcript_retention_days)).isoformat()
    connection.execute(
        "DELETE FROM openclaw_conversation_messages WHERE created_at < ?",
        (cutoff,),
    )


def _touch_conversation(
    connection: sqlite3.Connection,
    *,
    session_hash: str,
    channel: str,
    display_name: str | None,
) -> None:
    now = utc_now_iso()
    connection.execute(
        """
        INSERT INTO openclaw_conversations(session_hash, channel, display_name, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(session_hash) DO UPDATE SET
            channel = CASE WHEN excluded.channel <> '' THEN excluded.channel ELSE openclaw_conversations.channel END,
            display_name = CASE WHEN excluded.display_name <> '' THEN excluded.display_name ELSE openclaw_conversations.display_name END,
            last_seen_at = excluded.last_seen_at
        """,
        (session_hash, channel.strip() or "unknown", (display_name or "").strip()[:120], now, now),
    )


def get_conversation_settings() -> dict[str, object]:
    initialize_database()
    with connect() as connection:
        settings = _settings(connection)
    return asdict(settings)


def update_conversation_settings(*, transcript_mirror_enabled: bool, transcript_retention_days: int) -> dict[str, object]:
    if not 1 <= transcript_retention_days <= 365:
        raise ValueError("对话保留天数必须介于 1 到 365 之间")
    initialize_database()
    with connect() as connection:
        now = utc_now_iso()
        connection.execute(
            """
            INSERT INTO openclaw_conversation_settings(
                id, transcript_mirror_enabled, transcript_retention_days, updated_at
            ) VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                transcript_mirror_enabled = excluded.transcript_mirror_enabled,
                transcript_retention_days = excluded.transcript_retention_days,
                updated_at = excluded.updated_at
            """,
            (int(transcript_mirror_enabled), transcript_retention_days, now),
        )
        settings = _settings(connection)
        _prune_messages(connection, settings)
        connection.commit()
    return asdict(settings)


def bind_task(
    *,
    session_key: str,
    task_id: str,
    channel: str = "weixin",
    display_name: str | None = None,
) -> dict[str, object]:
    """Bind an existing task to an opaque OpenClaw conversation identifier."""
    session_hash = _session_hash(session_key)
    initialize_database()
    with connect() as connection:
        task = connection.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if task is None:
            raise LookupError("任务不存在，无法绑定会话")
        _touch_conversation(
            connection,
            session_hash=session_hash,
            channel=channel,
            display_name=display_name,
        )
        now = utc_now_iso()
        connection.execute(
            """
            INSERT INTO openclaw_task_bindings(id, session_hash, task_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_hash, task_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (uuid.uuid4().hex, session_hash, task_id, now, now),
        )
        connection.commit()
    return {"conversation_id": _conversation_id(session_hash), "task_id": task_id, "bound": True}


def list_conversation_tasks(*, session_key: str, limit: int = 8) -> list[dict[str, object]]:
    if not 1 <= limit <= 50:
        raise ValueError("任务数量必须介于 1 到 50 之间")
    session_hash = _session_hash(session_key)
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT bindings.task_id, bindings.notified_at, bindings.created_at AS bound_at,
                   tasks.status, tasks.progress, tasks.content_item_id, tasks.updated_at,
                   content_items.title
            FROM openclaw_task_bindings AS bindings
            JOIN tasks ON tasks.id = bindings.task_id
            LEFT JOIN content_items ON content_items.id = tasks.content_item_id
            WHERE bindings.session_hash = ?
            ORDER BY bindings.updated_at DESC, bindings.task_id DESC
            LIMIT ?
            """,
            (session_hash, limit),
        ).fetchall()
    return [
        {
            "conversation_id": _conversation_id(session_hash),
            "task_id": row["task_id"],
            "status": row["status"],
            "progress": float(row["progress"]),
            "content_item_id": row["content_item_id"],
            "title": row["title"] or "未命名内容",
            "bound_at": row["bound_at"],
            "updated_at": row["updated_at"],
            "notified_at": row["notified_at"],
        }
        for row in rows
    ]


def claim_terminal_notification(*, session_key: str, task_id: str) -> dict[str, object]:
    """Atomically reserve the terminal reply so duplicate cron jobs stay quiet."""
    session_hash = _session_hash(session_key)
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT tasks.status, bindings.notified_at
            FROM openclaw_task_bindings AS bindings
            JOIN tasks ON tasks.id = bindings.task_id
            WHERE bindings.session_hash = ? AND bindings.task_id = ?
            """,
            (session_hash, task_id),
        ).fetchone()
        if row is None:
            raise LookupError("当前会话没有这个任务")
        status = str(row["status"])
        if status not in TERMINAL_TASK_STATUSES:
            return {"task_id": task_id, "status": status, "should_notify": False, "reason": "任务尚未结束"}
        if row["notified_at"]:
            return {"task_id": task_id, "status": status, "should_notify": False, "reason": "完成结果已通知"}
        now = utc_now_iso()
        updated = connection.execute(
            """
            UPDATE openclaw_task_bindings
            SET notified_at = ?, updated_at = ?
            WHERE session_hash = ? AND task_id = ? AND notified_at IS NULL
            """,
            (now, now, session_hash, task_id),
        )
        connection.commit()
    return {"task_id": task_id, "status": status, "should_notify": updated.rowcount == 1, "reason": ""}


def reserve_terminal_notifications(*, limit: int = 20) -> list[dict[str, object]]:
    """Reserve terminal task deliveries for the backend sender.

    Recipient routes never enter this database.  The sender resolves the
    matching live OpenClaw session only after a reservation has been made.
    """
    if not 1 <= limit <= 100:
        raise ValueError("通知任务数量必须介于 1 到 100 之间")
    initialize_database()
    now = utc_now_iso()
    stale_before = (datetime.now(timezone.utc) - timedelta(seconds=NOTIFICATION_RESERVATION_SECONDS)).isoformat()
    reserved: list[dict[str, object]] = []
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT bindings.session_hash, bindings.task_id, tasks.status,
                   tasks.result_json, tasks.error_message, tasks.request_json
            FROM openclaw_task_bindings AS bindings
            JOIN tasks ON tasks.id = bindings.task_id
            WHERE tasks.status IN ('succeeded', 'failed', 'cancelled')
              AND bindings.notified_at IS NULL
              AND (
                  bindings.notification_reserved_at IS NULL
                  OR bindings.notification_reserved_at < ?
              )
            ORDER BY tasks.updated_at ASC, bindings.task_id ASC
            LIMIT ?
            """,
            (stale_before, limit),
        ).fetchall()
        for row in rows:
            reservation_id = uuid.uuid4().hex
            updated = connection.execute(
                """
                UPDATE openclaw_task_bindings
                SET notification_reservation_id = ?, notification_reserved_at = ?,
                    notification_attempts = COALESCE(notification_attempts, 0) + 1,
                    updated_at = ?
                WHERE session_hash = ? AND task_id = ? AND notified_at IS NULL
                  AND (notification_reserved_at IS NULL OR notification_reserved_at < ?)
                """,
                (reservation_id, now, now, row["session_hash"], row["task_id"], stale_before),
            )
            if updated.rowcount == 1:
                reserved.append({
                    "reservation_id": reservation_id,
                    "session_hash": str(row["session_hash"]),
                    "task_id": str(row["task_id"]),
                    "status": str(row["status"]),
                    "result_json": str(row["result_json"] or ""),
                    "error_message": str(row["error_message"] or ""),
                    "request_json": str(row["request_json"] or ""),
                })
        connection.commit()
    return reserved


def complete_terminal_notification(*, session_hash: str, task_id: str, reservation_id: str) -> bool:
    initialize_database()
    with connect() as connection:
        updated = connection.execute(
            """
            UPDATE openclaw_task_bindings
            SET notified_at = ?, notification_reservation_id = NULL,
                notification_reserved_at = NULL, notification_last_error = NULL,
                updated_at = ?
            WHERE session_hash = ? AND task_id = ?
              AND notification_reservation_id = ? AND notified_at IS NULL
            """,
            (utc_now_iso(), utc_now_iso(), session_hash, task_id, reservation_id),
        )
        connection.commit()
    return updated.rowcount == 1


def release_terminal_notification(*, session_hash: str, task_id: str, reservation_id: str, error: str) -> bool:
    safe_error = error.strip().replace("\n", " ")[:300] or "微信投递失败"
    initialize_database()
    with connect() as connection:
        updated = connection.execute(
            """
            UPDATE openclaw_task_bindings
            SET notification_reservation_id = NULL, notification_reserved_at = NULL,
                notification_last_error = ?, updated_at = ?
            WHERE session_hash = ? AND task_id = ?
              AND notification_reservation_id = ? AND notified_at IS NULL
            """,
            (safe_error, utc_now_iso(), session_hash, task_id, reservation_id),
        )
        connection.commit()
    return updated.rowcount == 1


def record_conversation_turn(
    *,
    session_key: str,
    role: str,
    text: str,
    channel: str = "weixin",
    display_name: str | None = None,
    turn_id: str | None = None,
) -> dict[str, object]:
    if role not in {"user", "assistant"}:
        raise ValueError("对话角色必须是 user 或 assistant")
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("对话内容不能为空")
    if len(cleaned_text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"单条对话最多 {MAX_MESSAGE_CHARS} 个字符")
    if turn_id is not None and len(turn_id.strip()) > 160:
        raise ValueError("turn_id 过长")

    session_hash = _session_hash(session_key)
    initialize_database()
    with connect() as connection:
        settings = _settings(connection)
        _prune_messages(connection, settings)
        _touch_conversation(
            connection,
            session_hash=session_hash,
            channel=channel,
            display_name=display_name,
        )
        if not settings.transcript_mirror_enabled:
            connection.commit()
            return {
                "conversation_id": _conversation_id(session_hash),
                "stored": False,
                "reason": "完整对话镜像未开启",
            }
        connection.execute(
            """
            INSERT INTO openclaw_conversation_messages(id, session_hash, turn_id, role, text, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_hash, turn_id) DO NOTHING
            """,
            (uuid.uuid4().hex, session_hash, (turn_id or "").strip() or None, role, cleaned_text, utc_now_iso()),
        )
        connection.commit()
    return {"conversation_id": _conversation_id(session_hash), "stored": True, "reason": ""}


def list_conversations(*, limit: int = 50) -> list[dict[str, object]]:
    if not 1 <= limit <= 100:
        raise ValueError("会话数量必须介于 1 到 100 之间")
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT conversations.session_hash, conversations.channel, conversations.display_name,
                   conversations.first_seen_at, conversations.last_seen_at,
                   COUNT(DISTINCT bindings.id) AS task_count,
                   COUNT(DISTINCT CASE WHEN bindings.notified_at IS NULL THEN bindings.id END) AS pending_notification_count,
                   COUNT(messages.id) AS mirrored_message_count
            FROM openclaw_conversations AS conversations
            LEFT JOIN openclaw_task_bindings AS bindings ON bindings.session_hash = conversations.session_hash
            LEFT JOIN openclaw_conversation_messages AS messages ON messages.session_hash = conversations.session_hash
            GROUP BY conversations.session_hash
            ORDER BY conversations.last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "conversation_id": _conversation_id(row["session_hash"]),
            "channel": row["channel"],
            "display_name": row["display_name"],
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
            "task_count": int(row["task_count"] or 0),
            "pending_notification_count": int(row["pending_notification_count"] or 0),
            "mirrored_message_count": int(row["mirrored_message_count"] or 0),
        }
        for row in rows
    ]
