from pydantic import BaseModel, Field

from services.pipeline_runner import (
    AICallInfo,
    DownloadTransferInfo,
    PipelineErrorInfo,
    PipelineLog,
    TextSourceInfo,
)
from services.task_manager import TaskRecord


class TaskResponse(BaseModel):
    task_id: str
    task_type: str = "process_video"
    content_item_id: str | None = None
    status: str
    priority: int = 100
    execution_mode: str = "foreground"
    cancel_requested: bool = False
    persistence_error: str | None = None
    created_at: str
    updated_at: str
    success: bool = False
    display_title: str | None = None
    source_title: str | None = None
    source_url: str | None = None
    local_video_path: str | None = None
    local_subtitle_path: str | None = None
    url: str | None = None
    platform: str | None = None
    video_path: str | None = None
    transcript: str | None = None
    summary: str | None = None
    summary_length: int = 0
    reasoning_content: str = ""
    reasoning_length: int = 0
    reasoning_truncated: bool = False
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
    source_sync_result: dict | None = None
    error: str | None = None
    error_info: PipelineErrorInfo | None = None
    step: str | None = None
    details_included: bool = True


def to_task_response(
    record: TaskRecord,
    *,
    include_heavy_payload: bool = True,
) -> TaskResponse:
    """Present a persisted task without making routers depend on one another."""
    result = record.result
    return TaskResponse(
        task_id=record.task_id,
        task_type=record.task_type,
        content_item_id=record.content_item_id or (result.content_item_id if result else None),
        status=record.status,
        priority=record.priority,
        execution_mode=record.execution_mode,
        cancel_requested=record.cancel_requested,
        persistence_error=record.persistence_error,
        created_at=record.created_at,
        updated_at=record.updated_at,
        success=bool(result and result.success),
        display_title=result.display_title if result else None,
        source_title=record.source_title,
        source_url=record.source_url or record.share_text or (result.url if result else None),
        local_video_path=record.local_video_path,
        local_subtitle_path=record.local_subtitle_path,
        url=result.url if result else None,
        platform=result.platform if result else None,
        video_path=result.video_path if result else None,
        transcript=result.transcript if result and include_heavy_payload else None,
        summary=result.summary if result and include_heavy_payload else None,
        summary_length=len(result.summary or "") if result else 0,
        reasoning_content=result.reasoning_content if result and include_heavy_payload else "",
        reasoning_length=len(result.reasoning_content or "") if result else 0,
        reasoning_truncated=bool(result and result.reasoning_truncated),
        obsidian_path=result.obsidian_path if result else None,
        markdown_draft_path=result.markdown_draft_path if result else None,
        whisper_model=result.whisper_model if result else record.whisper_model,
        asr_backend=result.asr_backend if result else record.asr_backend,
        text_source=result.text_source if result and include_heavy_payload else None,
        ai_calls=result.ai_calls if result and include_heavy_payload else [],
        cache_hits=result.cache_hits if result and include_heavy_payload else [],
        logs=result.logs if result and include_heavy_payload else [],
        timings=result.timings if result and include_heavy_payload else {},
        progress=result.progress if result else {},
        overall_progress=result.overall_progress if result else 0.0,
        download_transfer=result.download_transfer if result else None,
        source_sync_result=result.source_sync_result if result and include_heavy_payload else None,
        error=(result.error if result else None) or record.persistence_error,
        error_info=result.error_info if result and include_heavy_payload else None,
        step=result.step if result else None,
        details_included=include_heavy_payload,
    )
