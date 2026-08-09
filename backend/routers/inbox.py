from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from presentation.inbox_responses import InboxItemResponse, to_inbox_item_response
from services.inbox import capture_link_to_inbox, list_inbox_items, process_inbox_item
from services.pipeline_runner import WHISPER_MODELS


router = APIRouter()


class InboxCaptureRequest(BaseModel):
    url: str = Field(min_length=1)


class InboxProcessRequest(BaseModel):
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


class InboxCaptureResponse(BaseModel):
    item: InboxItemResponse
    created: bool
    duplicate: bool


class InboxProcessResponse(BaseModel):
    item: InboxItemResponse
    task_id: str
    task_status: str


@router.get("/inbox", response_model=list[InboxItemResponse])
async def get_inbox(limit: int = 100):
    return [to_inbox_item_response(item) for item in list_inbox_items(limit=max(1, min(limit, 500)))]


@router.post("/inbox/capture", response_model=InboxCaptureResponse)
async def capture_inbox_link(req: InboxCaptureRequest):
    result = capture_link_to_inbox(req.url.strip())
    if result.error or result.item is None:
        raise HTTPException(status_code=400, detail=result.error or "收件箱捕获失败")
    return InboxCaptureResponse(
        item=to_inbox_item_response(result.item),
        created=result.created,
        duplicate=result.duplicate,
    )


@router.post("/inbox/{item_id}/process", response_model=InboxProcessResponse)
async def process_inbox_item_endpoint(item_id: str, req: InboxProcessRequest):
    if req.whisper_model and req.whisper_model not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的 Whisper 模型: {req.whisper_model}")
    try:
        item, task = process_inbox_item(
            item_id,
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
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="收件箱条目不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return InboxProcessResponse(
        item=to_inbox_item_response(item),
        task_id=task.task_id,
        task_status=task.status,
    )
