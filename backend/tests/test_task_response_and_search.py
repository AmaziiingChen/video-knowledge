import asyncio
import inspect
from types import SimpleNamespace

from presentation.task_responses import to_task_response
from routers import search as search_router
from routers import tasks as tasks_router
from services.pipeline_runner import PipelineResponse
from services.task_manager import TaskManager, TaskRecord


def test_task_queue_response_omits_historical_heavy_payloads():
    record = TaskRecord(
        task_id="queue-task",
        status="succeeded",
        result=PipelineResponse(
            success=True,
            task_id="queue-task",
            transcript="很长的转写内容",
            summary="很长的摘要内容",
        ),
    )

    queue_response = to_task_response(record, include_heavy_payload=False)
    detail_response = to_task_response(record)

    assert queue_response.transcript is None
    assert queue_response.summary is None
    assert queue_response.summary_length == len("很长的摘要内容")
    assert detail_response.transcript == "很长的转写内容"
    assert detail_response.summary == "很长的摘要内容"


def test_cancel_active_tasks_endpoint_returns_each_requested_cancellation(monkeypatch):
    records = [
        TaskRecord(task_id="queued-task", status="cancelled", cancel_requested=True),
        TaskRecord(task_id="running-task", status="running", cancel_requested=True),
    ]
    monkeypatch.setattr(tasks_router.task_manager, "cancel_active", lambda: records)

    response = asyncio.run(tasks_router.cancel_active_tasks())

    assert response.cancelled_count == 2
    assert [task.task_id for task in response.tasks] == ["queued-task", "running-task"]


def test_task_manager_publishes_newest_live_snapshot_without_waiting_for_persistence():
    manager = TaskManager()
    updates = None
    try:
        with manager._lock:
            manager._tasks["stream-task"] = TaskRecord(
                task_id="stream-task",
                status="running",
                result=PipelineResponse(
                    success=False,
                    task_id="stream-task",
                    step="summarize",
                    summary="第一个片段",
                ),
            )

        updates = manager.subscribe_updates("stream-task")
        initial = next(updates)
        assert initial.result.summary == "第一个片段"
        assert manager._max_workers == 3

        with manager._lock:
            manager._tasks["stream-task"].result.summary = "第一个片段，第二个片段"
            snapshot = manager._copy_record(manager._tasks["stream-task"])
        manager._broadcast_update(snapshot)

        latest = next(updates)
        assert latest.result.summary == "第一个片段，第二个片段"
    finally:
        if updates is not None:
            updates.close()
        manager._executor.shutdown(wait=True, cancel_futures=True)


def test_search_route_runs_in_fastapi_worker_pool(monkeypatch):
    monkeypatch.setattr(
        search_router,
        "search_documents",
        lambda _query, *, limit, scope: [SimpleNamespace(
            content_key="item-1",
            title="测试",
            summary_snippet="摘要",
            transcript_snippet="正文",
        )],
    )

    assert not inspect.iscoroutinefunction(search_router.search_content)
    response = search_router.search_content("测试", limit=20, scope="source")
    assert response[0].content_key == "item-1"
