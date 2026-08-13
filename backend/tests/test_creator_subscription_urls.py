from datetime import datetime, timezone
import sqlite3

import pytest

from services.creator_sync import (
    CreatorPreview,
    CreatorSyncError,
    CreatorVideo,
    _canonical_creator_url,
    _next_bilibili_favorites_page_url,
    _parse_creator_url,
    _parse_page,
    _personal_douyin_creator_name,
    _preview_within_date_range,
    _recoverable_creator_items,
    _should_continue_creator_capture,
    _source_section_label,
    _unseen_prefix_before_known_item,
)
from services.database import (
    _migration_090_unify_video_source_subscriptions,
    _migration_091_unify_xiaohongshu_favorite_subscription,
)


def test_douyin_likes_and_favorites_urls_have_distinct_subscription_identities():
    likes = _parse_creator_url("https://www.douyin.com/user/MS4wLjABAAAA?showTab=like")
    favorites = _parse_creator_url(
        "https://www.douyin.com/user/MS4wLjABAAAA?showTab=favorite_collection&showSubTab=favorite_folder"
    )

    assert likes == ("douyin", "likes", "MS4wLjABAAAA")
    assert favorites == ("douyin", "favorites", "MS4wLjABAAAA")
    assert "showTab=like" in _canonical_creator_url(*likes)
    assert "favorite_folder" in _canonical_creator_url(*favorites)


def test_personal_bilibili_collections_remain_supported():
    assert _parse_creator_url("https://space.bilibili.com/42/favlist?fid=100") == (
        "bilibili",
        "favorites",
        "42:100",
    )
    assert _parse_creator_url("https://space.bilibili.com/42/like") == ("bilibili", "likes", "42:liked")
    assert _source_section_label("favorites", "") == "我的收藏"
    assert _source_section_label("likes", "") == "我的喜欢"


def test_bilibili_favorites_uses_the_next_api_page_instead_of_only_scrolling_the_first_page():
    next_url = _next_bilibili_favorites_page_url(
        "https://api.bilibili.com/x/v3/fav/resource/list?media_id=7&pn=1&ps=40&keyword=&order=mtime"
    )

    assert "pn=2" in next_url
    assert "ps=40" in next_url
    assert _next_bilibili_favorites_page_url("https://api.bilibili.com/x/space/wbi/arc/search?pn=1") == ""

    _videos, _creator, _cursor, has_more = _parse_page(
        {"data": {"medias": [{"bvid": "BV1xx411c7mD", "title": "收藏"}], "has_more": False}},
        provider="bilibili",
    )
    assert has_more is False


def test_incremental_creator_capture_stops_at_persisted_source_membership():
    page = {"data": {"medias": [{"bvid": "BV1anchor", "title": "已订阅作品"}], "has_more": True}}

    assert not _should_continue_creator_capture(
        [page], provider="bilibili", limit=3600, watermark=None, known_item_ids={"BV1anchor"}
    )


def test_incremental_creator_capture_never_silently_truncates_before_anchor():
    page = {"data": {"medias": [{"bvid": "BV1new", "title": "新作品"}], "has_more": True}}

    with pytest.raises(CreatorSyncError, match="尚未找到上次订阅的作品边界"):
        _should_continue_creator_capture(
            [page] * 60, provider="bilibili", limit=3600, watermark=None, known_item_ids={"BV1anchor"}
        )


def test_incremental_capture_fails_closed_when_the_last_page_has_no_saved_anchor():
    page = {"data": {"medias": [{"bvid": "BV1old", "title": "历史作品"}], "has_more": False}}

    with pytest.raises(CreatorSyncError, match="未找到上次订阅的作品边界"):
        _should_continue_creator_capture(
            [page], provider="bilibili", limit=3600, watermark=None, known_item_ids={"BV1anchor"}
        )


def test_incremental_sync_keeps_only_the_prefix_before_the_first_saved_work():
    videos = [
        CreatorVideo("douyin", "new-1", "https://example.test/new-1", "新作品 1"),
        CreatorVideo("douyin", "new-2", "https://example.test/new-2", "新作品 2"),
        CreatorVideo("douyin", "anchor", "https://example.test/anchor", "已订阅作品"),
        CreatorVideo("douyin", "old-1", "https://example.test/old-1", "更早作品"),
    ]

    assert [video.canonical_id for video in _unseen_prefix_before_known_item(videos, {"anchor"})] == ["new-1", "new-2"]
    with pytest.raises(CreatorSyncError, match="未找到上次订阅的作品边界"):
        _unseen_prefix_before_known_item(videos, {"missing-anchor"})


def test_personal_douyin_source_name_comes_from_the_signed_in_account_page():
    assert _personal_douyin_creator_name("白云苍狗的抖音 - 抖音") == "白云苍狗"
    assert _personal_douyin_creator_name("抖音") == ""


def test_retry_failed_creator_items_is_scoped_to_current_subscription_only():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE content_items (
            id TEXT PRIMARY KEY, canonical_source_id TEXT, source_url TEXT,
            title TEXT, status TEXT, deleted_at TEXT, published_at TEXT, created_at TEXT
        );
        CREATE TABLE creator_source_items (
            source_id TEXT, content_item_id TEXT, remote_item_id TEXT
        );
        CREATE TABLE tasks (content_item_id TEXT, status TEXT);
        """
    )
    connection.executemany(
        "INSERT INTO content_items VALUES (?, ?, ?, ?, ?, NULL, NULL, '2026-08-01T00:00:00+00:00')",
        [
            ("failed-current", "BV-current", "https://example.test/current", "当前订阅失败项", "failed"),
            ("inbox-current", "BV-inbox", "https://example.test/inbox", "当前订阅收件箱", "inbox"),
            ("failed-other", "BV-other", "https://example.test/other", "其他订阅失败项", "failed"),
        ],
    )
    connection.executemany(
        "INSERT INTO creator_source_items VALUES (?, ?, ?)",
        [("source-current", "failed-current", "BV-current"), ("source-current", "inbox-current", "BV-inbox"), ("source-other", "failed-other", "BV-other")],
    )

    rows = _recoverable_creator_items(connection, source_id="source-current", limit=500)

    assert [row["id"] for row in rows] == ["failed-current"]


def test_xiaohongshu_collect_profile_link_uses_the_same_personal_source_contract():
    assert _parse_creator_url(
        "https://www.xiaohongshu.com/user/profile/abc123?tab=collect"
    ) == ("xiaohongshu", "favorites", "abc123")
    assert _canonical_creator_url("xiaohongshu", "favorites", "abc123") == (
        "https://www.xiaohongshu.com/user/profile/abc123?tab=collect"
    )


def test_xiaohongshu_fav_profile_link_uses_the_same_personal_source_contract():
    assert _parse_creator_url(
        "https://www.xiaohongshu.com/user/profile/636f8603000000001f01b9cb?tab=fav&subTab=note"
    ) == ("xiaohongshu", "favorites", "636f8603000000001f01b9cb")


def test_xiaohongshu_preview_uses_the_creator_contract(monkeypatch):
    from services.creator_sync import preview_creator_source
    from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable

    with pytest.raises(XiaohongshuCollectorUnavailable, match="主动导入单篇图文"):
        preview_creator_source(
            source_url="https://www.xiaohongshu.com/user/profile/self-id?tab=collect",
            limit=50,
            allow_personal_sources=True,
        )


def test_xiaohongshu_preview_accepts_a_profile_link_alias(monkeypatch):
    from services.creator_sync import preview_creator_source
    from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable

    with pytest.raises(XiaohongshuCollectorUnavailable, match="创作者同步暂未开放"):
        preview_creator_source(
            source_url="https://www.xiaohongshu.com/user/profile/profile-page-alias?tab=fav&subTab=note",
            limit=50,
            allow_personal_sources=True,
        )


def test_invalid_creator_date_window_is_rejected_before_browser_capture():
    from services.creator_sync import preview_creator_source

    with pytest.raises(CreatorSyncError, match="结束日期不能早于起始日期"):
        preview_creator_source(
            source_url="https://www.douyin.com/user/MS4wLjABAAAA",
            published_after="2026-08-02",
            published_before="2026-08-01",
        )


def test_date_range_is_inclusive_and_hides_undated_items_when_requested():
    preview = CreatorPreview(
        provider="douyin",
        source_kind="profile",
        source_url="https://www.douyin.com/user/one",
        creator_key="one",
        creator_name="创作者",
        videos=[
            CreatorVideo("douyin", "old", "https://example.test/old", "old", published_at="2026-07-31T23:00:00+00:00"),
            CreatorVideo("douyin", "inside", "https://example.test/inside", "inside", published_at="2026-08-01T12:00:00+00:00"),
            CreatorVideo("douyin", "new", "https://example.test/new", "new", published_at="2026-08-02T00:00:00+00:00"),
            CreatorVideo("douyin", "unknown", "https://example.test/unknown", "unknown"),
        ],
    )

    result = _preview_within_date_range(
        preview,
        after=datetime(2026, 8, 1, tzinfo=timezone.utc),
        before=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )

    assert [video.canonical_id for video in result.videos] == ["inside"]


def test_legacy_douyin_favorites_migrate_once_and_disable_the_old_scheduler_row():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE creator_sources (
            id TEXT PRIMARY KEY, provider TEXT, source_url TEXT, source_kind TEXT,
            creator_key TEXT, creator_name TEXT, source_identity TEXT UNIQUE,
            library_folder_id TEXT, enabled INTEGER, auto_process INTEGER,
            processing_mode TEXT, sync_interval_minutes INTEGER, sync_limit INTEGER,
            queue_limit INTEGER, last_sync_at TEXT, next_sync_at TEXT,
            last_seen_published_at TEXT, last_error TEXT,
            consecutive_failure_count INTEGER, last_discovered_count INTEGER,
            last_created_count INTEGER, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE content_items (id TEXT PRIMARY KEY);
        CREATE TABLE favorite_sources (
            id TEXT PRIMARY KEY, provider TEXT, source_url TEXT, title TEXT,
            library_folder_id TEXT, enabled INTEGER, auto_analyze INTEGER,
            sync_interval_minutes INTEGER, sync_limit INTEGER, last_sync_at TEXT,
            next_sync_at TEXT, last_error TEXT, consecutive_failure_count INTEGER,
            last_discovered_count INTEGER, last_created_count INTEGER,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE favorite_source_items (
            source_id TEXT, content_item_id TEXT, remote_video_id TEXT, created_at TEXT
        );
        CREATE TABLE favorite_sync_runs (
            id TEXT PRIMARY KEY, source_id TEXT, status TEXT, message TEXT,
            discovered_count INTEGER, created_count INTEGER, created_at TEXT
        );
        CREATE TABLE creator_sync_runs (
            id TEXT PRIMARY KEY, source_id TEXT, status TEXT, error_category TEXT,
            message TEXT, discovered_count INTEGER, created_count INTEGER, created_at TEXT
        );
        """
    )
    connection.execute("INSERT INTO content_items VALUES ('content-1')")
    connection.execute(
        """INSERT INTO favorite_sources VALUES
           ('legacy-douyin', 'douyin', 'https://www.douyin.com/user/self?showTab=favorite_collection',
            '我的抖音收藏', 'folder-douyin', 1, 1, 360, 5, NULL, NULL, NULL, 0, 0, 0, 'now', 'now')"""
    )
    connection.execute("INSERT INTO favorite_source_items VALUES ('legacy-douyin', 'content-1', '123', 'now')")
    connection.execute("INSERT INTO favorite_sync_runs VALUES ('run-1', 'legacy-douyin', 'success', '', 1, 1, 'now')")

    _migration_090_unify_video_source_subscriptions(connection)

    migrated = connection.execute("SELECT * FROM creator_sources WHERE id='legacy-douyin'").fetchone()
    assert migrated["source_kind"] == "favorites"
    assert migrated["source_identity"] == "douyin:favorites:self"
    assert connection.execute("SELECT enabled FROM favorite_sources WHERE id='legacy-douyin'").fetchone()[0] == 0
    assert connection.execute("SELECT content_item_id FROM creator_source_items").fetchone()[0] == "content-1"
    assert connection.execute("SELECT status FROM creator_sync_runs").fetchone()[0] == "succeeded"


def test_legacy_xiaohongshu_favorites_migrate_into_creator_sources():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE creator_sources (
            id TEXT PRIMARY KEY, provider TEXT, source_url TEXT, source_kind TEXT,
            creator_key TEXT, creator_name TEXT, source_identity TEXT UNIQUE,
            library_folder_id TEXT, enabled INTEGER, auto_process INTEGER,
            processing_mode TEXT, sync_interval_minutes INTEGER, sync_limit INTEGER,
            queue_limit INTEGER, last_sync_at TEXT, next_sync_at TEXT,
            last_seen_published_at TEXT, last_error TEXT,
            consecutive_failure_count INTEGER, last_discovered_count INTEGER,
            last_created_count INTEGER, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE content_items (id TEXT PRIMARY KEY);
        CREATE TABLE creator_source_items (
            source_id TEXT, content_item_id TEXT, remote_item_id TEXT, created_at TEXT,
            PRIMARY KEY(source_id, remote_item_id)
        );
        CREATE TABLE xiaohongshu_favorite_sources (
            id TEXT PRIMARY KEY, title TEXT, library_folder_id TEXT, enabled INTEGER,
            auto_analyze INTEGER, sync_interval_minutes INTEGER, sync_limit INTEGER,
            last_sync_at TEXT, next_sync_at TEXT, last_error TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE xiaohongshu_favorite_items (
            source_id TEXT, content_item_id TEXT, note_id TEXT, created_at TEXT
        );
        """
    )
    connection.execute("INSERT INTO content_items VALUES ('xhs-content')")
    connection.execute(
        "INSERT INTO xiaohongshu_favorite_sources VALUES ('legacy-xhs', '我的小红书收藏', 'xhs-folder', 1, 1, 360, 50, NULL, NULL, NULL, 'now', 'now')"
    )
    connection.execute("INSERT INTO xiaohongshu_favorite_items VALUES ('legacy-xhs', 'xhs-content', 'note-1', 'now')")

    _migration_091_unify_xiaohongshu_favorite_subscription(connection)

    migrated = connection.execute("SELECT * FROM creator_sources WHERE id='legacy-xhs'").fetchone()
    assert migrated["provider"] == "xiaohongshu"
    assert migrated["source_kind"] == "favorites"
    assert connection.execute("SELECT enabled FROM xiaohongshu_favorite_sources WHERE id='legacy-xhs'").fetchone()[0] == 0
    assert connection.execute("SELECT remote_item_id FROM creator_source_items").fetchone()[0] == "note-1"
