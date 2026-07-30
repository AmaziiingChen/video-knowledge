"""Persistent, single-file report jobs started from an OpenClaw conversation."""

from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from threading import Lock
from typing import Any

from services.database import connect, initialize_database
from services.openclaw_notifications import openclaw_notification_scheduler
from services.repository import ContentRepository, TaskRepository, TaskRecordRow
from services.wechat_reports import generate_report


REPORT_TASK_TYPE = "wechat_group_report"
_INTERRUPTED_MESSAGE = "KnowledgeHub 重启导致报告生成中断，请重新发起生成。"


def _task_dict(record: TaskRecordRow) -> dict[str, Any]:
    try:
        result = json.loads(record.result_json or "{}")
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict):
        result = {}
    return {
        "task_id": record.id,
        "task_type": record.task_type,
        "status": record.status,
        "progress": record.progress,
        "current_stage": record.current_stage,
        "error": record.error_message or None,
        "content_item_id": result.get("content_item_id"),
        "report_title": result.get("report_title"),
        "source_count": result.get("source_count"),
        "cited_source_count": result.get("cited_source_count"),
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


class OpenClawReportTaskManager:
    """Run one DeepSeek group report at a time without blocking the API server."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openclaw-report")
        self._futures: dict[str, Future[None]] = {}
        self._lock = Lock()
        self._stopped = False

    def create(
        self,
        *,
        group_id: str,
        report_type: str,
        window_start: datetime | None,
        window_end: datetime | None,
        include_history_context: bool,
        file_name: str | None,
    ) -> dict[str, Any]:
        initialize_database()
        request = {
            "group_id": group_id,
            "report_type": report_type,
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": window_end.isoformat() if window_end else None,
            "include_history_context": include_history_context,
            "file_name": file_name,
        }
        with connect() as connection:
            record = TaskRepository(connection).create_task(
                task_type=REPORT_TASK_TYPE,
                priority=80,
                request_json=json.dumps(request, ensure_ascii=False),
            )
            connection.commit()
        self._submit(record.id, request)
        return _task_dict(record)

    def get(self, task_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            record = TaskRepository(connection).get_task(task_id)
        if record.task_type != REPORT_TASK_TYPE:
            raise LookupError("不是 OpenClaw 分组报告任务")
        return _task_dict(record)

    def create_draft(
        self,
        *,
        task_id: str,
        title: str = "",
        digest: str = "",
        author: str = "",
    ) -> dict[str, Any]:
        task = self.get(task_id)
        if task["status"] != "succeeded":
            raise ValueError("报告尚未生成完成，暂不能创建草稿")
        content_item_id = str(task.get("content_item_id") or "")
        if not content_item_id:
            raise ValueError("报告任务缺少内容标识，暂不能创建草稿")
        from services.wechat_publishing import wechat_publishing_service

        return wechat_publishing_service.create_draft(
            content_item_id,
            title=title,
            digest=digest,
            author=author,
        )

    def recover_from_database(self) -> None:
        """Make interrupted work explicit rather than replaying billable model calls."""
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE task_type=? AND status IN ('queued', 'running')",
                (REPORT_TASK_TYPE,),
            ).fetchall()
            repository = TaskRepository(connection)
            for row in rows:
                repository.update_task_state(
                    str(row["id"]),
                    status="failed",
                    current_stage="interrupted",
                    error_type="interrupted",
                    error_message=_INTERRUPTED_MESSAGE,
                )
            connection.commit()
        if rows:
            openclaw_notification_scheduler.wake()

    def shutdown(self) -> None:
        with self._lock:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._stopped = True

    def _submit(self, task_id: str, request: dict[str, Any]) -> None:
        with self._lock:
            # TestClient and desktop development can both start another app
            # lifespan in the same Python process after shutdown.
            if self._stopped:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="openclaw-report")
                self._stopped = False
            self._futures[task_id] = self._executor.submit(self._run, task_id, request)

    def _run(self, task_id: str, request: dict[str, Any]) -> None:
        def update(*, status: str, stage: str, progress: float, error: str = "", result: dict[str, Any] | None = None) -> None:
            with connect() as connection:
                TaskRepository(connection).update_task_state(
                    task_id,
                    status=status,
                    current_stage=stage,
                    progress=progress,
                    error_type="report_generation" if error else None,
                    error_message=error or None,
                    result_json=json.dumps(result, ensure_ascii=False) if result is not None else None,
                )
                if result and result.get("content_item_id"):
                    connection.execute(
                        "UPDATE tasks SET content_item_id=? WHERE id=?",
                        (str(result["content_item_id"]), task_id),
                    )
                connection.commit()

        try:
            update(status="running", stage="starting", progress=2)

            def on_progress(event: dict[str, object]) -> None:
                update(
                    status="running",
                    stage=str(event.get("stage") or "generating"),
                    progress=float(event.get("progress") or 0),
                )

            result = generate_report(
                str(request["group_id"]),
                str(request["report_type"]),
                window_start=datetime.fromisoformat(str(request["window_start"])) if request.get("window_start") else None,
                window_end=datetime.fromisoformat(str(request["window_end"])) if request.get("window_end") else None,
                include_history_context=bool(request.get("include_history_context", True)),
                file_name=str(request["file_name"]) if request.get("file_name") else None,
                generation_trigger="openclaw_weixin",
                progress_callback=on_progress,
            )
            content_item_id = str(result.get("content_item_id") or "")
            report_title = ""
            if content_item_id:
                with connect() as connection:
                    report_title = ContentRepository(connection).get_content_item(content_item_id).title
            # The notification sender deliberately sends this Markdown directly
            # through the Weixin channel.  It must remain the generated report,
            # never an OpenClaw-authored retelling.
            terminal_result = {**result, "summary": str(result.get("markdown") or ""), "report_title": report_title}
            update(status="succeeded", stage="completed", progress=100, result=terminal_result)
            from services.completion_notifications import record_completion_notification
            record_completion_notification(
                event_key=f"report-ready:{task_id}", event_type="report_ready",
                title=report_title or "日报/周报已生成", body="报告已完成，可在区间报告中查看",
                content_item_id=content_item_id or None, target_view="reports",
            )
        except Exception as exc:
            update(status="failed", stage="failed", progress=100, error=str(exc) or exc.__class__.__name__)
            try:
                from services.completion_notifications import record_completion_notification
                record_completion_notification(
                    event_key=f"report-failed:{task_id}", event_type="report_failed",
                    title="日报/周报生成失败", body=str(exc)[:240] or "请在处理日志中查看原因", target_view="reports",
                )
            except Exception:
                pass
        finally:
            with self._lock:
                self._futures.pop(task_id, None)
            openclaw_notification_scheduler.wake()


openclaw_report_task_manager = OpenClawReportTaskManager()
