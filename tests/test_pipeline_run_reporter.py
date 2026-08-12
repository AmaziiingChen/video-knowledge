from datetime import datetime

from services.ai_call_logger import AICallRecord
from services.download_contracts import DownloadProgress
from services.pipeline_contracts import PipelineResponse
from services.pipeline_run_reporter import PipelineRunReporter


def make_ai_call(call_type: str = "") -> AICallRecord:
    return AICallRecord(
        call_type=call_type,
        provider="test",
        model="test-model",
        input_chars=10,
        output_chars=5,
        prompt_tokens=4,
        completion_tokens=3,
        total_tokens=7,
        prompt_cache_hit_tokens=2,
        prompt_cache_miss_tokens=2,
        estimated_cost=0.01,
        elapsed_seconds=0.5,
    )


def test_progress_is_monotonic_and_publishes_independent_snapshots() -> None:
    response = PipelineResponse(success=False)
    snapshots: list[PipelineResponse] = []
    reporter = PipelineRunReporter(response, snapshots.append)

    reporter.set_progress("parse", 20)
    reporter.set_progress("parse", 10)
    reporter.set_progress("unknown", 100)
    response.display_title = "later mutation"

    assert response.progress == {"parse": 20.0}
    assert response.overall_progress == 0.8
    assert len(snapshots) == 2
    assert snapshots[0].progress == {"parse": 20.0}
    assert snapshots[0].display_title is None


def test_download_transfer_keeps_truthful_bytes_separate_from_weighted_progress() -> None:
    response = PipelineResponse(success=False)
    snapshots: list[PipelineResponse] = []
    reporter = PipelineRunReporter(response, snapshots.append)

    reporter.set_download_transfer(DownloadProgress(
        phase="transfer",
        detail="downloading",
        received_bytes=50,
        total_bytes=100,
        bytes_per_second=25,
        percent=50,
    ))
    reporter.set_download_transfer(DownloadProgress(phase="merging", detail="merging"))

    assert response.progress["download"] == 50.0
    assert response.overall_progress == 11.0
    assert snapshots[0].download_transfer.percent == 50
    assert snapshots[1].download_transfer.phase == "merging"
    assert snapshots[1].download_transfer.percent is None


def test_logs_initialize_stage_progress_and_ai_calls_keep_usage_metadata() -> None:
    response = PipelineResponse(success=False)
    reporter = PipelineRunReporter(response, None)

    reporter.add_log("transcribe", "开始转写")
    reporter.remember_ai_call("summary")(make_ai_call())
    reporter.remember_ai_call("summary")(make_ai_call("article_summary_prepare"))

    assert response.progress["transcribe"] == 5.0
    assert datetime.fromisoformat(response.logs[0].created_at).tzinfo is not None
    assert response.ai_calls[0].call_type == "summary"
    assert response.ai_calls[0].total_tokens == 7
    assert response.ai_calls[1].call_type == "article_summary_prepare"
    assert response.logs[-1].message == "超长文章材料压缩完成（第 1 次）"


def test_streamed_summary_updates_state_while_coalescing_live_publication() -> None:
    response = PipelineResponse(success=False)
    snapshots: list[PipelineResponse] = []
    times = iter([1.0, 1.01, 1.04])
    reporter = PipelineRunReporter(response, snapshots.append, clock=lambda: next(times))

    reporter.publish_summary_delta("标题", "第")
    reporter.publish_summary_delta("", "第二")
    reporter.publish_summary_delta("", "第三次")

    assert response.display_title == "标题"
    assert response.summary == "第三次"
    assert [snapshot.summary for snapshot in snapshots] == ["第", "第三次"]


def test_streamed_reasoning_is_separate_bounded_and_coalesced() -> None:
    response = PipelineResponse(success=False)
    snapshots: list[PipelineResponse] = []
    times = iter([1.0, 1.01, 1.04])
    reporter = PipelineRunReporter(response, snapshots.append, clock=lambda: next(times))

    reporter.publish_reasoning_delta("核")
    reporter.publish_reasoning_delta("核对")
    reporter.publish_reasoning_delta("核对材料", truncated=True)

    assert response.summary is None
    assert response.reasoning_content == "核对材料"
    assert response.reasoning_truncated is True
    assert [snapshot.reasoning_content for snapshot in snapshots] == ["核", "核对材料"]


def test_completed_summary_suggestions_remain_separate_from_summary() -> None:
    response = PipelineResponse(success=False, summary="正文")
    reporter = PipelineRunReporter(response, None)

    reporter.publish_suggested_questions(["问题一？", "问题二？"])

    assert response.summary == "正文"
    assert response.suggested_questions == ["问题一？", "问题二？"]
