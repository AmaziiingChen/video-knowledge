from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.pipeline_runner import WHISPER_MODELS
from services.telegram_settings import load_telegram_settings, save_telegram_settings
from services.telegram_watcher import telegram_watcher


router = APIRouter()


def _watch_options(req: "TelegramWatcherRequest") -> dict:
    return {
        "whisper_model": req.whisper_model,
        "asr_backend": req.asr_backend,
        "asr_model_strategy": req.asr_model_strategy,
        "asr_short_video_model": req.asr_short_video_model,
        "asr_long_video_model": req.asr_long_video_model,
        "asr_beam_size": req.asr_beam_size,
        "asr_vad_filter": req.asr_vad_filter,
        "asr_fallback_enabled": req.asr_fallback_enabled,
        "ai_model": req.ai_model,
        "use_cache": req.use_cache,
    }


class TelegramWatcherRequest(BaseModel):
    bot_token: str = ""
    allowed_user_ids: list[int] = Field(default_factory=list)
    reply_enabled: bool = True
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


class TelegramConnectionRequest(BaseModel):
    bot_token: str = Field(min_length=1)


class TelegramConnectionResponse(BaseModel):
    ok: bool
    id: int | None = None
    username: str | None = None
    first_name: str | None = None


class TelegramSettingsRequest(BaseModel):
    bot_token: str | None = Field(default=None, min_length=1)
    allowed_user_ids: list[int] = Field(default_factory=list)
    reply_enabled: bool = True


class TelegramSettingsResponse(BaseModel):
    configured: bool
    bot_token_masked: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)
    reply_enabled: bool = True


class TelegramCapturedLink(BaseModel):
    update_id: int
    message_id: int | None = None
    chat_id: int | None = None
    user_id: int | None = None
    link: str
    task_id: str | None = None
    created_at: str
    duplicate: bool = False


class TelegramWatcherResponse(BaseModel):
    running: bool
    configured: bool
    bot_token_masked: str | None = None
    proxy_url_masked: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)
    reply_enabled: bool = True
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
    last_update_id: int | None = None
    last_error: str | None = None
    last_checked_at: str | None = None
    started_at: str | None = None
    captured_links: list[TelegramCapturedLink] = Field(default_factory=list)
    created_task_ids: list[str] = Field(default_factory=list)


def _status_response() -> TelegramWatcherResponse:
    status = telegram_watcher.status()
    saved = load_telegram_settings()
    if not status.get("configured") and saved.get("bot_token"):
        status["configured"] = True
        status["bot_token_masked"] = _mask_token(saved.get("bot_token"))
    if not status.get("allowed_user_ids") and saved.get("allowed_user_ids"):
        status["allowed_user_ids"] = saved.get("allowed_user_ids") or []
    if "reply_enabled" in saved and not status.get("running"):
        status["reply_enabled"] = bool(saved.get("reply_enabled", True))
    return TelegramWatcherResponse(**status)


def _mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _settings_response() -> TelegramSettingsResponse:
    saved = load_telegram_settings()
    token = str(saved.get("bot_token") or "")
    return TelegramSettingsResponse(
        configured=bool(token),
        bot_token_masked=_mask_token(token),
        allowed_user_ids=saved.get("allowed_user_ids") or [],
        reply_enabled=bool(saved.get("reply_enabled", True)),
    )


@router.get("/telegram-watcher", response_model=TelegramWatcherResponse)
async def get_telegram_watcher_status():
    return _status_response()


@router.get("/telegram-watcher/settings", response_model=TelegramSettingsResponse)
async def get_telegram_settings():
    return _settings_response()


@router.post("/telegram-watcher/settings", response_model=TelegramSettingsResponse)
async def set_telegram_settings(req: TelegramSettingsRequest):
    save_telegram_settings(req.model_dump())
    return _settings_response()


@router.post("/telegram-watcher/test", response_model=TelegramConnectionResponse)
async def test_telegram_connection(req: TelegramConnectionRequest):
    try:
        result = TelegramConnectionResponse(**telegram_watcher.test_connection(req.bot_token))
        saved = load_telegram_settings()
        save_telegram_settings({**saved, "bot_token": req.bot_token})
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/telegram-watcher/start", response_model=TelegramWatcherResponse)
async def start_telegram_watcher(req: TelegramWatcherRequest):
    if req.whisper_model and req.whisper_model not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的 Whisper 模型: {req.whisper_model}")
    saved = load_telegram_settings()
    token = req.bot_token.strip() or str(saved.get("bot_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="请先在设置里填写 Telegram Bot Token")
    save_telegram_settings(
        {
            "bot_token": token,
            "allowed_user_ids": req.allowed_user_ids,
            "reply_enabled": req.reply_enabled,
            "watch_enabled": True,
            "watch_options": _watch_options(req),
        }
    )
    telegram_watcher.configure(
        bot_token=token,
        allowed_user_ids=req.allowed_user_ids,
        reply_enabled=req.reply_enabled,
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
    return TelegramWatcherResponse(**telegram_watcher.start())


@router.post("/telegram-watcher/stop", response_model=TelegramWatcherResponse)
async def stop_telegram_watcher():
    telegram_watcher.stop()
    save_telegram_settings({"watch_enabled": False})
    return _status_response()


@router.post("/telegram-watcher/poll-once", response_model=TelegramWatcherResponse)
async def poll_telegram_once():
    telegram_watcher.poll_once()
    return _status_response()
