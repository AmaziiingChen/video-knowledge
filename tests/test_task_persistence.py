from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from presentation.task_responses import to_task_response
from services.pipeline_runner import (
    AICallInfo,
    PipelineErrorInfo,
    PipelineLog,
    PipelineRequest,
    PipelineResponse,
    TextSourceInfo,
)
from services.task_manager import (
    TASK_PERSISTENCE_ATTEMPTS,
    TaskManager,
    TaskPersistenceError,
    TaskRecord,
)
from config import settings


def test_task_create_failure_never_leaves_an_in_memory_ghost():
    manager = TaskManager()
    try:
        with (
            patch.object(
                manager,
                "_persist_create",
                side_effect=TaskPersistenceError("queue unavailable"),
            ),
            patch.object(manager, "_schedule_next") as schedule,
        ):
            with pytest.raises(TaskPersistenceError):
                manager.create(PipelineRequest(share_text="https://example.com/video"))

        assert manager.list() == []
        schedule.assert_not_called()
    finally:
        manager._executor.shutdown(wait=True, cancel_futures=True)


def test_source_sync_task_is_persisted_and_exposes_its_provider_result():
    old_data_dir = settings.data_dir
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings.data_dir = Path(temp_dir)
            manager = TaskManager()
            try:
                with patch(
                    "services.source_sync_tasks.run_source_sync_task",
                    side_effect=lambda request, on_progress, cancel_check: (
                        on_progress("discovering", 45, "正在读取来源") or {"created": 3, "kind": request["kind"]}
                    ),
                ):
                    task = manager.create_source_sync(
                        {"kind": "rss_saved", "source_id": "rss-1"},
                        source_title="RSS 更新",
                    )
                    assert task.future is not None
                    task.future.result(timeout=3)

                completed = manager.get(task.task_id)
                assert completed is not None
                assert completed.status == "succeeded"
                assert completed.result is not None
                assert completed.result.source_sync_result == {"created": 3, "kind": "rss_saved"}
            finally:
                manager._executor.shutdown(wait=True, cancel_futures=True)
    finally:
        settings.data_dir = old_data_dir


def test_completed_summary_reasoning_survives_task_manager_restart():
    old_data_dir = settings.data_dir
    first = None
    recovered = None
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings.data_dir = Path(temp_dir)
            first = TaskManager()
            record = first._record_from_request(
                "reasoning-restart",
                PipelineRequest(share_text="https://example.com/video"),
            )
            first._persist_create(record)
            record.status = "succeeded"
            record.result = PipelineResponse(
                success=True,
                summary="可见摘要",
                reasoning_content="独立思考",
                reasoning_truncated=False,
            )
            assert first._persist_state(record) is True

            recovered = TaskManager()
            recovered.recover_from_database()
            restored = recovered.get(record.task_id)

            assert restored is not None
            assert restored.status == "succeeded"
            assert restored.result is not None
            assert restored.result.summary == "可见摘要"
            assert restored.result.reasoning_content == "独立思考"
            assert restored.result.reasoning_truncated is False
    finally:
        if first is not None:
            first._executor.shutdown(wait=True, cancel_futures=True)
        if recovered is not None:
            recovered._executor.shutdown(wait=True, cancel_futures=True)
        settings.data_dir = old_data_dir


def test_legacy_task_result_without_reasoning_fields_remains_compatible():
    result = PipelineResponse.model_validate_json('{"success":true,"summary":"旧摘要"}')

    assert result.summary == "旧摘要"
    assert result.reasoning_content == ""
    assert result.reasoning_truncated is False


def test_task_state_persistence_retries_busy_database_and_exposes_failure():
    manager = TaskManager()
    try:
        record = manager._record_from_request(
            "persist-state",
            PipelineRequest(share_text="https://example.com/video"),
        )
        manager._persist_create(record)
        with manager._lock:
            manager._tasks[record.task_id] = record

        with (
            patch(
                "services.task_manager.connect",
                side_effect=sqlite3.OperationalError("database is locked"),
            ) as mocked_connect,
            patch("services.task_manager.time.sleep"),
        ):
            assert manager._persist_state(record) is False

        assert mocked_connect.call_count == TASK_PERSISTENCE_ATTEMPTS
        assert manager.get(record.task_id).persistence_error == "任务暂时无法写入本地数据库"
        response = to_task_response(manager.get(record.task_id))
        assert response.status == "queued"
        assert response.persistence_error == "任务暂时无法写入本地数据库"
        assert response.error == "任务暂时无法写入本地数据库"

        assert manager._persist_state(manager.get(record.task_id)) is True
        assert manager.get(record.task_id).persistence_error is None
    finally:
        manager._executor.shutdown(wait=True, cancel_futures=True)


def test_task_cancel_persists_after_releasing_manager_lock():
    manager = TaskManager()
    try:
        record = manager._record_from_request(
            "cancel-outside-lock",
            PipelineRequest(share_text="https://example.com/video"),
        )
        with manager._lock:
            manager._tasks[record.task_id] = record

        lock_was_available = []

        def persist_without_manager_lock(_record):
            acquired = manager._lock.acquire(blocking=False)
            lock_was_available.append(acquired)
            if acquired:
                manager._lock.release()
            return True

        with (
            patch.object(manager, "_persist_state", side_effect=persist_without_manager_lock),
            patch.object(manager, "_schedule_next"),
        ):
            cancelled = manager.cancel(record.task_id)

        assert cancelled.status == "cancelled"
        assert lock_was_available == [True]
    finally:
        manager._executor.shutdown(wait=True, cancel_futures=True)


def test_task_telemetry_reports_reached_buckets_and_proven_failures_without_inventing_stage_results():
    manager = TaskManager()
    events = []
    record = manager._record_from_request(
        "telemetry-task",
        PipelineRequest(share_text="https://example.com/article"),
    )
    with manager._lock:
        manager._tasks[record.task_id] = record

    def run_pipeline(*args, on_update, **kwargs):
        on_update(PipelineResponse(success=False, step="parse"))
        on_update(PipelineResponse(success=False, step="info"))
        on_update(PipelineResponse(success=False, step="summarize"))
        return PipelineResponse(
            success=False,
            step="summarize",
            error="provider unavailable",
            timings={"download": 0.0, "transcribe": 0.0, "summarize": 1.0},
        )

    try:
        with (
            patch("services.task_manager.run_pipeline_sync", side_effect=run_pipeline),
            patch("services.task_manager.record_telemetry", side_effect=lambda name, properties: events.append((name, properties))),
            patch.object(manager, "_persist_state", return_value=True),
            patch.object(manager, "_persist_content_status"),
            patch.object(manager, "_broadcast_update"),
            patch.object(manager, "_schedule_next"),
            patch.object(manager, "_wake_openclaw_terminal_delivery"),
        ):
            manager._run(record.task_id)

        assert events == [
            ("pipeline_stage_reached", {"stage": "prepare"}),
            ("pipeline_stage_reached", {"stage": "summary"}),
            ("pipeline_stage_failed", {"stage": "summary"}),
            ("task_finished", {"result": "failed", "stage": "summary"}),
        ]
    finally:
        manager._executor.shutdown(wait=True, cancel_futures=True)


def test_task_persistence_failure_is_returned_as_service_unavailable():
    with patch(
        "routers.tasks.task_manager.create",
        side_effect=TaskPersistenceError("queue unavailable"),
    ):
        response = TestClient(app).post(
            "/api/tasks",
            json={"share_text": "https://example.com/video"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "本地任务队列暂时不可写，请稍后重试"


def test_task_list_returns_compact_summaries_and_detail_endpoint_keeps_logs():
    record = TaskRecord(
        task_id="compact-task",
        status="failed",
        created_at="2026-07-28T07:00:00+00:00",
        updated_at="2026-07-28T08:00:00+00:00",
        result=PipelineResponse(
            success=False,
            transcript="长转写",
            summary="长摘要",
            reasoning_content="独立思考",
            reasoning_truncated=True,
            text_source=TextSourceInfo(kind="subtitle", source="provider"),
            ai_calls=[AICallInfo(call_type="summary", prompt_tokens=12)],
            cache_hits=["transcript"],
            logs=[PipelineLog(step="summarize", message="失败详情")],
            timings={"total": 12.5},
            progress={"summarize": 80},
            overall_progress=80,
            error="模型请求失败",
            error_info=PipelineErrorInfo(
                stage="summarize",
                category="provider",
                message="服务暂不可用",
            ),
            step="summarize",
        ),
    )
    client = TestClient(app)

    with (
        patch("routers.tasks.task_manager.list", return_value=[record]),
        patch("routers.tasks.task_manager.get", return_value=record),
    ):
        summary = client.get("/api/tasks").json()[0]
        detail = client.get("/api/tasks/compact-task").json()

    assert summary["details_included"] is False
    assert summary["transcript"] is None
    assert summary["summary"] is None
    assert summary["reasoning_content"] == ""
    assert summary["reasoning_length"] == 4
    assert summary["reasoning_truncated"] is True
    assert summary["text_source"] is None
    assert summary["ai_calls"] == []
    assert summary["cache_hits"] == []
    assert summary["logs"] == []
    assert summary["timings"] == {}
    assert summary["error_info"] is None
    assert summary["progress"] == {"summarize": 80.0}
    assert summary["error"] == "模型请求失败"

    assert detail["details_included"] is True
    assert detail["transcript"] == "长转写"
    assert detail["reasoning_content"] == "独立思考"
    assert detail["logs"][0]["message"] == "失败详情"
    assert detail["ai_calls"][0]["prompt_tokens"] == 12
    assert detail["error_info"]["message"] == "服务暂不可用"


def test_task_list_filters_deltas_but_keeps_active_tasks_and_exact_ids():
    records = [
        TaskRecord(
            task_id="old-terminal",
            status="succeeded",
            created_at="2026-07-28T06:00:00+00:00",
            updated_at="2026-07-28T06:30:00+00:00",
        ),
        TaskRecord(
            task_id="old-active",
            status="running",
            created_at="2026-07-28T06:00:00+00:00",
            updated_at="2026-07-28T06:30:00+00:00",
        ),
        TaskRecord(
            task_id="new-terminal",
            status="failed",
            created_at="2026-07-28T08:00:00+00:00",
            updated_at="2026-07-28T08:30:00+00:00",
        ),
    ]
    client = TestClient(app)

    with patch("routers.tasks.task_manager.list", return_value=records):
        delta = client.get(
            "/api/tasks",
            params={"updated_after": "2026-07-28T08:00:00+00:00"},
        ).json()
        exact = client.get(
            "/api/tasks",
            params={"task_ids": "old-terminal,new-terminal"},
        ).json()

    assert {task["task_id"] for task in delta} == {"old-active", "new-terminal"}
    assert {task["task_id"] for task in exact} == {"old-terminal", "new-terminal"}
