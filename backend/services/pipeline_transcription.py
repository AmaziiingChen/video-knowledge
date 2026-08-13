"""Execute audio extraction and ASR for one pipeline media source."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from services.cache import write_cached_transcript, write_cached_transcript_segments
from services.pipeline_contracts import (
    PipelineCancelled,
    PipelineResponse,
    TextSourceInfo,
)
from services.pipeline_progress_rules import elapsed
from services.pipeline_run_reporter import PipelineRunReporter


class PipelineTranscriptionError(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


def transcribe_pipeline_media(
    video_path: Path,
    *,
    local_media_is_audio: bool,
    selected_model: str,
    asr_options: dict[str, Any],
    subtitle_fallback_reason: str,
    cache_dir: Path,
    response: PipelineResponse,
    reporter: PipelineRunReporter,
    check_cancel: Callable[[], None],
    provider_cancel_check: Callable[[], bool] | None,
    extract_audio: Callable[..., Any],
    transcribe: Callable[..., Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Return transcript state while preserving progress and cache contracts."""
    check_cancel()
    if local_media_is_audio:
        # The retained upload is already an ASR input. Rewriting a WAV onto
        # itself can destroy the user's original file.
        audio_path = video_path
        response.timings["extract_audio"] = 0.0
        reporter.complete_stage("extract_audio")
        reporter.add_log("extract_audio", "本地音频已就绪，跳过音频提取", "success", 0.0)
    else:
        audio_path = video_path.with_suffix(".wav")
        extract_started_at = time.perf_counter()
        reporter.add_log("extract_audio", "提取音频...")
        reporter.set_progress("extract_audio", 30)
        audio_result = extract_audio(
            video_path,
            audio_path,
            progress_callback=lambda percent: reporter.set_progress("extract_audio", 30 + percent * 0.7),
            cancel_check=provider_cancel_check,
        )
        response.timings["extract_audio"] = round(
            audio_result.elapsed_seconds or elapsed(extract_started_at),
            2,
        )
        if getattr(audio_result, "cancelled", False) or (
            provider_cancel_check and provider_cancel_check()
        ):
            raise PipelineCancelled()
        if not audio_result.success:
            error = audio_result.error or "音频提取失败"
            reporter.add_log("extract_audio", error, "error", response.timings["extract_audio"])
            raise PipelineTranscriptionError("extract_audio", error)
        reporter.complete_stage("extract_audio")
        reporter.add_log("extract_audio", "音频提取完成", "success", response.timings["extract_audio"])

    check_cancel()
    transcribe_started_at = time.perf_counter()
    reporter.add_log(
        "transcribe",
        f"开始语音识别（后端: {asr_options['backend']}，模型: {selected_model}，可能需要几分钟）...",
    )
    transcribe_result = transcribe(
        audio_path,
        selected_model,
        progress_callback=lambda percent: reporter.set_progress("transcribe", percent),
        backend=asr_options["backend"],
        beam_size=asr_options["beam_size"],
        vad_filter=asr_options["vad_filter"],
        fallback_enabled=asr_options["fallback_enabled"],
    )
    if not local_media_is_audio:
        audio_path.unlink(missing_ok=True)
    response.timings["transcribe"] = elapsed(transcribe_started_at)
    for key, value in transcribe_result.timings.items():
        response.timings[key] = round(value, 2)

    if not transcribe_result.success:
        error = transcribe_result.error or "转写失败"
        reporter.add_log("transcribe", error, "error", response.timings["transcribe"])
        raise PipelineTranscriptionError("transcribe", error)

    transcript = transcribe_result.transcript
    segments = getattr(transcribe_result, "segments", [])
    actual_backend = getattr(transcribe_result, "backend", "")
    response.asr_backend = actual_backend or response.asr_backend
    text_source_backend = "faster-whisper" if actual_backend in {"", "faster_whisper"} else actual_backend
    response.text_source = TextSourceInfo(
        kind="asr",
        source=text_source_backend,
        detail=f"Whisper {selected_model}",
        fallback_reason=subtitle_fallback_reason,
    )
    # Compact text survives even when the large downloaded media is ephemeral.
    write_cached_transcript(cache_dir, selected_model, transcript)
    write_cached_transcript_segments(cache_dir, selected_model, segments)
    return transcript, segments
