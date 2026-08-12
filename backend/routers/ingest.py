from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from presentation.inbox_responses import InboxItemResponse, to_inbox_item_response
from presentation.task_responses import TaskResponse, to_task_response
from services.inbox import capture_link_to_inbox, process_inbox_item
from services.manual_collection_settings import manual_collection_settings
from services.openclaw_conversations import bind_task
from services.pipeline_runner import PipelineRequest, WHISPER_MODELS
from services.task_manager import task_manager
from services.url_parser import parse_share_text
from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable, require_xiaohongshu_collector


router = APIRouter()

SUPPORTED_PLATFORMS = {"douyin", "bilibili", "wechat", "xiaohongshu"}


class IngestLinkRequest(BaseModel):
    text: str = Field(min_length=1)
    mode: str = Field(default="process", pattern="^(process|capture)$")
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
    priority: int = 100
    conversation_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="OpenClaw current session key. It is hashed locally before task mapping is stored.",
    )
    conversation_channel: str = Field(default="weixin", max_length=40)
    conversation_label: str | None = Field(default=None, max_length=120)


class IngestLinkResponse(BaseModel):
    platform: str
    url: str
    item: InboxItemResponse | None = None
    created: bool = False
    duplicate: bool = False
    task: TaskResponse | None = None


@router.post("/ingest/link", response_model=IngestLinkResponse)
async def ingest_link(req: IngestLinkRequest):
    if req.whisper_model and req.whisper_model not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的 Whisper 模型: {req.whisper_model}")

    parsed = parse_share_text(req.text)
    if not parsed:
        raise HTTPException(status_code=400, detail="没有识别到抖音、B站、微信公众号或小红书链接")
    if parsed.platform not in SUPPORTED_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"暂不支持的来源: {parsed.platform}")
    if parsed.platform == "xiaohongshu":
        try:
            require_xiaohongshu_collector()
        except XiaohongshuCollectorUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    capture = capture_link_to_inbox(parsed.url)
    if capture.error or capture.item is None:
        raise HTTPException(status_code=400, detail=capture.error or "链接入库失败")

    item_response = to_inbox_item_response(capture.item)
    if req.mode == "capture":
        return IngestLinkResponse(
            platform=parsed.platform,
            url=capture.item.source_url,
            item=item_response,
            created=capture.created,
            duplicate=capture.duplicate,
        )

    try:
        item, task = process_inbox_item(
            capture.item.id,
            whisper_model=req.whisper_model,
            asr_backend=req.asr_backend,
            asr_model_strategy=req.asr_model_strategy,
            asr_short_video_model=req.asr_short_video_model,
            asr_long_video_model=req.asr_long_video_model,
            asr_beam_size=req.asr_beam_size,
            asr_vad_filter=req.asr_vad_filter,
            asr_fallback_enabled=req.asr_fallback_enabled,
            ai_model=req.ai_model,
            use_cache=req.use_cache,
        )
    except ValueError as exc:
        if capture.duplicate:
            task = task_manager.create(
                PipelineRequest(
                    content_item_id=capture.item.id,
                    share_text=parsed.url,
                    source_title=capture.item.title,
                    source_url=parsed.url,
                    whisper_model=req.whisper_model,
                    asr_backend=req.asr_backend,
                    asr_model_strategy=req.asr_model_strategy,
                    asr_short_video_model=req.asr_short_video_model,
                    asr_long_video_model=req.asr_long_video_model,
                    asr_beam_size=req.asr_beam_size,
                    asr_vad_filter=req.asr_vad_filter,
                    asr_fallback_enabled=req.asr_fallback_enabled,
                    ai_model=req.ai_model,
                    use_cache=req.use_cache,
                    processing_mode="full" if manual_collection_settings()["auto_summarize"] else "transcript",
                    priority=req.priority,
                )
            )
            item = capture.item
        else:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    task_response = to_task_response(task)
    if req.conversation_key:
        try:
            bind_task(
                session_key=req.conversation_key,
                task_id=task_response.task_id,
                channel=req.conversation_channel,
                display_name=req.conversation_label,
            )
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return IngestLinkResponse(
        platform=parsed.platform,
        url=item.source_url,
        item=to_inbox_item_response(item),
        created=capture.created,
        duplicate=capture.duplicate,
        task=task_response,
    )
