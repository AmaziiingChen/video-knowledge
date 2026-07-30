"""Persistent background jobs for WeChat draft creation.

The GitHub Pages deployment that precedes a draft can legitimately take longer
than one browser request.  Keep that work out of the request/response lifetime
and retain a durable status record that the renderer can poll.
"""

from __future__ import annotations

import json
import hashlib
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Any

from services.database import connect, initialize_database
from services.markdown_sync import get_markdown_state
from services.repository import TaskRecordRow, TaskRepository


WECHAT_DRAFT_TASK_TYPE = "wechat_draft_publish"
_INTERRUPTED_MESSAGE = "应用重启导致草稿任务中断，请重新存入草稿箱。"


def _request_dict(record: TaskRecordRow) -> dict[str, Any]:
    try:
        value = json.loads(record.request_json or "{}")
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _result_dict(record: TaskRecordRow) -> dict[str, Any]:
    try:
        value = json.loads(record.result_json or "{}")
    except json.JSONDecodeError:
        value = {}
    return value if isinstance(value, dict) else {}


def _task_dict(record: TaskRecordRow) -> dict[str, Any]:
    result = _result_dict(record)
    request = _request_dict(record)
    return {
        "task_id": record.id,
        "status": record.status,
        "progress": record.progress,
        "stage": record.current_stage or "queued",
        "error": record.error_message or "",
        "content_item_id": request.get("content_item_id") or "",
        "publication": result.get("publication") if isinstance(result.get("publication"), dict) else None,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class WeChatDraftTaskManager:
    """Serialize WeChat draft uploads and survive renderer disconnects."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wechat-draft")
        self._futures: dict[str, Future[None]] = {}
        self._lock = Lock()
        self._stopped = False

    def create(self, *, content_item_id: str, title: str, digest: str, author: str) -> dict[str, Any]:
        initialize_database()
        source_hash = hashlib.sha256(
            get_markdown_state(content_item_id).markdown.encode("utf-8")
        ).hexdigest()
        request = {
            "content_item_id": content_item_id,
            "title": title,
            "digest": digest,
            "author": author,
            "source_markdown_hash": source_hash,
        }
        with connect() as connection:
            # Reuse an in-flight job.  The dialog may be closed and reopened,
            # or a second click may arrive while GitHub Pages is still building.
            row = connection.execute(
                """SELECT * FROM tasks
                   WHERE task_type=? AND content_item_id=? AND status IN ('queued', 'running')
                   ORDER BY created_at DESC LIMIT 1""",
                (WECHAT_DRAFT_TASK_TYPE, content_item_id),
            ).fetchone()
            repository = TaskRepository(connection)
            if row is not None:
                return _task_dict(repository.get_task(str(row["id"])))

            publication_row = connection.execute(
                """SELECT * FROM wechat_publications
                   WHERE content_item_id=? AND source_markdown_hash=?
                     AND status IN ('draft_created', 'published')
                   ORDER BY created_at DESC LIMIT 1""",
                (content_item_id, source_hash),
            ).fetchone()
            task = repository.create_task(
                task_type=WECHAT_DRAFT_TASK_TYPE,
                content_item_id=content_item_id,
                priority=90,
                request_json=json.dumps(request, ensure_ascii=False),
            )
            if publication_row is not None:
                task = repository.update_task_state(
                    task.id,
                    status="succeeded",
                    current_stage="already_created",
                    progress=100,
                    result_json=json.dumps({"publication": dict(publication_row)}, ensure_ascii=False),
                )
            connection.commit()
        if publication_row is None:
            self._submit(task.id, request)
        return _task_dict(task)

    def get(self, task_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            record = TaskRepository(connection).get_task(task_id)
        if record.task_type != WECHAT_DRAFT_TASK_TYPE:
            raise LookupError("不是公众号草稿任务")
        return _task_dict(record)

    def latest_for_content(self, content_item_id: str) -> dict[str, Any] | None:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """SELECT id FROM tasks WHERE task_type=? AND content_item_id=?
                   ORDER BY created_at DESC LIMIT 1""",
                (WECHAT_DRAFT_TASK_TYPE, content_item_id),
            ).fetchone()
            if row is None:
                return None
            record = TaskRepository(connection).get_task(str(row["id"]))
        return _task_dict(record)

    def recover_from_database(self) -> None:
        """Do not replay a possibly completed remote WeChat request on restart."""
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE task_type=? AND status IN ('queued', 'running')",
                (WECHAT_DRAFT_TASK_TYPE,),
            ).fetchall()
            repository = TaskRepository(connection)
            for row in rows:
                repository.update_task_state(
                    str(row["id"]),
                    status="failed",
                    current_stage="interrupted",
                    progress=100,
                    error_type="interrupted",
                    error_message=_INTERRUPTED_MESSAGE,
                )
            connection.commit()

    def shutdown(self) -> None:
        with self._lock:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._stopped = True

    def _submit(self, task_id: str, request: dict[str, Any]) -> None:
        with self._lock:
            if self._stopped:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wechat-draft")
                self._stopped = False
            self._futures[task_id] = self._executor.submit(self._run, task_id, request)

    def _run(self, task_id: str, request: dict[str, Any]) -> None:
        def update(stage: str, progress: float) -> None:
            with connect() as connection:
                TaskRepository(connection).update_task_state(
                    task_id,
                    status="running",
                    current_stage=stage,
                    progress=progress,
                )
                connection.commit()

        try:
            update("starting", 2)
            from services.wechat_publishing import wechat_publishing_service

            publication = wechat_publishing_service.create_draft(
                str(request["content_item_id"]),
                title=str(request.get("title") or ""),
                digest=str(request.get("digest") or ""),
                author=str(request.get("author") or ""),
                progress_callback=update,
            )
            with connect() as connection:
                TaskRepository(connection).update_task_state(
                    task_id,
                    status="succeeded",
                    current_stage="completed",
                    progress=100,
                    result_json=json.dumps({"publication": publication}, ensure_ascii=False),
                )
                connection.commit()
        except Exception as exc:
            with connect() as connection:
                TaskRepository(connection).update_task_state(
                    task_id,
                    status="failed",
                    current_stage="failed",
                    progress=100,
                    error_type="wechat_draft",
                    error_message=str(exc) or exc.__class__.__name__,
                )
                connection.commit()
        finally:
            with self._lock:
                self._futures.pop(task_id, None)


wechat_draft_task_manager = WeChatDraftTaskManager()
