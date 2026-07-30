from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import importlib.util
import os

from config import settings
from routers import parse, download, transcribe, summarize, pipeline, cookie, tasks, uploads, qa, knowledge, clipboard, folder_import_watcher, prompts, inbox, search, content, content_analyses, markdown, media, telegram, ingest, obsidian, openclaw, openclaw_reports, agent_workspace, wechat_subscriptions, wechat_feed, wechat_content_filters, media_tools, llm_settings, paddle_ocr_settings, wechat_reports, wechat_publishing, campus_sources, runtime_components, miniprogram_forum, creator_sources, rss_sources, manual_collection, favorite_sources, source_sync_tasks, video_settings, update, telemetry, completion_notifications
from services.database import connect, initialize_database
from services.llm_provider import DEEPSEEK_MODEL_OPTIONS, deepseek_model_option_value
from services.pipeline_runner import ASR_MODEL_STRATEGIES, WHISPER_MODELS
from services.runtime_components import supported_asr_backends
from services.task_manager import TaskPersistenceError, task_manager
from services.obsidian_settings import apply_saved_obsidian_settings
from services.llm_settings import apply_saved_llm_settings
from services.paddle_ocr_settings import apply_saved_paddle_ocr_settings
from services.paddle_ocr import resume_pending_ocr_jobs
from services.knowledge_library import ensure_library_layout, recover_legacy_report_documents
from services.content_index import ensure_content_index_ready
from services.wechat_reports import repair_report_folder_bindings
from services.prompt_file_store import sync_prompt_files
from services.wechat_subscription import (
    wechat_subscription_scheduler,
    wechat_subscription_service,
)
from services.campus_source_scheduler import campus_source_scheduler
from services.campus_digest_scheduler import campus_digest_scheduler
from services.cache_retention import cache_retention_scheduler
from services.miniprogram_forum_collector import miniprogram_forum_collector
from services.forum_capture_repository import repair_forum_capture_document_types
from services.miniprogram_forum_settings import miniprogram_forum_scheduler
from services.search_index_scheduler import search_index_scheduler
from services.creator_scheduler import creator_subscription_scheduler
from services.favorite_scheduler import favorite_subscription_scheduler
from services.rss_scheduler import rss_subscription_scheduler
from services.openclaw_notifications import openclaw_notification_scheduler
from services.openclaw_report_tasks import openclaw_report_task_manager
from services.wechat_draft_tasks import wechat_draft_task_manager
from services.report_group_scheduler import report_group_scheduler
from services.watcher_restore import restore_enabled_watchers, stop_watchers
from services import telemetry as telemetry_service

app = FastAPI(title="KnowledgeHub Pipeline", version="1.0.0")


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

@app.on_event("startup")
async def startup():
    telemetry_service.record("app_started")
    ensure_library_layout()
    try:
        apply_saved_obsidian_settings()
    except ValueError:
        # A disconnected or permission-restricted vault must not prevent the
        # local application (and its settings screen) from starting.
        settings.obsidian_vault = settings.data_dir / "obsidian"
        settings.obsidian_vault.mkdir(parents=True, exist_ok=True)
    apply_saved_llm_settings()
    apply_saved_paddle_ocr_settings()
    initialize_database()
    # Provider job IDs are durable; resume their low-frequency polls only
    # after the local database is ready, never on the first-render path.
    resume_pending_ocr_jobs()
    # Complete one-time legacy folder/index repair before the health endpoint
    # admits the desktop renderer.  Otherwise its first tree request pays for
    # this work and appears empty despite the window being ready.
    ensure_content_index_ready()
    # Older reports were stored under data/drafts.  Reconnect any preserved
    # legacy report files with the Markdown-first document index on startup.
    recover_legacy_report_documents()
    repair_report_folder_bindings()
    repair_forum_capture_document_types()
    with connect() as connection:
        sync_prompt_files(connection)
        connection.commit()
    miniprogram_forum_collector.recover_stale_runs()
    interrupted_initial_syncs = wechat_subscription_service.recover_interrupted_initial_syncs()
    if settings.miniprogram_forum_capture_enabled:
        miniprogram_forum_scheduler.start()
    task_manager.recover_from_database()
    openclaw_report_task_manager.recover_from_database()
    wechat_draft_task_manager.recover_from_database()
    openclaw_notification_scheduler.start()
    # Restore only listeners explicitly enabled by the user.  Clipboard
    # restoration primes the current clipboard first, so reopening the app
    # never requeues the link that happened to be copied at shutdown.
    restore_enabled_watchers()
    campus_source_scheduler.start()
    wechat_subscription_scheduler.start()
    for subscription_id in interrupted_initial_syncs:
        try:
            subscription = wechat_subscription_service.get_subscription(subscription_id)
            task_manager.create_source_sync(
                {"kind": "wechat_subscription", "subscription_id": subscription_id, "mode": "latest", "max_items": 10},
                source_title=f"恢复首次检查：{subscription['mp_name']}",
                execution_mode="background",
            )
        except Exception:
            continue
    creator_subscription_scheduler.start()
    favorite_subscription_scheduler.start()
    rss_subscription_scheduler.start()
    report_group_scheduler.start()
    campus_digest_scheduler.start()
    cache_retention_scheduler.start()
    # Search only observes local Markdown already in the library.  It neither
    # fetches source pages nor schedules OCR/model work.
    search_index_scheduler.start()
@app.on_event("shutdown")
async def shutdown():
    telemetry_service.flush()
    stop_watchers()
    openclaw_notification_scheduler.stop()
    openclaw_report_task_manager.shutdown()
    wechat_draft_task_manager.shutdown()
    search_index_scheduler.stop()
    miniprogram_forum_scheduler.stop()
    cache_retention_scheduler.stop()
    campus_digest_scheduler.stop()
    campus_source_scheduler.stop()
    wechat_subscription_scheduler.stop()
    creator_subscription_scheduler.stop()
    favorite_subscription_scheduler.stop()
    rss_subscription_scheduler.stop()
    report_group_scheduler.stop()

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "service": "knowledgehub-backend",
        "version": settings.app_version,
        "instance_token": os.environ.get("KNOWLEDGEHUB_INSTANCE_TOKEN", ""),
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
