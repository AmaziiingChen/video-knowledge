from __future__ import annotations

import asyncio
from contextlib import nullcontext
from unittest.mock import Mock

from services import application_lifecycle
from services.favorite_scheduler import FavoriteSubscriptionScheduler


def _patch_lifecycle_dependencies(monkeypatch):
    for name in (
        "ensure_library_layout",
        "apply_saved_obsidian_settings",
        "apply_saved_llm_settings",
        "apply_saved_paddle_ocr_settings",
        "initialize_database",
        "resume_pending_ocr_jobs",
        "start_article_source_preparation",
        "enqueue_pending_article_preparation",
        "shutdown_article_source_preparation",
        "ensure_content_index_ready",
        "recover_legacy_report_documents",
        "repair_report_folder_bindings",
        "repair_forum_capture_document_types",
        "sync_prompt_files",
        "restore_enabled_watchers",
        "stop_watchers",
    ):
        monkeypatch.setattr(application_lifecycle, name, Mock())
    monkeypatch.setattr(application_lifecycle, "connect", lambda: nullcontext(Mock()))
    monkeypatch.setattr(application_lifecycle.telemetry_service, "bootstrap", Mock())
    monkeypatch.setattr(application_lifecycle.telemetry_service, "record", Mock())
    monkeypatch.setattr(application_lifecycle.telemetry_service, "flush", Mock())
    monkeypatch.setattr(application_lifecycle, "telemetry_uploader", Mock())
    monkeypatch.setattr(application_lifecycle.miniprogram_forum_collector, "recover_stale_runs", Mock())
    monkeypatch.setattr(application_lifecycle, "wechat_subscription_service", Mock(recover_interrupted_initial_syncs=Mock(return_value=[])))
    for name in (
        "task_manager",
        "openclaw_report_task_manager",
        "wechat_draft_task_manager",
        "openclaw_notification_scheduler",
        "campus_source_scheduler",
        "wechat_subscription_scheduler",
        "wechat_public_album_scheduler",
        "creator_subscription_scheduler",
        "rss_subscription_scheduler",
        "report_group_scheduler",
        "campus_digest_scheduler",
        "cache_retention_scheduler",
        "search_index_scheduler",
        "miniprogram_forum_scheduler",
    ):
        monkeypatch.setattr(application_lifecycle, name, Mock())


def test_application_lifecycle_starts_and_stops_favorite_scheduler(monkeypatch):
    _patch_lifecycle_dependencies(monkeypatch)
    favorite_scheduler = Mock()
    monkeypatch.setattr(application_lifecycle, "favorite_subscription_scheduler", favorite_scheduler)

    asyncio.run(application_lifecycle.start_application())
    asyncio.run(application_lifecycle.stop_application())

    favorite_scheduler.start.assert_called_once_with()
    favorite_scheduler.stop.assert_called_once_with()


def test_application_lifecycle_resumes_pending_article_preparation_once(monkeypatch):
    _patch_lifecycle_dependencies(monkeypatch)

    asyncio.run(application_lifecycle.start_application())

    application_lifecycle.start_article_source_preparation.assert_called_once_with()
    application_lifecycle.enqueue_pending_article_preparation.assert_called_once_with()
    application_lifecycle.telemetry_uploader.start.assert_called_once_with()


def test_application_lifecycle_bootstraps_telemetry_before_the_first_event_and_database(monkeypatch):
    _patch_lifecycle_dependencies(monkeypatch)
    order = []
    application_lifecycle.telemetry_service.bootstrap.side_effect = lambda: order.append("telemetry_bootstrap")
    application_lifecycle.telemetry_service.record.side_effect = lambda *_args: order.append("app_started")
    application_lifecycle.initialize_database.side_effect = lambda: order.append("database")

    asyncio.run(application_lifecycle.start_application())

    assert order[:3] == ["telemetry_bootstrap", "app_started", "database"]


def test_application_lifecycle_stops_article_preparation_after_producers(monkeypatch):
    _patch_lifecycle_dependencies(monkeypatch)

    asyncio.run(application_lifecycle.stop_application())

    application_lifecycle.shutdown_article_source_preparation.assert_called_once_with(wait=True)
    application_lifecycle.telemetry_uploader.stop.assert_called_once_with()


def test_disabled_favorite_scheduler_never_creates_a_thread(monkeypatch):
    monkeypatch.setattr(application_lifecycle.settings, "favorite_scheduler_enabled", False)
    scheduler = FavoriteSubscriptionScheduler()

    scheduler.start()

    assert scheduler._thread is None
