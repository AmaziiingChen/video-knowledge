"""Own mutable progress, log and live-update projection for one pipeline run."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime

from services.ai_call_logger import AICallRecord
from services.download_contracts import DownloadProgress
from services.pipeline_contracts import (
    MAX_REASONING_CONTENT_CHARS,
    AICallInfo,
    DownloadTransferInfo,
    PipelineLog,
    PipelineResponse,
)
from services.pipeline_progress_rules import clamp_percent, elapsed

PROGRESS_WEIGHTS = {
    "parse": 4,
    "info": 4,
    "download": 22,
    "extract_audio": 10,
    "transcribe": 36,
    "summarize": 20,
    "save": 4,
}
# One opened assistant panel is cheap enough to repaint at roughly 40 fps.
# Every published snapshot still contains all text returned so far.
SUMMARY_PUBLISH_INTERVAL_SECONDS = 0.025


class PipelineRunReporter:
    def __init__(
        self,
        response: PipelineResponse,
        on_update: Callable[[PipelineResponse], None] | None,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.response = response
        self.on_update = on_update
        self.clock = clock
        self.last_summary_publish_at = 0.0
        self.last_reasoning_publish_at = 0.0

    def publish(self) -> None:
        if self.on_update:
            self.on_update(self.response.model_copy(deep=True))

    def update_overall_progress(self) -> None:
        total = sum(
            (self.response.progress.get(step, 0.0) / 100.0) * weight
            for step, weight in PROGRESS_WEIGHTS.items()
        )
        self.response.overall_progress = clamp_percent(total)

    def set_progress(self, step: str, percent: float, publish_update: bool = True) -> None:
        if step not in PROGRESS_WEIGHTS:
            return
        current = self.response.progress.get(step, 0.0)
        self.response.progress[step] = max(current, clamp_percent(percent))
        self.response.step = step
        self.update_overall_progress()
        if publish_update:
            self.publish()

    def set_download_transfer(self, progress: DownloadProgress) -> None:
        """Keep provider byte telemetry distinct from weighted run progress."""
        self.response.step = "download"
        self.response.download_transfer = DownloadTransferInfo(
            phase=progress.phase,
            detail=progress.detail,
            received_bytes=progress.received_bytes,
            total_bytes=progress.total_bytes,
            bytes_per_second=progress.bytes_per_second,
            percent=progress.percent,
        )
        if progress.percent is not None:
            current = self.response.progress.get("download", 0.0)
            self.response.progress["download"] = max(current, clamp_percent(progress.percent))
            self.update_overall_progress()
        self.publish()

    def complete_stage(self, step: str) -> None:
        self.set_progress(step, 100.0, publish_update=False)

    def add_log(
        self,
        step: str,
        message: str,
        level: str = "info",
        elapsed_seconds: float | None = None,
    ) -> None:
        self.response.step = step
        if step in PROGRESS_WEIGHTS and self.response.progress.get(step, 0.0) == 0:
            self.set_progress(step, 5.0, publish_update=False)
        self.response.logs.append(
            PipelineLog(
                step=step,
                message=message,
                level=level,
                elapsed_seconds=elapsed_seconds,
                created_at=datetime.now().astimezone().isoformat(),
            )
        )
        self.publish()

    def mark_stage(self, step: str, message: str, start: float, level: str = "success") -> None:
        elapsed_seconds = elapsed(start)
        self.response.timings[step] = elapsed_seconds
        self.complete_stage(step)
        self.add_log(step, message, level, elapsed_seconds)

    def set_many_complete(self, steps: list[str]) -> None:
        for step in steps:
            self.complete_stage(step)

    def remember_ai_call(self, fallback_call_type: str) -> Callable[[AICallRecord], None]:
        def append_call(record: AICallRecord) -> None:
            call_type = record.call_type or fallback_call_type
            self.response.ai_calls.append(
                AICallInfo(
                    call_type=call_type,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    total_tokens=record.total_tokens,
                    prompt_cache_hit_tokens=record.prompt_cache_hit_tokens,
                    prompt_cache_miss_tokens=record.prompt_cache_miss_tokens,
                    estimated_cost=record.estimated_cost,
                    elapsed_seconds=record.elapsed_seconds,
                )
            )
            if call_type == "article_summary_prepare":
                count = sum(item.call_type == "article_summary_prepare" for item in self.response.ai_calls)
                self.add_log(
                    "summarize",
                    f"超长文章材料压缩完成（第 {count} 次）",
                    "success",
                    record.elapsed_seconds,
                )

        return append_call

    def publish_summary_delta(self, title: str, partial_summary: str) -> None:
        self.response.display_title = title or self.response.display_title
        self.response.summary = partial_summary
        now = self.clock()
        if now - self.last_summary_publish_at < SUMMARY_PUBLISH_INTERVAL_SECONDS:
            return
        self.last_summary_publish_at = now
        self.publish()

    def publish_reasoning_delta(self, partial_reasoning: str, truncated: bool = False) -> None:
        self.response.reasoning_content = str(partial_reasoning or "")[:MAX_REASONING_CONTENT_CHARS]
        self.response.reasoning_truncated = bool(
            truncated or len(str(partial_reasoning or "")) > MAX_REASONING_CONTENT_CHARS
        )
        now = self.clock()
        if now - self.last_reasoning_publish_at < SUMMARY_PUBLISH_INTERVAL_SECONDS:
            return
        self.last_reasoning_publish_at = now
        self.publish()

    def publish_suggested_questions(self, questions: list[str]) -> None:
        self.response.suggested_questions = list(questions[:3])
