from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services import inbox
from services.content_index import (
    ensure_manual_collection_folder,
    ensure_manual_collection_target_folder,
    migrate_manual_collection_items,
)
from services.database import connect, initialize_database
from services.manual_collection_settings import manual_collection_settings, save_manual_collection_settings
from services.providers.base import ResolvedContent
from services.repository import ContentRepository
from services.cache import cache_dir_for_url, write_cache_meta
from services import pipeline_runner


class _ResolvedWechatProvider:
    name = "wechat"

    def normalize_url(self, url: str) -> str:
        return url

    def resolve(self, url: str) -> ResolvedContent:
        return ResolvedContent(
            provider="wechat",
            content_type="article",
            source_url=url,
            canonical_source_id=url,
            title="主动收藏文章",
        )


def test_manual_capture_uses_the_provider_collection_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    monkeypatch.setattr(inbox, "get_provider_for_url", lambda _url: _ResolvedWechatProvider())

    captured = inbox.capture_link_to_inbox("https://mp.weixin.qq.com/s/manual")
    assert captured.created is True
    assert captured.item is not None
    with connect() as connection:
        folder_id = ensure_manual_collection_target_folder(connection, "wechat")
        item = ContentRepository(connection).get_content_item(captured.item.id)
        folder = connection.execute("SELECT name FROM library_folders WHERE id=?", (folder_id,)).fetchone()
    assert item.library_folder_id == folder_id
    assert folder["name"] == "手动收藏"


def test_manual_collection_backfill_and_summary_preference(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    assert manual_collection_settings()["auto_summarize"] is True
    assert save_manual_collection_settings(auto_summarize=False)["auto_summarize"] is False
    with connect() as connection:
        legacy_folder_id = ensure_manual_collection_folder(connection)
        item = ContentRepository(connection).create_content_item(
            source_provider="bilibili",
            canonical_source_id="legacy-direct-link",
            title="旧的直接链接",
            library_folder_id=legacy_folder_id,
        )
        connection.commit()
    assert migrate_manual_collection_items() == 1
    with connect() as connection:
        repaired = ContentRepository(connection).get_content_item(item.id)
    assert repaired.library_folder_id is not None


def test_manual_summary_preference_controls_created_task(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    monkeypatch.setattr(inbox, "get_provider_for_url", lambda _url: _ResolvedWechatProvider())
    request_holder = {}

    def fake_create(request):
        request_holder["request"] = request
        return type("Task", (), {"task_id": "manual-task"})()

    monkeypatch.setattr(inbox.task_manager, "create", fake_create)
    item = inbox.capture_link_to_inbox("https://mp.weixin.qq.com/s/manual-summary").item
    assert item is not None
    save_manual_collection_settings(auto_summarize=False)
    _, task = inbox.process_inbox_item(item.id)
    assert task.task_id == "manual-task"
    assert request_holder["request"].processing_mode == "transcript"


def test_rss_auto_analysis_schema_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    with connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(rss_sources)")}
    assert "auto_analyze" in columns


def test_persisted_rss_article_can_use_the_summary_task_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    initialize_database()
    url = "https://example.test/rss-entry"
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="rss",
            content_type="article",
            source_url=url,
            canonical_source_id="rss:test-entry",
            title="RSS 测试文章",
            status="to_read",
        )
        connection.commit()
    write_cache_meta(
        cache_dir_for_url(url),
        {"article_info": {"title": item.title, "platform": "rss", "body_text": "这是一段 RSS 正文。", "body_html": "<p>这是一段 RSS 正文。</p>", "images": []}},
    )
    monkeypatch.setattr(pipeline_runner, "summarize_stream", lambda *_args, **_kwargs: ("RSS 总结标题", "RSS 总结内容"))
    monkeypatch.setattr(pipeline_runner, "replace_content_summary_and_sync", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_runner, "upsert_search_document", lambda **_kwargs: None)

    response = pipeline_runner.run_pipeline_sync(content_item_id=item.id, share_text=url)
    assert response.success is True
    assert response.summary == "RSS 总结内容"
    assert response.display_title == "RSS 总结标题"
