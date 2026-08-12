"""Stable transport contracts and error taxonomy for the processing pipeline."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

MAX_REASONING_CONTENT_CHARS = 32_768


class PipelineRequest(BaseModel):
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
    cover_visual_brief: dict[str, Any] | None = None
    priority: int = 100
    execution_mode: Literal["foreground", "background"] = "foreground"
    source_sync_request: dict[str, Any] | None = None


class PipelineLog(BaseModel):
    step: str
    message: str
    level: str = "info"
    elapsed_seconds: float | None = None
    created_at: str | None = None


class TextSourceInfo(BaseModel):
    kind: str
    source: str
    cached: bool = False
    detail: str | None = None
    fallback_reason: str | None = None


class AICallInfo(BaseModel):
    call_type: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    estimated_cost: float | None = None
    elapsed_seconds: float | None = None


class PipelineErrorInfo(BaseModel):
    stage: str
    category: str
    retryable: bool = True
    retry_scope: str = "full"
    message: str


class DownloadTransferInfo(BaseModel):
    """Live transfer telemetry, distinct from weighted pipeline progress."""

    phase: str
    detail: str
    received_bytes: int | None = None
    total_bytes: int | None = None
    bytes_per_second: float | None = None
    percent: float | None = None


class PipelineResponse(BaseModel):
    success: bool
    task_id: str | None = None
    content_item_id: str | None = None
    url: str | None = None
    platform: str | None = None
    display_title: str | None = None
    video_path: str | None = None
    transcript: str | None = None
    summary: str | None = None
    reasoning_content: str = Field(default="", max_length=MAX_REASONING_CONTENT_CHARS)
    reasoning_truncated: bool = False
    suggested_questions: list[str] = Field(default_factory=list, max_length=3)
    obsidian_path: str | None = None
    markdown_draft_path: str | None = None
    whisper_model: str | None = None
    asr_backend: str | None = None
    text_source: TextSourceInfo | None = None
    ai_calls: list[AICallInfo] = Field(default_factory=list)
    cache_hits: list[str] = Field(default_factory=list)
    logs: list[PipelineLog] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    progress: dict[str, float] = Field(default_factory=dict)
    overall_progress: float = 0.0
    download_transfer: DownloadTransferInfo | None = None
    source_sync_result: dict[str, Any] | None = None
    error: str | None = None
    error_info: PipelineErrorInfo | None = None
    step: str | None = None


class PipelineCancelled(Exception):
    pass


def classify_pipeline_error(step: str, error: str) -> PipelineErrorInfo:
    if step == "config":
        return PipelineErrorInfo(
            stage=step,
            category="configuration",
            retryable=False,
            retry_scope="none",
            message=error,
        )
    if step == "parse":
        return PipelineErrorInfo(
            stage=step,
            category="input",
            retryable=False,
            retry_scope="none",
            message=error,
        )
    categories = {
        "download": ("network_or_download", "download"),
        "extract_audio": ("media_processing", "audio"),
        "transcribe": ("asr", "transcribe"),
        "summarize": ("llm", "summarize"),
        "save": ("filesystem", "save"),
        "cancelled": ("cancelled", "full"),
        "executor": ("queue_executor", "full"),
    }
    category, retry_scope = categories.get(step, ("unknown", "full"))
    return PipelineErrorInfo(
        stage=step,
        category=category,
        retryable=True,
        retry_scope=retry_scope,
        message=error,
    )
