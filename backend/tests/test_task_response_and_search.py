import inspect
from types import SimpleNamespace

from routers import search as search_router
from routers import tasks as tasks_router
from services.pipeline_runner import PipelineResponse
from services.task_manager import TaskRecord


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

    queue_response = tasks_router._to_response(record, include_heavy_payload=False)
    detail_response = tasks_router._to_response(record)

    assert queue_response.transcript is None
    assert queue_response.summary is None
    assert detail_response.transcript == "很长的转写内容"
    assert detail_response.summary == "很长的摘要内容"


def test_search_route_runs_in_fastapi_worker_pool(monkeypatch):
    monkeypatch.setattr(
        search_router,
        "search_documents",
        lambda _query, *, limit: [SimpleNamespace(
            content_key="item-1",
            title="测试",
            summary_snippet="摘要",
            transcript_snippet="正文",
        )],
    )

    assert not inspect.iscoroutinefunction(search_router.search_content)
    response = search_router.search_content("测试", limit=20)
    assert response[0].content_key == "item-1"
