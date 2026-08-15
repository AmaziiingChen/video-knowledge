from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from threading import Lock
from typing import Literal
import json
import logging
import sqlite3
import time
import uuid

from services.database import (
    connect,
    ensure_database_initialized,
    is_database_busy_error,
    utc_now_iso,
)
from services.pipeline_runner import PipelineLog, PipelineRequest, PipelineResponse, classify_pipeline_error, run_pipeline_sync
from services.repository import ContentRepository, TaskRepository
from config import settings
from services.telemetry import record as record_telemetry, telemetry_stage_bucket
from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable, require_xiaohongshu_request, xiaohongshu_capabilities


TaskStatus = Literal["queued", "running", "paused", "succeeded", "failed", "cancelled"]
BACKGROUND_TASK_PRIORITY = 800
TASK_PERSISTENCE_ATTEMPTS = 3
TASK_PERSISTENCE_BUSY_TIMEOUT_MS = 1_000
# A coordinator is deliberately cheap: actual media downloads and ASR have
# their own single-resource gates.  Three coordinators let one downloaded
# video transcribe while the next one is fetched and a previous one awaits AI.
MEDIA_PIPELINE_COORDINATOR_WORKERS = 3
SUMMARY_STATE_PERSIST_INTERVAL_SECONDS = 0.35
logger = logging.getLogger(__name__)


class TaskPersistenceError(RuntimeError):
    """Raised when a task cannot be durably accepted into the local queue."""


@dataclass
class TaskRecord:
    task_id: str
    task_type: str = "process_video"
    content_item_id: str | None = None
    share_text: str | None = None
    local_video_path: str | None = None
    local_subtitle_path: str | None = None
    local_document_path: str | None = None
    local_document_kind: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    whisper_model: str | None = None
    asr_backend: str | None = None
    asr_model_strategy: str | None = None
    asr_short_video_model: str | None = None
    asr_long_video_model: str | None = None
    asr_beam_size: int | None = None
    asr_vad_filter: bool | None = None
    asr_fallback_enabled: bool | None = None
    ai_model: str | None = None
    use_cache: bool = True
    processing_mode: str = "full"
    download_video_preview: bool = False
    subtitle_only: bool = False
    manual_collection: bool = False
    cover_title: str | None = None
    cover_digest: str | None = None
    cover_visual_brief: dict | None = None
    source_sync_request: dict | None = None
    priority: int = 100
    execution_mode: Literal["foreground", "background"] = "foreground"
    status: TaskStatus = "queued"
    cancel_requested: bool = False
    persistence_error: str | None = None
    persistence_error_action: str | None = None
    result: PipelineResponse | None = None
    created_at: str = field(default_factory=lambda: _now_iso())
    updated_at: str = field(default_factory=lambda: _now_iso())
    future: Future | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_sync_identity(request: dict) -> tuple[str, str]:
    """Stable identity used only to coalesce active source-check tasks."""
    kind = str(request.get("kind") or "")
    for key in ("subscription_id", "source_id", "source_slug", "source_url"):
        value = str(request.get(key) or "")
        if value:
            return kind, value
    return kind, "bulk"


def _request_payload(record: TaskRecord) -> dict:
    return {
        "content_item_id": record.content_item_id,
        "share_text": record.share_text,
        "local_video_path": record.local_video_path,
        "local_subtitle_path": record.local_subtitle_path,
        "local_document_path": record.local_document_path,
        "local_document_kind": record.local_document_kind,
        "source_title": record.source_title,
        "source_url": record.source_url,
        "whisper_model": record.whisper_model,
        "asr_backend": record.asr_backend,
        "asr_model_strategy": record.asr_model_strategy,
        "asr_short_video_model": record.asr_short_video_model,
        "asr_long_video_model": record.asr_long_video_model,
        "asr_beam_size": record.asr_beam_size,
        "asr_vad_filter": record.asr_vad_filter,
        "asr_fallback_enabled": record.asr_fallback_enabled,
        "ai_model": record.ai_model,
        "use_cache": record.use_cache,
        "processing_mode": record.processing_mode,
        "download_video_preview": record.download_video_preview,
        "subtitle_only": record.subtitle_only,
        "manual_collection": record.manual_collection,
        "cover_title": record.cover_title,
        "cover_digest": record.cover_digest,
        "cover_visual_brief": record.cover_visual_brief,
        "source_sync_request": record.source_sync_request,
        "priority": record.priority,
        "execution_mode": record.execution_mode,
    }


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._lock = Lock()
        # These threads coordinate independent pipeline stages; they do not
        # mean three downloads or ASR runs. ``pipeline_runner`` and
        # ``transcriber`` serialize those resource-heavy operations globally.
        self._max_workers = max(
            1,
            min(int(settings.pipeline_concurrency), MEDIA_PIPELINE_COORDINATOR_WORKERS),
        )
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="video-pipeline")
        self._active_task_ids: set[str] = set()
        self._subscribers: dict[str, set[Queue[TaskRecord]]] = {}

    def create(
        self,
        request: PipelineRequest,
        *,
        task_type: str = "process_video",
    ) -> TaskRecord:
        require_xiaohongshu_request(request)
        task_id = str(uuid.uuid4())[:8]
        record = self._record_from_request(task_id, request, task_type=task_type)
        # A task is not accepted until its queue record is durable. Otherwise
        # the API can report success for work that disappears on restart.
        self._persist_create(record)
        with self._lock:
            self._tasks[task_id] = record
        record_telemetry(
            "task_enqueued",
            {"processing_mode": record.processing_mode if record.processing_mode in {"full", "transcript"} else "other"},
        )
        self._schedule_next()
        return self.get(task_id)

    def subscribe_updates(self, task_id: str):
        """Yield live task snapshots for a single local client connection.

        A bounded queue keeps a slow UI from retaining every intermediate LLM
        token.  It always preserves the newest snapshot, which is the only
        state a renderer needs to continue a cumulative text stream.
        """
        subscriber: Queue[TaskRecord] = Queue(maxsize=1)
        with self._lock:
            current = self._tasks.get(task_id)
            if current is None:
                return
            self._subscribers.setdefault(task_id, set()).add(subscriber)
            initial = self._copy_record(current)
        if initial is not None:
            subscriber.put_nowait(initial)
        try:
            while True:
                try:
                    yield subscriber.get(timeout=15)
                except Empty:
                    # The router turns this into an SSE comment to keep a
                    # quiet local proxy from closing a healthy stream.
                    yield None
        finally:
            with self._lock:
                listeners = self._subscribers.get(task_id)
                if listeners is not None:
                    listeners.discard(subscriber)
                    if not listeners:
                        self._subscribers.pop(task_id, None)

    def _broadcast_update(self, record: TaskRecord | None) -> None:
        if record is None:
            return
        with self._lock:
            listeners = tuple(self._subscribers.get(record.task_id, ()))
        for subscriber in listeners:
            snapshot = self._copy_record(record)
            if snapshot is None:
                continue
            try:
                subscriber.put_nowait(snapshot)
            except Full:
                try:
                    subscriber.get_nowait()
                except Empty:
                    pass
                try:
                    subscriber.put_nowait(snapshot)
                except Full:
                    # Another delivery won the small race; its snapshot is
                    # newer than the one we were about to enqueue.
                    continue

    def create_source_sync(
        self,
        source_sync_request: dict,
        *,
        source_title: str,
        source_url: str | None = None,
        execution_mode: Literal["foreground", "background"] = "foreground",
    ) -> TaskRecord:
        """Persist a provider sync in the canonical task queue before work starts."""
        # Schedulers run more often than a slow provider call can finish. Do
        # not accumulate identical checks before the provider advances its
        # next_sync_at after the active task completes.
        identity = _source_sync_identity(source_sync_request)
        with self._lock:
            for active in self._tasks.values():
                if (
                    active.task_type == "source_sync"
                    and active.status in {"queued", "running", "paused"}
                    and _source_sync_identity(active.source_sync_request or {}) == identity
                ):
                    return self._copy_record(active)
        request = PipelineRequest(
            source_title=source_title,
            source_url=source_url,
            processing_mode="source_sync",
            execution_mode=execution_mode,
            priority=80 if execution_mode == "foreground" else BACKGROUND_TASK_PRIORITY,
            source_sync_request=dict(source_sync_request),
        )
        return self.create(request, task_type="source_sync")

    def recover_from_database(self) -> None:
        try:
            ensure_database_initialized()
            with connect() as connection:
                rows = TaskRepository(connection).list_recent(limit=200)
        except Exception:
            return

        recoverable: list[TaskRecord] = []
        read_only_task_ids: set[str] = set()
        xiaohongshu_features = xiaohongshu_capabilities()
        for row in reversed(rows):
            if row.task_type not in {"process_video", "generate_wechat_cover", "import_document", "source_sync"}:
                continue
            record = self._record_from_row(row)
            if record is None:
                continue
            try:
                require_xiaohongshu_request(PipelineRequest.model_validate(_request_payload(record)), capabilities=xiaohongshu_features)
            except XiaohongshuCollectorUnavailable:
                if record.status in {"queued", "running", "paused"}:
                    # Leave active work untouched; terminal history loads read-only.
                    continue
                read_only_task_ids.add(record.task_id)
            recoverable.append(record)

        recovered_state_changes: list[TaskRecord] = []
        with self._lock:
            for record in recoverable:
                if record.task_id in self._tasks:
                    continue
                if record.status == "running":
                    if record.task_type == "process_video" and record.execution_mode == "background":
                        # Automatic collection work is idempotent and already
                        # has a durable content identity.  Resume it after an
                        # app restart instead of leaving a personal favorite
                        # waiting for the user to click download manually.
                        record.status = "queued"
                        record.result = self._queued_result(record)
                    else:
                        record.status = "failed"
                        record.result = self._interrupted_result(record)
                    record.updated_at = _now_iso()
                    recovered_state_changes.append(self._copy_record(record))
                self._tasks[record.task_id] = record

        for record in recovered_state_changes:
            self._persist_state(record)
        # A shutdown can happen after the task state was persisted as running
        # but before its content row was reconciled.  Repair terminal media
        # tasks on startup, while preserving an item a user has already moved
        # out of the processing state.
        for record in self.list():
            if record.status in {"succeeded", "failed", "cancelled"} and record.task_id not in read_only_task_ids:
                self._persist_content_status(record, only_if_processing=True)
        self._schedule_next()

    def retry(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                record = self._load_record_for_control(task_id)
                if record:
                    self._tasks[task_id] = record
            if not record:
                return None
            if record.status not in {"failed", "cancelled"}:
                return self._copy_record(record)
            require_xiaohongshu_request(PipelineRequest.model_validate(_request_payload(record)))
            record.status = "queued"
            record.cancel_requested = False
            if record.share_text and not record.local_video_path and not record.local_subtitle_path:
                record.use_cache = True
            record.updated_at = _now_iso()
            record.result = self._queued_result(record)
            snapshot = self._copy_record(record)
        self._persist_state(snapshot)
        self._persist_request(snapshot)
        self._persist_content_status(snapshot)
        record_telemetry("task_control_used", {"action": "retry"})
        self._schedule_next()
        return self.get(task_id)

    def pause(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                record = self._load_record_for_control(task_id)
                if record:
                    self._tasks[task_id] = record
            if not record:
                return None
            if record.status != "queued":
                return self._copy_record(record)
            require_xiaohongshu_request(PipelineRequest.model_validate(_request_payload(record)))
            record.status = "paused"
            record.updated_at = _now_iso()
            if record.future:
                record.future.cancel()
            record.result = self._paused_result(record)
            snapshot = self._copy_record(record)
        self._persist_state(snapshot)
        record_telemetry("task_control_used", {"action": "pause"})
        with self._lock:
            if task_id in self._active_task_ids and record.future and record.future.cancel():
                self._active_task_ids.discard(task_id)
        self._schedule_next()
        return self.get(task_id)

    def resume(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                record = self._load_record_for_control(task_id)
                if record:
                    self._tasks[task_id] = record
            if not record:
                return None
            if record.status != "paused":
                return self._copy_record(record)
            require_xiaohongshu_request(PipelineRequest.model_validate(_request_payload(record)))
            record.status = "queued"
            record.cancel_requested = False
            record.updated_at = _now_iso()
            record.result = self._queued_result(record)
            snapshot = self._copy_record(record)
        self._persist_state(snapshot)
        record_telemetry("task_control_used", {"action": "resume"})
        self._schedule_next()
        return self.get(task_id)

    def reprioritize(self, task_id: str, priority: int) -> TaskRecord | None:
        priority = max(0, min(1000, int(priority)))
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                record = self._load_record_for_control(task_id)
                if record:
                    self._tasks[task_id] = record
            if not record:
                return None
            if record.status not in {"queued", "paused"}:
                return self._copy_record(record)
            require_xiaohongshu_request(PipelineRequest.model_validate(_request_payload(record)))
            record.priority = priority
            record.updated_at = _now_iso()
            snapshot = self._copy_record(record)
        self._persist_priority(snapshot)
        self._schedule_next()
        return self.get(task_id)

    def _load_record_for_control(self, task_id: str) -> TaskRecord | None:
        record = self._load_record_from_database(task_id)
        if record is not None and record.status in {"queued", "running", "paused"}:
            require_xiaohongshu_request(PipelineRequest.model_validate(_request_payload(record)))
        return record

    def list(self) -> list[TaskRecord]:
        with self._lock:
            return sorted(
                (self._copy_record(record) for record in self._tasks.values()),
                key=lambda item: item.created_at,
                reverse=True,
            )

    def get(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._tasks.get(task_id)
            return self._copy_record(record) if record else None

    def cancel(self, task_id: str) -> TaskRecord | None:
        should_schedule = False
        should_persist = False
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return None
            if record.status in {"queued", "running", "paused"}:
                record.cancel_requested = True
                record.updated_at = _now_iso()
                if record.status in {"queued", "paused"} and record.future:
                    record.future.cancel()
                # Cancellation is a user-facing terminal decision.  Blocking
                # provider calls may need a moment to unwind, but the queue and
                # UI must not remain stuck in "正在取消" until their timeout.
                record.status = "cancelled"
                should_schedule = True
                record.result = PipelineResponse(
                    success=False,
                    task_id=task_id,
                    error="任务已取消",
                    error_info=classify_pipeline_error("cancelled", "任务已取消"),
                    step="cancelled",
                )
                should_persist = True
            snapshot = self._copy_record(record)
        if should_persist:
            self._persist_state(snapshot)
            self._broadcast_update(snapshot)
            if should_schedule:
                self._persist_content_status(snapshot)
        if should_schedule:
            with self._lock:
                if task_id in self._active_task_ids and record.future and record.future.cancel():
                    self._active_task_ids.discard(task_id)
            self._schedule_next()
        if snapshot and snapshot.cancel_requested:
            record_telemetry("task_control_used", {"action": "cancel"})
        return snapshot

    def cancel_active(self) -> list[TaskRecord]:
        """Request cancellation for every currently active local task.

        Use the same cancellation path as the one-task action so queued work
        becomes terminal immediately and running work receives its cooperative
        cancellation signal.  The task list is snapshotted first because each
        individual cancellation may reschedule the executor.
        """
        with self._lock:
            task_ids = [
                record.task_id
                for record in self._tasks.values()
                if record.status in {"queued", "running", "paused"}
            ]
        cancelled: list[TaskRecord] = []
        for task_id in task_ids:
            record = self.cancel(task_id)
            if record and record.cancel_requested:
                cancelled.append(record)
        return cancelled

    def _schedule_next(self) -> None:
        while True:
            task_id: str | None = None
            with self._lock:
                stale_ids = {
                    active_id
                    for active_id in self._active_task_ids
                    if not (
                        (active := self._tasks.get(active_id))
                        and active.future
                        and not active.future.done()
                    )
                }
                self._active_task_ids.difference_update(stale_ids)
                if len(self._active_task_ids) >= self._max_workers:
                    return

                active_ids = set(self._active_task_ids)
                candidates = [
                    record
                    for record in self._tasks.values()
                    if record.status == "queued" and record.task_id not in active_ids
                ]
                if not candidates:
                    return
                next_record = min(candidates, key=lambda item: (item.priority, item.created_at, item.task_id))
                task_id = next_record.task_id
                self._active_task_ids.add(task_id)
                next_record.updated_at = _now_iso()
            try:
                future = self._executor.submit(self._run, task_id)
            except RuntimeError:
                with self._lock:
                    self._active_task_ids.discard(task_id)
                return
            with self._lock:
                record = self._tasks.get(task_id)
                if record and task_id in self._active_task_ids:
                    record.future = future
            future.add_done_callback(lambda done_future, task_id=task_id: self._on_future_done(task_id, done_future))

    def _on_future_done(self, task_id: str, future: Future) -> None:
        stale_snapshot = None
        future_error = future.exception() if not future.cancelled() else None
        with self._lock:
            record = self._tasks.get(task_id)
            should_mark_failed = (
                record
                and record.future is future
                and not future.cancelled()
                and (
                    record.status == "queued"
                    or (future_error is not None and record.status == "running")
                )
            )
            if should_mark_failed:
                record.status = "failed"
                record.result = self._executor_exited_result(record, cause=future_error)
                record.updated_at = _now_iso()
                stale_snapshot = self._copy_record(record)
            self._active_task_ids.discard(task_id)
        if stale_snapshot:
            self._persist_state(stale_snapshot)
            self._persist_content_status(stale_snapshot)
        self._schedule_next()

    def _run(self, task_id: str) -> None:
        try:
            last_telemetry_stage: str | None = None
            with self._lock:
                record = self._tasks.get(task_id)
                if not record:
                    return
                if record.status == "paused":
                    return
                if record.cancel_requested:
                    record.status = "cancelled"
                    record.updated_at = _now_iso()
                    cancelled_snapshot = self._copy_record(record)
                else:
                    record.status = "running"
                    record.updated_at = _now_iso()
                    running_snapshot = self._copy_record(record)
                    cancelled_snapshot = None
            if cancelled_snapshot:
                self._persist_state(cancelled_snapshot)
                self._broadcast_update(cancelled_snapshot)
                return
            self._persist_state(running_snapshot)
            self._broadcast_update(running_snapshot)
            last_state_persist_at = time.monotonic()

            def on_update(result: PipelineResponse) -> None:
                nonlocal last_telemetry_stage, last_state_persist_at
                snapshot = None
                with self._lock:
                    current = self._tasks.get(task_id)
                    if not current or current.status == "cancelled":
                        return
                    current.result = result
                    # A WeChat article gets its library item while the body snapshot is
                    # being captured, before the later AI-summary stage finishes. Keep
                    # that identifier on the task's live record so the client can open
                    # the cached article preview immediately.
                    current.content_item_id = result.content_item_id or current.content_item_id
                    current.updated_at = _now_iso()
                    snapshot = self._copy_record(current)
                is_streamed_summary = result.step == "summarize" and bool(result.summary or result.reasoning_content)
                now = time.monotonic()
                if not is_streamed_summary or now - last_state_persist_at >= SUMMARY_STATE_PERSIST_INTERVAL_SECONDS:
                    self._persist_state(snapshot)
                    last_state_persist_at = now
                # The desktop detail view subscribes to this in-memory snapshot
                # directly. Persisting every LLM token would make SQLite the
                # bottleneck, while the final terminal state is still durable.
                self._broadcast_update(snapshot)
                stage = str(result.step or "")
                stage_bucket = telemetry_stage_bucket(stage)
                if stage and stage_bucket != last_telemetry_stage:
                    last_telemetry_stage = stage_bucket
                    record_telemetry("pipeline_stage_reached", {"stage": stage_bucket})

            def cancel_check() -> bool:
                with self._lock:
                    current = self._tasks.get(task_id)
                    return bool(current and current.cancel_requested)

            if record.task_type == "generate_wechat_cover":
                from services.wechat_publishing import wechat_publishing_service

                result = wechat_publishing_service.run_cover_task(
                    content_item_id=str(record.content_item_id or ""),
                    title=str(record.cover_title or ""),
                    digest=str(record.cover_digest or ""),
                    visual_brief=record.cover_visual_brief,
                    task_id=task_id,
                    on_update=on_update,
                    cancel_check=cancel_check,
                )
            elif record.task_type == "import_document":
                from services.local_file_imports import run_document_import

                result = run_document_import(
                    content_item_id=str(record.content_item_id or ""),
                    original_path=str(record.local_document_path or ""),
                    task_id=task_id,
                    on_update=on_update,
                    cancel_check=cancel_check,
                )
            elif record.task_type == "source_sync":
                from services.source_sync_tasks import run_source_sync_task

                def on_source_sync_update(stage: str, progress: float, message: str) -> None:
                    on_update(
                        PipelineResponse(
                            success=False,
                            task_id=task_id,
                            display_title=record.source_title,
                            step=stage,
                            overall_progress=progress,
                            logs=[PipelineLog(step=stage, message=message)],
                        )
                    )

                source_result = run_source_sync_task(
                    dict(record.source_sync_request or {}),
                    on_progress=on_source_sync_update,
                    cancel_check=cancel_check,
                )
                result = PipelineResponse(
                    success=True,
                    task_id=task_id,
                    display_title=record.source_title,
                    overall_progress=100.0,
                    step="completed",
                    source_sync_result=source_result,
                )
            else:
                result = run_pipeline_sync(
                    record.share_text,
                    whisper_model=record.whisper_model,
                    asr_backend=record.asr_backend,
                    asr_model_strategy=record.asr_model_strategy,
                    asr_short_video_model=record.asr_short_video_model,
                    asr_long_video_model=record.asr_long_video_model,
                    asr_beam_size=record.asr_beam_size,
                    asr_vad_filter=record.asr_vad_filter,
                    asr_fallback_enabled=record.asr_fallback_enabled,
                    ai_model=record.ai_model,
                    use_cache=record.use_cache,
                    processing_mode=record.processing_mode,
                    download_video_preview=record.download_video_preview,
                    subtitle_only=record.subtitle_only,
                    manual_collection=record.manual_collection,
                    task_id=task_id,
                    on_update=on_update,
                    cancel_check=cancel_check,
                    content_item_id=record.content_item_id,
                    local_video_path=record.local_video_path,
                    local_subtitle_path=record.local_subtitle_path,
                    source_title=record.source_title,
                    source_url=record.source_url,
                )

            with self._lock:
                current = self._tasks.get(task_id)
                if not current:
                    return
                current.result = result
                current.content_item_id = result.content_item_id or current.content_item_id
                if current.cancel_requested or result.step == "cancelled":
                    current.status = "cancelled"
                elif result.success:
                    current.status = "succeeded"
                else:
                    current.status = "failed"
                current.updated_at = _now_iso()
                final_snapshot = self._copy_record(current)
            self._persist_state(final_snapshot)
            self._persist_content_status(final_snapshot)
            self._broadcast_update(final_snapshot)
            if final_snapshot.status == "succeeded" and final_snapshot.content_item_id:
                try:
                    from services.completion_notifications import record_content_ready, record_manual_media_ready
                    record_content_ready(final_snapshot.content_item_id, after_analysis=True)
                    if final_snapshot.task_type == "process_video" and (
                        final_snapshot.manual_collection or final_snapshot.source_url or final_snapshot.local_video_path
                    ):
                        record_manual_media_ready(
                            final_snapshot.content_item_id,
                            str(result.display_title or final_snapshot.source_title or "媒体资料"),
                        )
                except Exception:
                    logger.info("Could not record task completion notification", exc_info=True)
            if final_snapshot.status in {"succeeded", "failed"}:
                if final_snapshot.status == "failed":
                    record_telemetry("pipeline_stage_failed", {"stage": telemetry_stage_bucket(result.step)})
                record_telemetry(
                    "task_finished",
                    {"result": final_snapshot.status, "stage": telemetry_stage_bucket(result.step)},
                )
            self._wake_openclaw_terminal_delivery()
        except Exception as exc:
            with self._lock:
                current = self._tasks.get(task_id)
                if current is None:
                    return
                if current.cancel_requested:
                    current.status = "cancelled"
                    current.result = PipelineResponse(
                        success=False,
                        task_id=task_id,
                        error="任务已取消",
                        error_info=classify_pipeline_error("cancelled", "任务已取消"),
                        step="cancelled",
                    )
                else:
                    current.status = "failed"
                    current.result = self._executor_exited_result(current, cause=exc)
                current.updated_at = _now_iso()
                failed_snapshot = self._copy_record(current)
            self._persist_state(failed_snapshot)
            self._persist_content_status(failed_snapshot)
            self._broadcast_update(failed_snapshot)
            record_telemetry("task_finished", {"result": "failed", "stage": "executor"})
            self._wake_openclaw_terminal_delivery()
        finally:
            with self._lock:
                self._active_task_ids.discard(task_id)
            self._schedule_next()

    def _copy_record(self, record: TaskRecord | None) -> TaskRecord | None:
        if record is None:
            return None
        return TaskRecord(
            task_id=record.task_id,
            task_type=record.task_type,
            content_item_id=record.content_item_id,
            share_text=record.share_text,
            local_video_path=record.local_video_path,
            local_subtitle_path=record.local_subtitle_path,
            local_document_path=record.local_document_path,
            local_document_kind=record.local_document_kind,
            source_title=record.source_title,
            source_url=record.source_url,
            whisper_model=record.whisper_model,
            asr_backend=record.asr_backend,
            asr_model_strategy=record.asr_model_strategy,
            asr_short_video_model=record.asr_short_video_model,
            asr_long_video_model=record.asr_long_video_model,
            asr_beam_size=record.asr_beam_size,
            asr_vad_filter=record.asr_vad_filter,
            asr_fallback_enabled=record.asr_fallback_enabled,
            ai_model=record.ai_model,
            use_cache=record.use_cache,
            processing_mode=record.processing_mode,
            download_video_preview=record.download_video_preview,
            subtitle_only=record.subtitle_only,
            manual_collection=record.manual_collection,
            cover_title=record.cover_title,
            cover_digest=record.cover_digest,
            cover_visual_brief=dict(record.cover_visual_brief) if record.cover_visual_brief else None,
            source_sync_request=dict(record.source_sync_request) if record.source_sync_request else None,
            priority=record.priority,
            execution_mode=record.execution_mode,
            status=record.status,
            cancel_requested=record.cancel_requested,
            persistence_error=record.persistence_error,
            persistence_error_action=record.persistence_error_action,
            result=record.result.model_copy(deep=True) if record.result else None,
            created_at=record.created_at,
            updated_at=record.updated_at,
            future=record.future,
        )

    def _record_from_request(
        self,
        task_id: str,
        request: PipelineRequest,
        *,
        task_type: str = "process_video",
        status: TaskStatus = "queued",
        created_at: str | None = None,
        updated_at: str | None = None,
        result: PipelineResponse | None = None,
        priority: int | None = None,
    ) -> TaskRecord:
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            content_item_id=request.content_item_id,
            share_text=request.share_text,
            local_video_path=request.local_video_path,
            local_subtitle_path=request.local_subtitle_path,
            local_document_path=getattr(request, "local_document_path", None),
            local_document_kind=getattr(request, "local_document_kind", None),
            source_title=request.source_title,
            source_url=request.source_url,
            whisper_model=request.whisper_model,
            asr_backend=getattr(request, "asr_backend", None),
            asr_model_strategy=getattr(request, "asr_model_strategy", None),
            asr_short_video_model=getattr(request, "asr_short_video_model", None),
            asr_long_video_model=getattr(request, "asr_long_video_model", None),
            asr_beam_size=getattr(request, "asr_beam_size", None),
            asr_vad_filter=getattr(request, "asr_vad_filter", None),
            asr_fallback_enabled=getattr(request, "asr_fallback_enabled", None),
            ai_model=getattr(request, "ai_model", None),
            use_cache=request.use_cache,
            processing_mode=getattr(request, "processing_mode", "full"),
            download_video_preview=bool(getattr(request, "download_video_preview", False)),
            subtitle_only=bool(getattr(request, "subtitle_only", False)),
            manual_collection=bool(getattr(request, "manual_collection", False)),
            cover_title=getattr(request, "cover_title", None),
            cover_digest=getattr(request, "cover_digest", None),
            cover_visual_brief=getattr(request, "cover_visual_brief", None),
            source_sync_request=getattr(request, "source_sync_request", None),
            priority=self._effective_priority(request, priority),
            execution_mode=getattr(request, "execution_mode", "foreground"),
            status=status,
            result=result,
            created_at=created_at or _now_iso(),
            updated_at=updated_at or _now_iso(),
        )
        if record.result is None:
            record.result = self._queued_result(record)
        return record

    @staticmethod
    def _effective_priority(request: PipelineRequest, priority: int | None) -> int:
        """Keep automatic work behind an ordinary user-requested task.

        A running worker is intentionally not force-killed: downloads, OCR and
        model calls do not all have safe interruption points.  The next queue
        selection, however, always prefers foreground work.
        """
        requested = priority if priority is not None else getattr(request, "priority", 100)
        if getattr(request, "execution_mode", "foreground") == "background":
            return max(BACKGROUND_TASK_PRIORITY, int(requested))
        return int(requested)

    def _record_from_row(self, row) -> TaskRecord | None:
        if not row.request_json:
            return None
        try:
            request = PipelineRequest.model_validate(json.loads(row.request_json))
        except Exception:
            return None
        result = None
        if row.result_json:
            try:
                result = PipelineResponse.model_validate_json(row.result_json)
            except Exception:
                result = None
        return self._record_from_request(
            row.id,
            request,
            task_type=str(row.task_type or "process_video"),
            status=row.status if row.status in {"queued", "running", "paused", "succeeded", "failed", "cancelled"} else "failed",
            created_at=row.created_at,
            updated_at=row.updated_at,
            result=result,
            priority=row.priority,
        )

    def _load_record_from_database(self, task_id: str) -> TaskRecord | None:
        try:
            ensure_database_initialized()
            with connect() as connection:
                row = TaskRepository(connection).get_task(task_id)
        except Exception:
            return None
        return self._record_from_row(row)

    def _queued_result(self, record: TaskRecord) -> PipelineResponse:
        return PipelineResponse(
            success=False,
            task_id=record.task_id,
            url=record.source_url,
            platform="subtitle" if record.local_subtitle_path else "local" if record.local_video_path else None,
            video_path=record.local_video_path,
            whisper_model=record.whisper_model,
            asr_backend=record.asr_backend,
            step="queued",
        )

    def _paused_result(self, record: TaskRecord) -> PipelineResponse:
        result = record.result.model_copy(deep=True) if record.result else self._queued_result(record)
        result.success = False
        result.task_id = record.task_id
        result.error = None
        result.step = "paused"
        return result

    def _interrupted_result(self, record: TaskRecord) -> PipelineResponse:
        result = record.result.model_copy(deep=True) if record.result else self._queued_result(record)
        result.success = False
        result.task_id = record.task_id
        result.error = "后端重启，任务中断，可重试"
        result.error_info = classify_pipeline_error("executor", result.error)
        result.step = "interrupted"
        return result

    def _executor_exited_result(self, record: TaskRecord, *, cause: BaseException | None = None) -> PipelineResponse:
        result = record.result.model_copy(deep=True) if record.result else self._queued_result(record)
        result.success = False
        result.task_id = record.task_id
        if cause is None:
            result.error = "任务执行器提前退出，可重试"
        else:
            result.error = f"任务执行异常：{cause}"
        result.error_info = classify_pipeline_error("executor", result.error)
        result.step = "executor"
        return result

    def _persist_create(self, record: TaskRecord) -> bool:
        return self._persist_operation(
            record,
            action="create",
            required=True,
            writer=lambda connection: TaskRepository(connection).create_task(
                task_id=record.task_id,
                task_type=record.task_type,
                content_item_id=record.content_item_id,
                priority=record.priority,
                request_json=json.dumps(
                    _request_payload(record),
                    ensure_ascii=False,
                ),
            ),
        )

    def _persist_priority(self, record: TaskRecord | None) -> bool:
        if record is None:
            return True
        return self._persist_operation(
            record,
            action="priority",
            writer=lambda connection: TaskRepository(connection).update_task_priority(
                record.task_id,
                record.priority,
            ),
        )

    def _persist_request(self, record: TaskRecord | None) -> bool:
        if record is None:
            return True
        return self._persist_operation(
            record,
            action="request",
            writer=lambda connection: TaskRepository(connection).update_task_request(
                record.task_id,
                json.dumps(
                    _request_payload(record),
                    ensure_ascii=False,
                ),
            ),
        )

    def _persist_state(self, record: TaskRecord | None) -> bool:
        if record is None:
            return True
        result = record.result
        return self._persist_operation(
            record,
            action="state",
            writer=lambda connection: TaskRepository(connection).update_task_state(
                record.task_id,
                status=record.status,
                current_stage=result.step if result else None,
                progress=result.overall_progress if result else 0.0,
                error_type=result.step if result and result.error else None,
                error_message=result.error if result else None,
                result_json=result.model_dump_json() if result else None,
            ),
        )

    def _persist_content_status(self, record: TaskRecord | None, *, only_if_processing: bool = False) -> bool:
        if record is None or not record.content_item_id or record.task_type not in {"process_video", "import_document"}:
            return True
        if record.status == "succeeded":
            status = "to_read"
        elif record.status == "failed":
            status = "failed"
        elif record.status == "cancelled":
            status = "inbox"
        else:
            status = "processing"
        def write_status(connection: sqlite3.Connection) -> None:
            if only_if_processing:
                connection.execute(
                    """
                    UPDATE content_items
                    SET status = ?, updated_at = ?
                    WHERE id = ? AND status = 'processing'
                    """,
                    (status, utc_now_iso(), record.content_item_id),
                )
            else:
                ContentRepository(connection).update_status(record.content_item_id, status)

        return self._persist_operation(
            record,
            action="content_status",
            writer=write_status,
        )

    def _persist_operation(
        self,
        record: TaskRecord,
        *,
        action: str,
        writer: Callable[[sqlite3.Connection], object],
        required: bool = False,
    ) -> bool:
        for attempt in range(1, TASK_PERSISTENCE_ATTEMPTS + 1):
            try:
                ensure_database_initialized()
                with connect(busy_timeout_ms=TASK_PERSISTENCE_BUSY_TIMEOUT_MS) as connection:
                    writer(connection)
                    connection.commit()
                self._set_persistence_error(record, action=action, message=None)
                return True
            except Exception as exc:
                retryable = (
                    isinstance(exc, sqlite3.OperationalError)
                    and is_database_busy_error(exc)
                    and attempt < TASK_PERSISTENCE_ATTEMPTS
                )
                if retryable:
                    time.sleep(0.1 * attempt)
                    continue
                logger.exception(
                    "Unable to persist task %s operation %s",
                    record.task_id,
                    action,
                )
                message = "任务暂时无法写入本地数据库"
                self._set_persistence_error(record, action=action, message=message)
                if required:
                    raise TaskPersistenceError(message) from exc
                return False
        return False

    def _set_persistence_error(
        self,
        record: TaskRecord,
        *,
        action: str,
        message: str | None,
    ) -> None:
        if message is not None:
            record.persistence_error = message
            record.persistence_error_action = action
        elif record.persistence_error_action == action:
            record.persistence_error = None
            record.persistence_error_action = None
        with self._lock:
            current = self._tasks.get(record.task_id)
            if current is None:
                return
            if message is not None:
                current.persistence_error = message
                current.persistence_error_action = action
            elif current.persistence_error_action == action:
                current.persistence_error = None
                current.persistence_error_action = None

    @staticmethod
    def _wake_openclaw_terminal_delivery() -> None:
        """Prompt a direct Weixin delivery scan without coupling task execution to it."""
        try:
            from services.openclaw_notifications import openclaw_notification_scheduler
            openclaw_notification_scheduler.wake()
        except Exception:
            # The scheduler's periodic scan remains the durable fallback.
            return


task_manager = TaskManager()
