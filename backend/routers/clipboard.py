from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.clipboard_watcher import clipboard_watcher
from services.clipboard_settings import save_clipboard_watcher_settings
from services.pipeline_runner import WHISPER_MODELS


router = APIRouter()


class ClipboardWatcherRequest(BaseModel):
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
    poll_interval: float = Field(default=0.75, ge=0.5, le=10.0)
    capture_mode: str = Field(default="task", pattern="^(inbox|task)$")


class ClipboardScanRequest(BaseModel):
    text: str = Field(max_length=50_000)


class CapturedClipboardLink(BaseModel):
    link: str
    item_id: str | None = None
    task_id: str | None = None
    created_at: str
    duplicate: bool = False
    capture_mode: str = "task"


class ClipboardWatcherResponse(BaseModel):
    running: bool
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
    poll_interval: float = 0.75
    capture_mode: str = "task"
    last_error: str | None = None
    last_checked_at: str | None = None
    started_at: str | None = None
    captured_links: list[CapturedClipboardLink] = Field(default_factory=list)
    created_task_ids: list[str] = Field(default_factory=list)


def _status_response() -> ClipboardWatcherResponse:
    return ClipboardWatcherResponse(**clipboard_watcher.status())


@router.get("/clipboard-watcher", response_model=ClipboardWatcherResponse)
async def get_clipboard_watcher_status():
    return _status_response()


@router.post("/clipboard-watcher/scan", response_model=ClipboardWatcherResponse)
async def scan_native_clipboard(req: ClipboardScanRequest):
    # Electron owns the reliable native pasteboard API in packaged builds.
    # Keep the existing backend poller for source mode and Windows, while this
    # authenticated loopback bridge supplies macOS changes only when enabled.
    if clipboard_watcher.status()["running"]:
        clipboard_watcher.scan_text(req.text)
    return _status_response()


@router.post("/clipboard-watcher/start", response_model=ClipboardWatcherResponse)
async def start_clipboard_watcher(req: ClipboardWatcherRequest):
    if req.whisper_model and req.whisper_model not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的 Whisper 模型: {req.whisper_model}")
    saved = save_clipboard_watcher_settings({"enabled": True, **req.model_dump()})
    clipboard_watcher.start(
        whisper_model=req.whisper_model,
        asr_backend=req.asr_backend,
        asr_model_strategy=req.asr_model_strategy,
        asr_short_video_model=req.asr_short_video_model,
        asr_long_video_model=req.asr_long_video_model,
        asr_beam_size=req.asr_beam_size,
        asr_vad_filter=req.asr_vad_filter,
        asr_fallback_enabled=req.asr_fallback_enabled,
        ai_model=req.ai_model,
        use_cache=bool(saved["use_cache"]),
        poll_interval=float(saved["poll_interval"]),
        capture_mode=str(saved["capture_mode"]),
    )
    return _status_response()


@router.post("/clipboard-watcher/stop", response_model=ClipboardWatcherResponse)
async def stop_clipboard_watcher():
    clipboard_watcher.stop()
    save_clipboard_watcher_settings({"enabled": False})
    return _status_response()
