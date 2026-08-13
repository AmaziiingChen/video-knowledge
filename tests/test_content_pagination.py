from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from routers.content import (
    ContentItemsResolveRequest,
    get_content_item,
    list_library_folder_history,
    list_content_page,
    resolve_content_items,
)
from services.content_deletion import cleanup_content_files_after_commit, delete_content_item_data
from services.cache import (
    cache_dir_for_url,
    write_cached_transcript,
    write_cached_transcript_segments,
)
from services.database import connect, initialize_database
from services.repository import ContentRepository


def test_content_page_total_excludes_library_hidden_items(monkeypatch, tmp_path):
    """A hidden source must not make the final visible page look incomplete."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        repository.create_content_item(
            source_provider="wechat",
            source_url="https://mp.weixin.qq.com/s/visible",
            canonical_source_id="visible",
            title="资料库文章",
            content_type="article",
            library_visible=True,
        )
        repository.create_content_item(
            source_provider="wechat_miniprogram",
            source_url="https://example.invalid/hidden",
            canonical_source_id="hidden",
            title="不显示在资料库的帖子",
            content_type="forum_post",
            library_visible=False,
        )
        connection.commit()

    page = list_content_page(status=None, limit=1, offset=0)

    assert page.total == 1
    assert len(page.items) == 1
    assert page.items[0].title == "资料库文章"
    assert page.has_more is False


def test_content_page_defaults_to_recent_window_but_can_explicitly_include_history(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        recent = repository.create_content_item(
            source_provider="wechat",
            source_url="https://mp.weixin.qq.com/s/recent",
            canonical_source_id="recent",
            title="近期文章",
            content_type="article",
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        old = repository.create_content_item(
            source_provider="wechat",
            source_url="https://mp.weixin.qq.com/s/archive",
            canonical_source_id="archive",
            title="历史文章",
            content_type="article",
            published_at=(datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
        )
        connection.commit()

    recent_page = list_content_page(status=None, limit=20, offset=0)
    history_page = list_content_page(status=None, limit=20, offset=0, include_history=True)

    assert [item.id for item in recent_page.items] == [recent.id]
    assert recent_page.total == 1
    assert recent_page.recent_after
    assert {item.id for item in history_page.items} == {recent.id, old.id}
    assert history_page.total == 2
    assert history_page.recent_after is None


def test_content_page_defers_cache_and_transcript_loading_until_item_is_opened(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    source_url = "https://www.bilibili.com/video/BV1example"
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="bilibili",
            source_url=source_url,
            canonical_source_id="BV1example",
            title="带字幕的视频",
            content_type="video",
        )
        connection.commit()
    write_cached_transcript_segments(
        cache_dir_for_url(source_url),
        "subtitle",
        [{"start": 0, "end": 2, "text": "真实字幕"}],
    )
    write_cached_transcript(cache_dir_for_url(source_url), "subtitle", "真实字幕")

    page_item = list_content_page(status=None, limit=20, offset=0).items[0]
    detail_item = get_content_item(item.id)

    assert page_item.transcript_segments == []
    assert page_item.text_readiness.label == "打开后检查"
    assert detail_item.transcript_segments[0]["text"] == "真实字幕"


def test_folder_history_is_paginated_outside_the_recent_library_window(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    now = datetime.now(timezone.utc)
    with connect() as connection:
        folder_id = "campus-source"
        connection.execute(
            """INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at)
               VALUES (?, ?, NULL, 0, ?, ?)""",
            (folder_id, "历史测试源", now.isoformat(), now.isoformat()),
        )
        repository = ContentRepository(connection)
        recent = repository.create_content_item(
            source_provider="manual",
            source_url="https://example.test/recent",
            canonical_source_id="recent-folder",
            title="近期文章",
            content_type="article",
            library_folder_id=folder_id,
            published_at=now.isoformat(),
        )
        older = [
            repository.create_content_item(
                source_provider="manual",
                source_url=f"https://example.test/archive-{day}",
                canonical_source_id=f"archive-{day}",
                title=f"历史文章 {day}",
                content_type="article",
                library_folder_id=folder_id,
                published_at=(now - timedelta(days=day)).isoformat(),
            )
            for day in (31, 32)
        ]
        connection.commit()

    first = list_library_folder_history(folder_id, limit=1, offset=0)
    second = list_library_folder_history(
        folder_id,
        limit=1,
        offset=1,
        history_before=first.history_before,
    )

    assert first.total == 2
    assert first.has_more is True
    assert first.items[0].id == older[0].id
    assert second.has_more is False
    assert second.items[0].id == older[1].id
    assert recent.id not in {item.id for item in first.items + second.items}


def test_resolve_content_items_keeps_requested_order_and_ignores_hidden_records(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        visible = repository.create_content_item(
            source_provider="manual",
            source_url="local://visible",
            canonical_source_id="visible-resolve",
            title="可见资料",
        )
        hidden = repository.create_content_item(
            source_provider="manual",
            source_url="local://hidden",
            canonical_source_id="hidden-resolve",
            title="隐藏资料",
            library_visible=False,
        )
        connection.commit()

    items = resolve_content_items(ContentItemsResolveRequest(
        content_item_ids=[hidden.id, visible.id, visible.id, "missing"],
    ))

    assert [item.id for item in items] == [visible.id]


def test_permanent_delete_keeps_files_until_the_database_transaction_commits(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    document = tmp_path / "library" / "source.md"
    document.parent.mkdir(parents=True)
    document.write_text("# 保留到提交\n", encoding="utf-8")
    with connect() as connection:
        repository = ContentRepository(connection)
        item = repository.create_content_item(
            source_provider="manual",
            source_url="local://source.md",
            canonical_source_id="source",
            title="待删资料",
        )
        connection.execute(
            "INSERT INTO content_documents (content_item_id, markdown_path, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            (item.id, str(document), "hash", item.created_at),
        )
        connection.commit()

        cleanup = delete_content_item_data(connection, repository, item)
        connection.rollback()

    assert document.exists()

    with connect() as connection:
        cleanup = delete_content_item_data(connection, ContentRepository(connection), item)
        connection.commit()
    cleanup_content_files_after_commit(cleanup)

    assert not document.exists()
