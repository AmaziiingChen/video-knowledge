from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

from services.database import utc_now_iso


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class ContentItemRecord:
    id: str
    content_type: str
    source_provider: str
    source_url: str | None
    canonical_source_id: str | None
    title: str
    cover_url: str | None
    duration_seconds: float | None
    status: str
    series_id: str | None
    library_folder_id: str | None
    sort_order: float
    created_at: str
    updated_at: str
    published_at: str | None = None
    source_name: str | None = None
    source_section: str | None = None


@dataclass(frozen=True)
class TaskRecordRow:
    id: str
    task_type: str
    status: str
    priority: int
    current_stage: str | None
    progress: float
    error_type: str | None
    error_message: str | None
    request_json: str | None
    result_json: str | None
    created_at: str
    updated_at: str


class ContentRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_content_item(
        self,
        *,
        source_provider: str,
        title: str = "",
        content_type: str = "video",
        source_url: str | None = None,
        canonical_source_id: str | None = None,
        cover_url: str | None = None,
        duration_seconds: float | None = None,
        status: str = "inbox",
        series_id: str | None = None,
        library_folder_id: str | None = None,
        library_visible: bool = True,
        sort_order: float = 0,
        published_at: str | None = None,
        source_name: str | None = None,
        source_section: str | None = None,
    ) -> ContentItemRecord:
        now = utc_now_iso()
        item_id = new_id()
        self.connection.execute(
            """
            INSERT INTO content_items (
                id, content_type, source_provider, source_url, canonical_source_id,
                title, cover_url, duration_seconds, status, series_id, library_folder_id, library_visible,
                sort_order, published_at, source_name, source_section, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_id,
                content_type,
                source_provider,
                source_url,
                canonical_source_id,
                title,
                cover_url,
                duration_seconds,
                status,
                series_id,
                library_folder_id,
                int(library_visible),
                sort_order,
                published_at,
                source_name,
                source_section,
                now,
                now,
            ),
        )
        return self.get_content_item(item_id)

    def get_content_item(self, item_id: str) -> ContentItemRecord:
        row = self.connection.execute(
            "SELECT * FROM content_items WHERE id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"content item not found: {item_id}")
        return _content_item_from_row(row)

    def update_content_type(self, item_id: str, content_type: str) -> ContentItemRecord:
        """Correct a legacy item when a provider's source contract changed."""
        self.connection.execute(
            "UPDATE content_items SET content_type=?, updated_at=? WHERE id=?",
            (content_type, utc_now_iso(), item_id),
        )
        return self.get_content_item(item_id)

    def update_source_url(self, item_id: str, source_url: str) -> ContentItemRecord:
        """Refresh an expiring provider URL without changing content identity."""
        self.connection.execute(
            "UPDATE content_items SET source_url=?, updated_at=? WHERE id=?",
            (source_url, utc_now_iso(), item_id),
        )
        return self.get_content_item(item_id)

    def update_canonical_source_id(self, item_id: str, canonical_source_id: str) -> ContentItemRecord:
        """Repair a legacy source identity while retaining the user's item."""
        self.connection.execute(
            "UPDATE content_items SET canonical_source_id=?, updated_at=? WHERE id=?",
            (canonical_source_id, utc_now_iso(), item_id),
        )
        return self.get_content_item(item_id)

    def find_by_source_url(self, *, source_provider: str, source_url: str) -> ContentItemRecord | None:
        row = self.connection.execute(
            "SELECT * FROM content_items WHERE source_provider = ? AND source_url = ? LIMIT 1",
            (source_provider, source_url),
        ).fetchone()
        return _content_item_from_row(row) if row else None

    def find_by_canonical_id(
        self,
        *,
        source_provider: str,
        canonical_source_id: str,
    ) -> ContentItemRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM content_items
            WHERE source_provider = ? AND canonical_source_id = ?
            """,
            (source_provider, canonical_source_id),
        ).fetchone()
        return _content_item_from_row(row) if row else None

    def list_content_items(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        published_after: str | None = None,
    ) -> list[ContentItemRecord]:
        where, params = self._library_content_where(status=status, published_after=published_after)
        rows = self.connection.execute(
            f"""
            SELECT content_items.*, {self._effective_published_at_sql()} AS effective_published_at
            FROM content_items
            WHERE {where}
            ORDER BY content_items.sort_order ASC,
                COALESCE(effective_published_at, content_items.created_at) DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return [_content_item_from_row(row) for row in rows]

    def count_content_items(
        self,
        *,
        status: str | None = None,
        published_after: str | None = None,
    ) -> int:
        where, params = self._library_content_where(status=status, published_after=published_after)
        row = self.connection.execute(
            f"SELECT COUNT(*) FROM content_items WHERE {where}",
            params,
        ).fetchone()
        return int(row[0] if row else 0)

    def list_content_items_by_ids(self, item_ids: list[str]) -> list[ContentItemRecord]:
        """Return visible library records in the caller's requested order."""
        ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if item_id))
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        rows = self.connection.execute(
            f"""
            SELECT content_items.*, {self._effective_published_at_sql()} AS effective_published_at
            FROM content_items
            WHERE content_items.id IN ({placeholders})
              AND content_items.deleted_at IS NULL
              AND content_items.library_visible = 1
            """,
            ids,
        ).fetchall()
        records = {str(row["id"]): _content_item_from_row(row) for row in rows}
        return [records[item_id] for item_id in ids if item_id in records]

    def list_folder_history_content_items(
        self,
        folder_id: str,
        *,
        published_before: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentItemRecord]:
        where, params = self._library_content_where(status=None, published_after=None)
        where = " AND ".join([
            where,
            "content_items.library_folder_id = ?",
            f"{self._effective_published_at_sql()} < ?",
        ])
        rows = self.connection.execute(
            f"""
            SELECT content_items.*, {self._effective_published_at_sql()} AS effective_published_at
            FROM content_items
            WHERE {where}
            ORDER BY content_items.sort_order ASC,
                COALESCE(effective_published_at, content_items.created_at) DESC
            LIMIT ? OFFSET ?
            """,
            [*params, folder_id, published_before, limit, offset],
        ).fetchall()
        return [_content_item_from_row(row) for row in rows]

    def list_folder_content_items(
        self,
        folder_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentItemRecord]:
        """Return one explicit folder's visible items without a date cutoff.

        The workbench uses this for lazy tree expansion.  Keeping the folder
        predicate in the repository makes it match the normal library list
        (including soft-deletion and ``library_visible`` semantics).
        """
        where, params = self._library_content_where(status=None, published_after=None)
        where = " AND ".join([where, "content_items.library_folder_id = ?"])
        rows = self.connection.execute(
            f"""
            SELECT content_items.*, {self._effective_published_at_sql()} AS effective_published_at
            FROM content_items
            WHERE {where}
            ORDER BY content_items.sort_order ASC,
                COALESCE(effective_published_at, content_items.created_at) DESC
            LIMIT ? OFFSET ?
            """,
            [*params, folder_id, limit, offset],
        ).fetchall()
        return [_content_item_from_row(row) for row in rows]

    def count_folder_content_items(self, folder_id: str) -> int:
        where, params = self._library_content_where(status=None, published_after=None)
        where = " AND ".join([where, "content_items.library_folder_id = ?"])
        row = self.connection.execute(
            f"SELECT COUNT(*) FROM content_items WHERE {where}",
            [*params, folder_id],
        ).fetchone()
        return int(row[0] if row else 0)

    def count_folder_history_content_items(self, folder_id: str, *, published_before: str) -> int:
        where, params = self._library_content_where(status=None, published_after=None)
        where = " AND ".join([
            where,
            "content_items.library_folder_id = ?",
            f"{self._effective_published_at_sql()} < ?",
        ])
        row = self.connection.execute(
            f"SELECT COUNT(*) FROM content_items WHERE {where}",
            [*params, folder_id, published_before],
        ).fetchone()
        return int(row[0] if row else 0)

    @staticmethod
    def _effective_published_at_sql() -> str:
        return """COALESCE(content_items.published_at, (
            SELECT published_at
            FROM wechat_subscription_items
            WHERE content_item_id = content_items.id
            ORDER BY published_at DESC, id DESC
            LIMIT 1
        ), content_items.created_at)"""

    def _library_content_where(
        self,
        *,
        status: str | None,
        published_after: str | None,
    ) -> tuple[str, list[object]]:
        clauses = ["content_items.deleted_at IS NULL", "content_items.library_visible = 1"]
        params: list[object] = []
        if status:
            clauses.append("content_items.status = ?")
            params.append(status)
        if published_after:
            clauses.append(f"{self._effective_published_at_sql()} >= ?")
            params.append(published_after)
        return " AND ".join(clauses), params

    def update_status(self, item_id: str, status: str) -> ContentItemRecord:
        self.connection.execute(
            """
            UPDATE content_items
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, utc_now_iso(), item_id),
        )
        return self.get_content_item(item_id)

    def update_source_metadata(
        self,
        item_id: str,
        *,
        title: str,
        published_at: str | None,
        source_name: str | None,
        source_section: str | None,
    ) -> ContentItemRecord:
        self.connection.execute(
            """
            UPDATE content_items
            SET title = COALESCE(NULLIF(?, ''), title),
                published_at = COALESCE(NULLIF(?, ''), published_at),
                source_name = COALESCE(NULLIF(?, ''), source_name),
                source_section = COALESCE(NULLIF(?, ''), source_section),
                updated_at = ?
            WHERE id = ?
            """,
            (title, published_at, source_name, source_section, utc_now_iso(), item_id),
        )
        return self.get_content_item(item_id)

    def update_content_item(
        self,
        item_id: str,
        *,
        title: str | None = None,
        library_folder_id: str | None = None,
        sort_order: float | None = None,
    ) -> ContentItemRecord:
        current = self.get_content_item(item_id)
        self.connection.execute(
            """
            UPDATE content_items
            SET title = ?,
                library_folder_id = ?,
                sort_order = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                current.title if title is None else title,
                library_folder_id,
                current.sort_order if sort_order is None else sort_order,
                utc_now_iso(),
                item_id,
            ),
        )
        return self.get_content_item(item_id)

    def delete_content_item(self, item_id: str) -> None:
        self.connection.execute("DELETE FROM content_items WHERE id = ?", (item_id,))


class TaskRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_task(
        self,
        *,
        task_type: str,
        task_id: str | None = None,
        content_item_id: str | None = None,
        series_id: str | None = None,
        parent_task_id: str | None = None,
        priority: int = 100,
        request_json: str | None = None,
    ) -> TaskRecordRow:
        now = utc_now_iso()
        final_task_id = task_id or new_id()
        self.connection.execute(
            """
            INSERT INTO tasks (
                id, task_type, parent_task_id, content_item_id, series_id, request_json, status,
                priority, progress, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, 0, ?, ?)
            """,
            (
                final_task_id,
                task_type,
                parent_task_id,
                content_item_id,
                series_id,
                request_json,
                priority,
                now,
                now,
            ),
        )
        return self.get_task(final_task_id)

    def get_task(self, task_id: str) -> TaskRecordRow:
        row = self.connection.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"task not found: {task_id}")
        return _task_from_row(row)

    def update_task_state(
        self,
        task_id: str,
        *,
        status: str,
        current_stage: str | None = None,
        progress: float | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        result_json: str | None = None,
    ) -> TaskRecordRow:
        current = self.get_task(task_id)
        self.connection.execute(
            """
            UPDATE tasks
            SET status = ?,
                current_stage = ?,
                progress = ?,
                error_type = ?,
                error_message = ?,
                result_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                current_stage,
                current.progress if progress is None else progress,
                error_type,
                error_message,
                current.result_json if result_json is None else result_json,
                utc_now_iso(),
                task_id,
            ),
        )
        return self.get_task(task_id)

    def update_task_priority(self, task_id: str, priority: int) -> TaskRecordRow:
        self.connection.execute(
            """
            UPDATE tasks
            SET priority = ?, updated_at = ?
            WHERE id = ?
            """,
            (priority, utc_now_iso(), task_id),
        )
        return self.get_task(task_id)

    def update_task_request(self, task_id: str, request_json: str) -> TaskRecordRow:
        self.connection.execute(
            """
            UPDATE tasks
            SET request_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (request_json, utc_now_iso(), task_id),
        )
        return self.get_task(task_id)

    def list_queued(self, *, limit: int = 20) -> list[TaskRecordRow]:
        rows = self.connection.execute(
            """
            SELECT * FROM tasks
            WHERE status = 'queued'
            ORDER BY priority ASC, created_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_task_from_row(row) for row in rows]

    def list_recent(self, *, limit: int = 50) -> list[TaskRecordRow]:
        rows = self.connection.execute(
            """
            SELECT * FROM tasks
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_task_from_row(row) for row in rows]


def _content_item_from_row(row: sqlite3.Row) -> ContentItemRecord:
    return ContentItemRecord(
        id=row["id"],
        content_type=row["content_type"],
        source_provider=row["source_provider"],
        source_url=row["source_url"],
        canonical_source_id=row["canonical_source_id"],
        title=row["title"],
        cover_url=row["cover_url"],
        duration_seconds=row["duration_seconds"],
        status=row["status"],
        series_id=row["series_id"],
        library_folder_id=row["library_folder_id"] if "library_folder_id" in row.keys() else None,
        sort_order=float(row["sort_order"] if "sort_order" in row.keys() else 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        published_at=(
            row["effective_published_at"]
            if "effective_published_at" in row.keys()
            else row["published_at"] if "published_at" in row.keys() else None
        ),
        source_name=row["source_name"] if "source_name" in row.keys() else None,
        source_section=row["source_section"] if "source_section" in row.keys() else None,
    )


def _task_from_row(row: sqlite3.Row) -> TaskRecordRow:
    return TaskRecordRow(
        id=row["id"],
        task_type=row["task_type"],
        status=row["status"],
        priority=int(row["priority"]),
        current_stage=row["current_stage"],
        progress=float(row["progress"]),
        error_type=row["error_type"],
        error_message=row["error_message"],
        request_json=row["request_json"],
        result_json=row["result_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
