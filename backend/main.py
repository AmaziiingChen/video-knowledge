import hmac
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import importlib.util

from config import settings
from routers import parse, download, transcribe, summarize, pipeline, cookie, tasks, uploads, qa, knowledge, clipboard, folder_import_watcher, prompts, inbox, search, content, content_analyses, markdown, media, telegram, ingest, obsidian, openclaw, openclaw_reports, agent_workspace, wechat_subscriptions, wechat_discovery, wechat_feed, wechat_content_filters, media_tools, llm_settings, paddle_ocr_settings, wechat_reports, wechat_publishing, campus_sources, runtime_components, miniprogram_forum, creator_sources, rss_sources, manual_collection, favorite_sources, source_sync_tasks, video_settings, update, telemetry, completion_notifications
from services.llm_provider import DEEPSEEK_MODEL_OPTIONS, deepseek_model_option_value
from services.pipeline_runner import ASR_MODEL_STRATEGIES, WHISPER_MODELS
from services.runtime_components import supported_asr_backends
from services.task_manager import TaskPersistenceError
from services.application_lifecycle import start_application, stop_application


@asynccontextmanager
async def application_lifespan(_app: FastAPI):
    await start_application()
    try:
        yield
    finally:
        await stop_application()


app = FastAPI(title="KnowledgeHub Pipeline", version="0.1.0", lifespan=application_lifespan)


@app.exception_handler(TaskPersistenceError)
async def task_persistence_error_handler(_request, _exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "本地任务队列暂时不可写，请稍后重试"},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=settings.allowed_origin_regex,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _is_allowed_local_origin(request: Request) -> bool:
    """Accept only the desktop shell or loopback source UI as browser callers."""
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        # Non-browser callers still need the private instance token below.
        return True
    allowed_origins = {value.rstrip("/") for value in settings.allowed_origins}
    return origin in allowed_origins or bool(re.fullmatch(settings.allowed_origin_regex, origin))


def _allows_unauthenticated_test_api() -> bool:
    return os.environ.get("KNOWLEDGEHUB_ALLOW_UNAUTHENTICATED_LOCAL_API", "").strip().lower() in {"1", "true", "yes"}


@app.middleware("http")
async def require_desktop_instance_token(request: Request, call_next):
    """Bind every local API write to the launching desktop or source-session token."""
    expected_token = os.environ.get("KNOWLEDGEHUB_INSTANCE_TOKEN", "").strip()
    if request.url.path.startswith("/api/") and request.method.upper() in _MUTATING_METHODS:
        if not _is_allowed_local_origin(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "本机 API 仅接受 KnowledgeHub 页面发起的写入请求"},
            )
        if not expected_token and not _allows_unauthenticated_test_api():
            return JSONResponse(
                status_code=503,
                content={"detail": "本机 API 尚未配置实例访问令牌"},
            )
        received_token = request.headers.get("x-knowledgehub-token", "")
        if expected_token and not hmac.compare_digest(received_token, expected_token):
            return JSONResponse(
                status_code=401,
                content={"detail": "本机 API 请求未获桌面应用授权"},
            )
    return await call_next(request)

app.include_router(parse.router, prefix="/api", tags=["parse"])
app.include_router(download.router, prefix="/api", tags=["download"])
app.include_router(transcribe.router, prefix="/api", tags=["transcribe"])
app.include_router(summarize.router, prefix="/api", tags=["summarize"])
app.include_router(pipeline.router, prefix="/api", tags=["pipeline"])
app.include_router(cookie.router, prefix="/api", tags=["cookie"])
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(uploads.router, prefix="/api", tags=["uploads"])
app.include_router(qa.router, prefix="/api", tags=["qa"])
app.include_router(knowledge.router, prefix="/api", tags=["knowledge"])
app.include_router(clipboard.router, prefix="/api", tags=["clipboard"])
app.include_router(folder_import_watcher.router, prefix="/api", tags=["folder-import-watcher"])
app.include_router(prompts.router, prefix="/api", tags=["prompts"])
app.include_router(inbox.router, prefix="/api", tags=["inbox"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(content.router, prefix="/api", tags=["content"])
app.include_router(content_analyses.router, prefix="/api", tags=["content-analyses"])
app.include_router(markdown.router, prefix="/api", tags=["markdown"])
app.include_router(media.router, prefix="/api", tags=["media"])
app.include_router(telegram.router, prefix="/api", tags=["telegram"])
app.include_router(ingest.router, prefix="/api", tags=["ingest"])
app.include_router(obsidian.router, prefix="/api", tags=["obsidian"])
app.include_router(openclaw.router, prefix="/api", tags=["openclaw"])
app.include_router(openclaw_reports.router, prefix="/api", tags=["openclaw-reports"])
app.include_router(agent_workspace.router, prefix="/api", tags=["agent-workspace"])
app.include_router(wechat_subscriptions.router, prefix="/api", tags=["wechat-subscriptions"])
app.include_router(wechat_discovery.router, prefix="/api", tags=["wechat-discovery"])
app.include_router(wechat_feed.router, prefix="/api", tags=["wechat-feed"])
app.include_router(wechat_content_filters.router, prefix="/api", tags=["wechat-content-filters"])
app.include_router(media_tools.router, prefix="/api", tags=["media-tools"])
app.include_router(llm_settings.router, prefix="/api", tags=["llm-settings"])
app.include_router(paddle_ocr_settings.router, prefix="/api", tags=["paddle-ocr-settings"])
app.include_router(wechat_reports.router, prefix="/api", tags=["wechat-reports"])
app.include_router(wechat_publishing.router, prefix="/api", tags=["wechat-publishing"])
app.include_router(campus_sources.router, prefix="/api", tags=["campus-sources"])
app.include_router(runtime_components.router, prefix="/api", tags=["runtime-components"])
app.include_router(miniprogram_forum.router, prefix="/api", tags=["miniprogram-forum"])
app.include_router(creator_sources.router, prefix="/api", tags=["creator-sources"])
app.include_router(manual_collection.router, prefix="/api", tags=["manual-collection"])
app.include_router(rss_sources.router, prefix="/api", tags=["rss-sources"])
app.include_router(favorite_sources.router, prefix="/api", tags=["favorite-sources"])
app.include_router(source_sync_tasks.router, prefix="/api", tags=["source-sync-tasks"])
app.include_router(video_settings.router, prefix="/api", tags=["video-settings"])
app.include_router(update.router, prefix="/api", tags=["updates"])
app.include_router(telemetry.router, prefix="/api", tags=["telemetry"])
app.include_router(completion_notifications.router, prefix="/api", tags=["completion-notifications"])

@app.get("/api/health")
async def health(request: Request):
    expected_token = os.environ.get("KNOWLEDGEHUB_INSTANCE_TOKEN", "").strip()
    supplied_token = request.headers.get("x-knowledgehub-token", "")
    # Do not disclose the launch capability to an arbitrary loopback client.
    # The Electron parent already owns it and supplies it when checking that
    # port 8000 belongs to this exact backend process.
    instance_token = (
        expected_token
        if expected_token and hmac.compare_digest(supplied_token, expected_token)
        else ""
    )
    return {
        "status": "ok",
        "service": "knowledgehub-backend",
        "version": settings.app_version,
        "instance_token": instance_token,
    }

@app.get("/api/config")
async def get_config():
    return {
        "deepseek_configured": bool(settings.deepseek_api_key),
        "deepseek_model": settings.deepseek_model,
        "deepseek_model_option": deepseek_model_option_value(settings.deepseek_model),
        "available_ai_models": DEEPSEEK_MODEL_OPTIONS,
        "whisper_model": settings.whisper_model,
        "available_whisper_models": sorted(WHISPER_MODELS),
        "asr_backend": settings.asr_backend,
        "asr_model_strategy": settings.asr_model_strategy,
        "asr_short_video_model": settings.asr_short_video_model,
        "asr_long_video_model": settings.asr_long_video_model,
        "asr_beam_size": settings.asr_beam_size,
        "asr_vad_filter": settings.asr_vad_filter,
        "asr_fallback_enabled": settings.asr_fallback_enabled,
        "available_asr_backends": supported_asr_backends(),
        "available_asr_model_strategies": sorted(ASR_MODEL_STRATEGIES),
        "mlx_whisper_available": importlib.util.find_spec("mlx_whisper") is not None,
        "miniprogram_forum_capture_enabled": settings.miniprogram_forum_capture_enabled,
    }
