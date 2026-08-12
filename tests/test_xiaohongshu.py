from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.providers.xiaohongshu import XiaohongshuProvider
from services.url_parser import parse_share_text
from services.xiaohongshu_client import XiaohongshuNote, normalize_note_url, note_id_from_url, xiaohongshu_cookie_status
from services import xiaohongshu_ingest
from services.article_preview import normalize_article_html
from services.cache import cache_dir_for_url, read_cache_meta, write_cache_meta
from services.clipboard_watcher import extract_supported_links
from services.content_source_text import ContentSourceText
from services.database import connect, initialize_database
from services.inbox import capture_link_to_inbox
from services.pipeline_runner import run_pipeline_sync
from services.telegram_watcher import TelegramWatcher
from services.xiaohongshu_cache import xiaohongshu_cache_dir
from services.xiaohongshu_links import XiaohongshuShareLinkError, resolve_xiaohongshu_share_url
from config import settings
from services import xiaohongshu_client
from services.database import _migration_092_repair_placeholder_content_items


@pytest.fixture(autouse=True)
def available_xiaohongshu_collector(tmp_path, monkeypatch):
    vendor_root = tmp_path / "Spider_XHS"
    (vendor_root / "apis").mkdir(parents=True)
    (vendor_root / "xhs_utils").mkdir(parents=True)
    (vendor_root / "apis" / "xhs_pc_apis.py").touch()
    (vendor_root / "xhs_utils" / "xhs_pc.py").touch()
    monkeypatch.setattr("services.xiaohongshu_capability.xiaohongshu_vendor_root", lambda: vendor_root)


def test_xiaohongshu_share_link_enters_the_manual_ingest_contract():
    parsed = parse_share_text("分享一篇笔记 https://www.xiaohongshu.com/explore/abc123?xsec_token=token")

    assert parsed is not None
    assert parsed.platform == "xiaohongshu"
    assert parsed.url.startswith("https://www.xiaohongshu.com/explore/abc123")


def test_xiaohongshu_short_link_enters_the_manual_ingest_contract():
    parsed = parse_share_text("打开小红书看看 http://xhslink.com/a/AbC123。")

    assert parsed is not None
    assert parsed.platform == "xiaohongshu"
    assert parsed.url == "http://xhslink.com/a/AbC123"


def test_xiaohongshu_search_result_link_enters_all_manual_ingest_contracts():
    url = "https://www.xiaohongshu.com/search_result/69a2a73d000000001600a4a9?xsec_token=test-token&xsec_source="
    parsed = parse_share_text(f"搜索页分享 {url}")

    assert parsed is not None
    assert parsed.platform == "xiaohongshu"
    assert parsed.url == url
    assert extract_supported_links(f"剪贴板内容 {url}") == [url]
    assert resolve_xiaohongshu_share_url(url) == url
    assert normalize_note_url(url).startswith(
        "https://www.xiaohongshu.com/explore/69a2a73d000000001600a4a9"
    )


def test_xiaohongshu_short_link_only_follows_trusted_redirects():
    target = "https://www.xiaohongshu.com/explore/abc123?xsec_token=token"

    class Response:
        status_code = 302
        headers = {"location": target}

    resolved = resolve_xiaohongshu_share_url(
        "https://xhslink.com/a/AbC123",
        request_get=lambda *_args, **_kwargs: Response(),
    )

    assert resolved == target


def test_xiaohongshu_short_link_rejects_foreign_redirects():
    class Response:
        status_code = 302
        headers = {"location": "http://127.0.0.1:8000/private"}

    try:
        resolve_xiaohongshu_share_url(
            "https://xhslink.com/a/AbC123",
            request_get=lambda *_args, **_kwargs: Response(),
        )
    except XiaohongshuShareLinkError as exc:
        assert "不受信任" in str(exc)
    else:
        raise AssertionError("foreign redirects must be rejected")


def test_xiaohongshu_provider_uses_note_id_for_deduplication_without_network():
    provider = XiaohongshuProvider()
    resolved = provider.resolve("https://www.xiaohongshu.com/explore/abc123?xsec_token=token&xsec_source=pc_user")

    assert resolved.provider == "xiaohongshu"
    assert resolved.content_type == "article"
    assert resolved.canonical_source_id == "abc123"
    assert resolved.title == "小红书图文 · abc123"


def test_xiaohongshu_note_without_a_title_uses_its_description_before_a_generic_placeholder():
    note = xiaohongshu_client._note_from_raw(
        {
            "id": "note-id-123456",
            "note_card": {
                "title": "   ",
                "desc": "  这是一条没有标题、但有正文的小红书笔记。  ",
            },
        },
        source_url="https://www.xiaohongshu.com/explore/note-id-123456?xsec_token=token",
    )

    assert note.title == "这是一条没有标题、但有正文的小红书笔记。"


def test_placeholder_repair_keeps_legacy_rows_identifiable_and_routes_xhs_to_articles(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    with connect() as connection:
        connection.execute(
            """INSERT INTO content_items (
                id, content_type, source_provider, source_url, canonical_source_id,
                title, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'inbox', ?, ?)""",
            (
                "legacy-xhs", "video", "xiaohongshu",
                "https://www.xiaohongshu.com/explore/note-123?xsec_token=token",
                "note-123", "无标题小红书笔记", "2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            """INSERT INTO content_items (
                id, content_type, source_provider, source_url, canonical_source_id,
                title, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'inbox', ?, ?)""",
            (
                "legacy-video", "video", "bilibili",
                "https://www.bilibili.com/video/BV123", "BV123", "未命名视频",
                "2026-08-01T00:00:00+00:00", "2026-08-01T00:00:00+00:00",
            ),
        )
        _migration_092_repair_placeholder_content_items(connection)
        rows = connection.execute(
            "SELECT id, content_type, title FROM content_items WHERE id IN ('legacy-xhs', 'legacy-video') ORDER BY id"
        ).fetchall()

    assert [(row["id"], row["content_type"], row["title"]) for row in rows] == [
        ("legacy-video", "video", "B站视频 · BV123"),
        ("legacy-xhs", "article", "小红书图文 · note-123"),
    ]


def test_xiaohongshu_normalization_keeps_access_token_but_stabilizes_the_origin():
    url = normalize_note_url("https://xiaohongshu.com/explore/abc123?xsec_token=token")

    assert url == "https://www.xiaohongshu.com/explore/abc123?xsec_token=token&xsec_source=pc_search"
    assert note_id_from_url(url) == "abc123"


def test_xiaohongshu_description_renders_only_safe_topic_badges():
    rendered = xiaohongshu_ingest.render_xiaohongshu_description_html(
        "正文 #效率工具 #VMark[话题]# <script>bad()</script> C# 不应成为标签"
    )
    normalized = normalize_article_html(rendered)

    assert '<span class="article-xhs-tag">#效率工具</span>' in normalized
    assert '<span class="article-xhs-tag">#VMark</span>' in normalized
    assert "[话题]" not in normalized
    assert "<script" not in normalized
    assert "C# 不应成为标签" in normalized


def test_xiaohongshu_favorites_are_incremental_and_queue_background_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    note = XiaohongshuNote(
        note_id="note-1",
        source_url="https://www.xiaohongshu.com/explore/note-1?xsec_token=token",
        title="一篇图文", author="作者", author_url="", avatar_url="", description="正文",
        image_urls=("https://example.com/cover.jpg",), published_at="", tags=(), stats={}, ip_location="",
    )
    monkeypatch.setattr("services.xiaohongshu_client.fetch_my_favorites", lambda *, limit: [note])
    requests = []
    monkeypatch.setattr(
        xiaohongshu_ingest.task_manager,
        "create",
        lambda request: requests.append(request) or SimpleNamespace(task_id=f"task-{len(requests)}"),
    )

    first = xiaohongshu_ingest.sync_xiaohongshu_favorites(auto_analyze=True)
    second = xiaohongshu_ingest.sync_xiaohongshu_favorites(source_id=first["source_id"])
    source = xiaohongshu_ingest.get_xiaohongshu_favorite_source()

    assert first["created_count"] == 1
    assert first["task_ids"] == ["task-1"]
    assert second["created_count"] == 0
    assert source and source["next_sync_at"] and source["enabled"] is True


def test_xiaohongshu_favorites_refresh_an_existing_note_access_token(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    tokens = iter(("old-token", "new-token"))

    def favorites(*, limit):
        token = next(tokens)
        return [
            XiaohongshuNote(
                note_id="note-1",
                source_url=f"https://www.xiaohongshu.com/explore/note-1?xsec_token={token}",
                title="一篇图文", author="作者", author_url="", avatar_url="", description="正文",
                image_urls=(), published_at="", tags=(), stats={}, ip_location="",
            )
        ]

    monkeypatch.setattr("services.xiaohongshu_client.fetch_my_favorites", favorites)

    first = xiaohongshu_ingest.sync_xiaohongshu_favorites(auto_analyze=False)
    second = xiaohongshu_ingest.sync_xiaohongshu_favorites(source_id=first["source_id"])

    with connect() as connection:
        source_url = connection.execute(
            "SELECT source_url FROM content_items WHERE id=?",
            (first["content_item_ids"][0],),
        ).fetchone()["source_url"]
    assert second["created_count"] == 0
    assert "xsec_token=new-token" in source_url


def test_xiaohongshu_cookie_status_is_safe_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))

    status = xiaohongshu_cookie_status(probe=True)

    assert status["configured"] is False
    assert status["state"] == "missing"


def test_clipboard_recognizes_xiaohongshu_image_note_links():
    url = "https://www.xiaohongshu.com/explore/6a666e2b000000001c0108b4?xsec_token=token&xsec_source=pc_feed"

    assert extract_supported_links(f"看看这个 {url}") == [url]


def test_clipboard_recognizes_xiaohongshu_share_short_links():
    url = "http://xhslink.com/a/AbC123"

    assert extract_supported_links(f"复制后打开小红书 {url}。") == [url]


def test_xiaohongshu_short_link_is_expanded_before_inbox_provider_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    short_url = "https://xhslink.com/a/AbC123"
    full_url = "https://www.xiaohongshu.com/explore/abc123?xsec_token=token"
    monkeypatch.setattr("services.inbox.resolve_xiaohongshu_share_url", lambda _url: full_url)

    captured = capture_link_to_inbox(short_url)

    assert captured.error is None
    assert captured.item is not None
    assert captured.item.source_provider == "xiaohongshu"
    assert captured.item.source_url == normalize_note_url(full_url)


def test_telegram_queues_xiaohongshu_share_short_links(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    monkeypatch.setattr(TelegramWatcher, "_restore_saved_settings", lambda _self: None)
    monkeypatch.setattr("services.telegram_watcher.manual_collection_settings", lambda: {"auto_summarize": True})
    monkeypatch.setattr("services.telegram_watcher.save_telegram_watcher_checkpoint", lambda _update_id: None)
    requests = []
    monkeypatch.setattr(
        "services.telegram_watcher.task_manager.create",
        lambda request: requests.append(request) or SimpleNamespace(task_id="task-xhs"),
    )
    watcher = TelegramWatcher()
    watcher._bot_token = "test-token"
    watcher._allowed_user_ids = {100}
    replies = []
    monkeypatch.setattr(watcher, "_send_message", lambda _chat_id, text: replies.append(text))

    events = watcher._handle_updates(
        [{
            "update_id": 1,
            "message": {
                "message_id": 2,
                "text": "看看这个 https://xhslink.com/a/AbC123",
                "from": {"id": 100},
                "chat": {"id": 100},
            },
        }]
    )

    assert len(events) == 1
    assert events[0].task_id == "task-xhs"
    assert requests[0].share_text == "https://xhslink.com/a/AbC123"
    assert requests[0].execution_mode == "background"
    assert replies == ["已加入处理队列：https://xhslink.com/a/AbC123"]


def test_openclaw_mcp_declares_xiaohongshu_ingest_support():
    from mcp_server import IngestLinkInput, knowledgehub_ingest_link

    assert "Xiaohongshu" in str(IngestLinkInput.model_fields["text"].description)
    assert "Xiaohongshu" in str(knowledgehub_ingest_link.__doc__)


def test_direct_xiaohongshu_task_promotes_to_article_before_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    url = "https://www.xiaohongshu.com/explore/6a666e2b000000001c0108b4?xsec_token=token&xsec_source=pc_feed"
    monkeypatch.setattr("services.xiaohongshu_ingest.capture_xiaohongshu_note", lambda _item_id: {})
    monkeypatch.setattr(
        "services.pipeline_runner.load_content_source_text",
        lambda item_id: ContentSourceText(item_id, "图文", url, "可用于总结的图文正文", "article"),
    )
    monkeypatch.setattr("services.pipeline_runner.download_video", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("小红书不能进入下载器")))

    response = run_pipeline_sync(share_text=url, processing_mode="transcript")

    assert response.success is True
    assert response.platform == "xiaohongshu"
    assert "xsec_token=token" not in "\n".join(log.message for log in response.logs)
    with connect() as connection:
        row = connection.execute("SELECT content_type FROM content_items WHERE id=?", (response.content_item_id,)).fetchone()
    assert row["content_type"] == "article"


def test_existing_xiaohongshu_video_item_is_repaired_to_article(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    url = "https://www.xiaohongshu.com/explore/6a666e2b000000001c0108b4?xsec_token=token&xsec_source=pc_feed"
    first = capture_link_to_inbox(url)
    assert first.item is not None
    with connect() as connection:
        connection.execute("UPDATE content_items SET content_type='video' WHERE id=?", (first.item.id,))
        connection.commit()

    repaired = capture_link_to_inbox(url)

    assert repaired.duplicate is True
    assert repaired.item and repaired.item.content_type == "article"


def test_retry_repairs_a_legacy_xiaohongshu_video_item_before_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    url = "https://www.xiaohongshu.com/explore/6a666e2b000000001c0108b4?xsec_token=token&xsec_source=pc_feed"
    first = capture_link_to_inbox(url)
    assert first.item is not None
    with connect() as connection:
        connection.execute("UPDATE content_items SET content_type='video' WHERE id=?", (first.item.id,))
        connection.commit()
    monkeypatch.setattr("services.xiaohongshu_ingest.capture_xiaohongshu_note", lambda _item_id: {})
    monkeypatch.setattr(
        "services.pipeline_runner.load_content_source_text",
        lambda item_id: ContentSourceText(item_id, "图文", url, "可用于总结的图文正文", "article"),
    )
    monkeypatch.setattr(
        "services.pipeline_runner.download_video",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("旧小红书图文不能进入下载器")),
    )

    response = run_pipeline_sync(content_item_id=first.item.id, processing_mode="transcript")

    assert response.success is True
    with connect() as connection:
        row = connection.execute("SELECT content_type FROM content_items WHERE id=?", (first.item.id,)).fetchone()
    assert row["content_type"] == "article"


def test_duplicate_xiaohongshu_capture_refreshes_the_access_token(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    old_url = "https://www.xiaohongshu.com/explore/note-1?xsec_token=old-token"
    new_url = "https://www.xiaohongshu.com/explore/note-1?xsec_token=new-token"

    first = capture_link_to_inbox(old_url)
    legacy_cache = cache_dir_for_url(normalize_note_url(old_url))
    write_cache_meta(legacy_cache, {"article_info": {"body_text": "已经抓取的正文"}})
    refreshed = capture_link_to_inbox(new_url)

    assert first.item is not None
    assert refreshed.duplicate is True
    assert refreshed.item and refreshed.item.id == first.item.id
    assert refreshed.item.source_url == normalize_note_url(new_url)
    assert read_cache_meta(xiaohongshu_cache_dir(refreshed.item.source_url))["article_info"]["body_text"] == "已经抓取的正文"


def test_xiaohongshu_source_text_does_not_treat_an_empty_note_as_analysis_input():
    assert xiaohongshu_ingest._source_text("", [{"index": 1, "ocr_text": ""}]) == ""
    assert "图片里的字" in xiaohongshu_ingest._source_text(
        "",
        [{"index": 1, "ocr_text": "图片里的字"}],
    )
