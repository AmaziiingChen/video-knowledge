"""Application startup and shutdown orchestration for the local backend."""

from config import settings

from services import telemetry as telemetry_service
from services.article_ingest_preparation import enqueue_pending_article_preparation
from services.cache_retention import cache_retention_scheduler
from services.campus_digest_scheduler import campus_digest_scheduler
from services.campus_source_scheduler import campus_source_scheduler
from services.content_index import ensure_content_index_ready
from services.creator_scheduler import creator_subscription_scheduler
from services.database import connect, initialize_database
from services.favorite_scheduler import favorite_subscription_scheduler
from services.forum_capture_repository import repair_forum_capture_document_types
from services.knowledge_library import ensure_library_layout, recover_legacy_report_documents
from services.llm_settings import apply_saved_llm_settings
from services.miniprogram_forum_collector import miniprogram_forum_collector
from services.miniprogram_forum_settings import miniprogram_forum_scheduler
from services.obsidian_settings import apply_saved_obsidian_settings
from services.openclaw_notifications import openclaw_notification_scheduler
from services.openclaw_report_tasks import openclaw_report_task_manager
from services.paddle_ocr import resume_pending_ocr_jobs
from services.paddle_ocr_settings import apply_saved_paddle_ocr_settings
from services.prompt_file_store import sync_prompt_files
from services.report_group_scheduler import report_group_scheduler
from services.rss_scheduler import rss_subscription_scheduler
from services.search_index_scheduler import search_index_scheduler
from services.task_manager import task_manager
from services.watcher_restore import restore_enabled_watchers, stop_watchers
from services.wechat_draft_tasks import wechat_draft_task_manager
from services.wechat_public_scheduler import wechat_public_album_scheduler
from services.wechat_reports import repair_report_folder_bindings
from services.wechat_subscription import (
    wechat_subscription_scheduler,
    wechat_subscription_service,
)


async def start_application() -> None:
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
    # Body capture and OCR preparation use in-memory executors.  Their durable
    # readiness state lives on the content item, so rebuild that bounded queue
    # once after database/index repair when a previous desktop session ended.
    enqueue_pending_article_preparation()
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
    wechat_public_album_scheduler.start()
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


async def stop_application() -> None:
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
    wechat_public_album_scheduler.stop()
    creator_subscription_scheduler.stop()
    favorite_subscription_scheduler.stop()
    rss_subscription_scheduler.stop()
    report_group_scheduler.stop()
