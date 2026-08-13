import pytest

from services.pipeline_contracts import (
    PipelineRequest,
    PipelineResponse,
    classify_pipeline_error,
)
from services.pipeline_runner import PipelineRequest as RunnerPipelineRequest
from services.pipeline_runner import (
    classify_pipeline_error as runner_classify_pipeline_error,
)


def test_pipeline_contracts_keep_error_taxonomy_and_runner_compatibility():
    assert RunnerPipelineRequest is PipelineRequest
    assert runner_classify_pipeline_error is classify_pipeline_error
    assert classify_pipeline_error("config", "缺少设置").model_dump() == {
        "stage": "config",
        "category": "configuration",
        "retryable": False,
        "retry_scope": "none",
        "message": "缺少设置",
    }
    first = PipelineResponse(success=True)
    second = PipelineResponse(success=True)
    first.logs.append({"step": "save", "message": "完成"})
    assert second.logs == []


@pytest.mark.parametrize(
    ("stage", "category", "retry_scope"),
    [
        ("download", "network_or_download", "download"),
        ("extract_audio", "media_processing", "audio"),
        ("transcribe", "asr", "transcribe"),
        ("summarize", "llm", "summarize"),
        ("save", "filesystem", "save"),
        ("cancelled", "cancelled", "full"),
        ("executor", "queue_executor", "full"),
        ("new-stage", "unknown", "full"),
    ],
)
def test_pipeline_error_taxonomy_preserves_every_retryable_stage(
    stage, category, retry_scope
):
    actual = classify_pipeline_error(stage, "失败")

    assert actual.category == category
    assert actual.retryable is True
    assert actual.retry_scope == retry_scope
