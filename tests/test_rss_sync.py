import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.cache import cache_dir_for_url, read_cache_meta
from services.article_fetcher import ArticleFetchResult, fetch_rss_article
from services.content_source_text import inspect_content_text_readiness, load_content_source_text
from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.content_index import repair_rss_source_folders
from services.rss_sync import RssEntry, RssPreview, _save_and_sync
from routers.qa import _require_regenerable_content


def test_rss_sync_creates_source_folder_content_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    preview = RssPreview(
        feed_url="https://example.com/feed.xml",
        title="示例订阅",
        description="测试订阅",
        site_url="https://example.com",
        entries=[
            RssEntry(
                identity="article-1",
                title="第一篇 RSS 文章",
                url="https://example.com/articles/1",
                published_at="2026-07-19T10:00:00Z",
                author="测试作者",
                body_html="<h1>第一篇 RSS 文章</h1><p>正文内容。</p>",
                body_text="第一篇 RSS 文章\n正文内容。",
                source_summary="正文摘要",
            )
        ],
    )

    result = _save_and_sync(preview, source_id=None, sync_interval_minutes=180)

    assert result["created_count"] == 1
    assert result["source"]["sync_interval_minutes"] == 180
    with connect() as connection:
        item = connection.execute("SELECT * FROM content_items WHERE source_provider='rss'").fetchone()
        folder = connection.execute("SELECT * FROM library_folders WHERE id=?", (item["library_folder_id"],)).fetchone()
    assert item["content_type"] == "article"
    assert item["status"] == "to_read"
    assert folder["name"] == "示例订阅"
    assert read_cache_meta(cache_dir_for_url(item["source_url"]))["article_info"]["body_text"] == "第一篇 RSS 文章\n正文内容。"
    source = load_content_source_text(item["id"])
    assert source.text == "第一篇 RSS 文章\n正文内容。"
    assert _require_regenerable_content(item["id"]) == "article"
    with connect() as connection:
        item_record = ContentRepository(connection).get_content_item(item["id"])
    assert inspect_content_text_readiness(item_record).status == "ready"


def test_rss_sync_is_incremental_for_same_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    entry = RssEntry("entry", "文章", "https://example.com/article", None, "", "<p>正文</p>", "正文", "")
    preview = RssPreview("https://example.com/feed.xml", "示例", "", "", [entry])
    first = _save_and_sync(preview, source_id=None, sync_interval_minutes=180)
    second = _save_and_sync(preview, source_id=first["source"]["id"], sync_interval_minutes=180)

    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert second["duplicate_count"] == 1


def test_summary_only_rss_entry_fetches_and_replaces_cached_body(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    monkeypatch.setattr("services.article_ingest_preparation.enqueue_article_source_preparation", lambda _item_id: True)
    initialize_database()
    entry = RssEntry(
        "summary-only", "摘要文章", "https://example.com/article", None, "", "<p>RSS 摘要</p>", "RSS 摘要", "RSS 摘要", True,
    )
    result = _save_and_sync(
        RssPreview("https://example.com/feed.xml", "示例", "", "", [entry]),
        source_id=None,
        sync_interval_minutes=180,
    )
    with connect() as connection:
        item = connection.execute("SELECT * FROM content_items WHERE source_provider='rss'").fetchone()

    calls = []

    def fetch_original(url, platform, **_kwargs):
        calls.append((url, platform))
        return ArticleFetchResult(
            url=url,
            platform="rss",
            title="原文标题",
            body_text="这是从文章链接取得的完整原文。",
            body_html="<article><p>这是从文章链接取得的完整原文。</p></article>",
        )

    monkeypatch.setattr("services.content_source_text.fetch_article", fetch_original)
    source = load_content_source_text(item["id"], include_image_ocr=False)
    metadata = read_cache_meta(cache_dir_for_url(item["source_url"]))["article_info"]

    assert result["created_count"] == 1
    assert source.text == "这是从文章链接取得的完整原文。"
    assert calls == [("https://example.com/article", "rss")]
    assert metadata["rss_body_source"] == "web_full"
    assert metadata["rss_full_text_status"] == "fetched"


def test_summary_only_rss_entry_keeps_summary_after_original_fetch_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    monkeypatch.setattr("services.article_ingest_preparation.enqueue_article_source_preparation", lambda _item_id: True)
    initialize_database()
    entry = RssEntry(
        "summary-fallback", "摘要文章", "https://example.com/article", None, "", "<p>保留的摘要</p>", "保留的摘要", "保留的摘要", True,
    )
    _save_and_sync(
        RssPreview("https://example.com/feed.xml", "示例", "", "", [entry]),
        source_id=None,
        sync_interval_minutes=180,
    )
    with connect() as connection:
        item = connection.execute("SELECT * FROM content_items WHERE source_provider='rss'").fetchone()

    calls = []

    def fail_fetch(*_args, **_kwargs):
        calls.append(True)
        raise ValueError("站点拒绝访问")

    monkeypatch.setattr("services.content_source_text.fetch_article", fail_fetch)
    source = load_content_source_text(item["id"], include_image_ocr=False)
    second_source = load_content_source_text(item["id"], include_image_ocr=False)
    metadata = read_cache_meta(cache_dir_for_url(item["source_url"]))["article_info"]

    assert source.text == "保留的摘要"
    assert second_source.text == "保留的摘要"
    assert calls == [True]
    assert metadata["rss_full_text_status"] == "failed"


def test_rss_original_page_extracts_article_content_without_fetching_navigation(monkeypatch):
    monkeypatch.setattr(
        "services.article_fetcher._fetch_rss_article_html",
        lambda _url: (
            "https://example.com/article",
            "<html><head><title>页面标题</title></head><body><nav>导航</nav><article><h1>原文标题</h1><p>第一段。</p><p>第二段。</p></article><footer>页脚</footer></body></html>",
        ),
    )

    result = fetch_rss_article("https://example.com/article", include_image_ocr=False)

    assert result.title == "原文标题"
    assert result.body_text == "原文标题\n第一段。\n第二段。"


def test_rss_same_titled_sources_receive_distinct_child_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    first = _save_and_sync(
        RssPreview(
            "https://first.example.com/feed.xml", "同名订阅", "", "", 
            [RssEntry("first", "第一篇", "https://first.example.com/1", None, "", "<p>正文</p>", "正文", "")],
        ),
        source_id=None,
        sync_interval_minutes=180,
    )
    second = _save_and_sync(
        RssPreview(
            "https://second.example.com/feed.xml", "同名订阅", "", "", 
            [RssEntry("second", "第二篇", "https://second.example.com/1", None, "", "<p>正文</p>", "正文", "")],
        ),
        source_id=None,
        sync_interval_minutes=180,
    )

    with connect() as connection:
        root = connection.execute("SELECT id FROM library_folders WHERE name='RSS订阅' AND parent_folder_id IS NULL").fetchone()
        folders = connection.execute("SELECT id, name FROM library_folders WHERE parent_folder_id=?", (root["id"],)).fetchall()
        items = connection.execute("SELECT title, library_folder_id FROM content_items WHERE source_provider='rss' ORDER BY title").fetchall()

    assert first["source"]["library_folder_id"] != second["source"]["library_folder_id"]
    assert [folder["name"] for folder in folders] == ["同名订阅", "同名订阅 (2)"]
    assert {item["library_folder_id"] for item in items} == {first["source"]["library_folder_id"], second["source"]["library_folder_id"]}


def test_rss_folder_repair_separates_previously_shared_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", Path(tmp_path))
    initialize_database()
    first = _save_and_sync(
        RssPreview("https://first.example.com/feed.xml", "同名订阅", "", "", [RssEntry("first", "第一篇", "https://first.example.com/1", None, "", "<p>正文</p>", "正文", "")]),
        source_id=None, sync_interval_minutes=180,
    )
    second = _save_and_sync(
        RssPreview("https://second.example.com/feed.xml", "另一订阅", "", "", [RssEntry("second", "第二篇", "https://second.example.com/1", None, "", "<p>正文</p>", "正文", "")]),
        source_id=None, sync_interval_minutes=180,
    )
    shared_folder_id = first["source"]["library_folder_id"]
    with connect() as connection:
        connection.execute("UPDATE rss_sources SET library_folder_id=? WHERE id=?", (shared_folder_id, second["source"]["id"]))
        connection.execute(
            "UPDATE library_source_folder_bindings SET folder_id=? WHERE source_type='rss_source' AND source_key=?",
            (shared_folder_id, second["source"]["id"]),
        )
        connection.commit()

    assert repair_rss_source_folders() >= 1
    with connect() as connection:
        folders = connection.execute("SELECT library_folder_id FROM rss_sources ORDER BY feed_url").fetchall()
        second_item = connection.execute("SELECT library_folder_id FROM content_items WHERE title='第二篇'").fetchone()

    assert folders[0]["library_folder_id"] != folders[1]["library_folder_id"]
    assert second_item["library_folder_id"] == folders[1]["library_folder_id"]
