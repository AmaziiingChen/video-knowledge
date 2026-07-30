from services.pipeline_runner import PipelineRequest
from services.task_manager import BACKGROUND_TASK_PRIORITY, TaskManager, _request_payload


def test_background_pipeline_task_is_persisted_and_deprioritized():
    manager = TaskManager()
    try:
        background = manager._record_from_request(
            "background-task",
            PipelineRequest(share_text="https://example.com/background", execution_mode="background"),
        )
        foreground = manager._record_from_request(
            "foreground-task",
            PipelineRequest(share_text="https://example.com/foreground"),
        )

        assert background.execution_mode == "background"
        assert background.priority == BACKGROUND_TASK_PRIORITY
        assert foreground.execution_mode == "foreground"
        assert foreground.priority < background.priority
        assert _request_payload(background)["execution_mode"] == "background"
    finally:
        manager._executor.shutdown(wait=True, cancel_futures=True)
