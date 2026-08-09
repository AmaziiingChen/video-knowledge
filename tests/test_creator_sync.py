from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from services import creator_sync
from services import creator_source_registry
from services.creator_sync import CreatorPreview, CreatorSyncError, CreatorVideo
from routers.creator_sources import _preview_response
from services.database import connect, initialize_database
from services.repository import ContentRepository


def test_preview_douyin_profile_uses_bundled_browser_reader(monkeypatch):
    expected = CreatorPreview(
        provider="douyin",
        source_kind="profile",
        source_url="https://www.douyin.com/user/MS4wLjABAAATest",
        creator_key="MS4wLjABAAATest",
        creator_name="测试作者",
        videos=[
            CreatorVideo(
                provider="douyin",
                canonical_id="741",
                source_url="https://www.douyin.com/video/741",
                title="第一条作品",
                cover_url="https://cover/1",
                duration_seconds=15.0,
                published_at="2023-11-14T22:13:20+00:00",
            )
        ],
    )
    calls = []
    monkeypatch.setattr(
        creator_sync,
        "_preview_douyin_profile_in_browser",
        lambda **kwargs: calls.append(kwargs) or expected,
    )

    preview = creator_sync.preview_creator_source(source_url=expected.source_url, limit=20)

    assert preview == expected
    assert calls == [
        {
            "source_url": expected.source_url,
            "creator_key": "MS4wLjABAAATest",
            "limit": 20,
            "cutoff": None,
            "known_item_ids": None,
        }
    ]


def test_creator_url_rejects_embedded_or_non_https_target_urls():
    for value in (
        "http://www.douyin.com/user/MS4wLjABAAATest",
        "https://example.com/?next=https://www.douyin.com/user/MS4wLjABAAATest",
        "https://www.douyin.com.evil.example/user/MS4wLjABAAATest",
    ):
        try:
            creator_sync._parse_creator_url(value)
        except CreatorSyncError:
            continue
        raise AssertionError(f"expected {value} to be rejected")


def test_bilibili_extended_source_urls_are_normalized_and_personal_sources_require_consent(monkeypatch):
    assert creator_sync._parse_creator_url("https://space.bilibili.com/42/upload/video") == ("bilibili", "profile", "42")
    assert creator_sync._canonical_creator_url("bilibili", "profile", "42") == "https://space.bilibili.com/42/upload/video"
    assert creator_sync._creator_capture_url(
        "https://space.bilibili.com/42", provider="bilibili", source_kind="profile", creator_key="42"
    ) == "https://space.bilibili.com/42/upload/video"
    assert creator_sync._parse_creator_url("https://space.bilibili.com/42/lists/88?type=series") == ("bilibili", "series", "42:88")
    assert creator_sync._parse_creator_url("https://space.bilibili.com/42/lists/88?type=season") == ("bilibili", "collection", "42:88")
    assert creator_sync._parse_creator_url("https://space.bilibili.com/42/channel/seriesdetail?sid=88") == ("bilibili", "channel_series", "42:88")
    assert creator_sync._parse_creator_url("https://space.bilibili.com/42/favlist?fid=88") == ("bilibili", "favorites", "42:88")

    monkeypatch.setattr(creator_sync, "_preview_bilibili_source_in_browser", lambda **_kwargs: None)
    try:
        creator_sync.preview_creator_source(source_url="https://space.bilibili.com/42/favlist?fid=88")
    except CreatorSyncError as exc:
        assert "明确授权" in str(exc)
    else:
        raise AssertionError("expected private source access to require consent")


def test_bilibili_profile_preview_opens_the_explicit_upload_tab(monkeypatch):
    calls = []
    expected = CreatorPreview(
        provider="bilibili",
        source_kind="profile",
        source_url="https://space.bilibili.com/42/upload/video",
        creator_key="42",
        creator_name="测试 UP 主",
        videos=[],
    )
    monkeypatch.setattr(
        creator_sync,
        "_preview_bilibili_source_in_browser",
        lambda **kwargs: calls.append(kwargs) or expected,
    )

    assert creator_sync.preview_creator_source(source_url="https://space.bilibili.com/42") is expected
    assert calls == [{
        "source_url": "https://space.bilibili.com/42/upload/video",
        "creator_key": "42",
        "source_kind": "profile",
        "limit": 20,
        "cutoff": None,
    }]


def test_douyin_compilation_tab_is_not_misclassified_as_a_plain_profile(monkeypatch):
    url = "https://www.douyin.com/user/tester?modal_id=741&showSubTab=compilation"
    assert creator_sync._parse_creator_url(url) == ("douyin", "profile_compilations", "tester")
    captured = []
    monkeypatch.setattr(
        creator_sync,
        "_preview_douyin_profile_in_browser",
        lambda **kwargs: captured.append(kwargs) or CreatorPreview("douyin", "profile_compilations", kwargs["source_url"], "tester", "作者", []),
    )

    creator_sync.preview_creator_source(source_url=url)

    assert captured[0]["source_url"] == "https://www.douyin.com/user/tester?showSubTab=compilation"
    assert captured[0]["compilation_view"] is True


def test_douyin_collection_entry_keeps_position_only_for_browser_navigation(monkeypatch):
    entry_url = "https://www.douyin.com/collection/7500918452492699688/1?previous_page=others_homepage"
    assert creator_sync._parse_creator_url(entry_url) == ("douyin", "collection", "7500918452492699688")
    captured = []
    monkeypatch.setattr(
        creator_sync,
        "_preview_douyin_collection_in_browser",
        lambda **kwargs: captured.append(kwargs) or CreatorPreview("douyin", "collection", kwargs["source_url"], kwargs["creator_key"], "作者", []),
    )

    creator_sync.preview_creator_source(source_url=entry_url)

    assert captured == [{
        "source_url": "https://www.douyin.com/collection/7500918452492699688",
        "capture_url": "https://www.douyin.com/collection/7500918452492699688/1",
        "creator_key": "7500918452492699688",
        "limit": 20,
        "cutoff": None,
    }]


def test_douyin_collection_prefers_project_browser_reader(monkeypatch):
    expected = CreatorPreview("douyin", "collection", "https://www.douyin.com/collection/741", "741", "测试作者", [])
    browser_calls = []
    monkeypatch.setattr(
        creator_sync,
        "_preview_douyin_collection_via_browser_capture",
        lambda **kwargs: browser_calls.append(kwargs) or expected,
    )
    preview = creator_sync._preview_douyin_collection_in_browser(
        source_url="https://www.douyin.com/collection/741", capture_url="https://www.douyin.com/collection/741/1",
        creator_key="741", limit=20, cutoff=None,
    )

    assert preview is expected
    assert browser_calls == [{
        "source_url": "https://www.douyin.com/collection/741",
        "capture_url": "https://www.douyin.com/collection/741/1",
        "creator_key": "741",
        "limit": 20,
        "cutoff": None,
    }]


def test_creator_preview_response_keeps_collection_and_creator_metadata():
    preview = CreatorPreview(
        provider="douyin", source_kind="collection", source_url="https://www.douyin.com/collection/741",
        creator_key="741", creator_name="测试作者", videos=[], creator_avatar_url="https://avatar",
        creator_description="简介", collection_id="741", collection_name="测试合集",
    )

    response = _preview_response(preview)

    assert response.collection_id == "741"
    assert response.collection_name == "测试合集"
    assert response.creator_avatar_url == "https://avatar"
    assert response.creator_description == "简介"


def test_douyin_browser_reader_parses_captured_profile_payload(monkeypatch):
    monkeypatch.setattr(
        creator_sync,
        "_capture_browser_pages",
        lambda **_kwargs: (
            [{"aweme_list": [{"aweme_id": "741", "desc": "第一条作品", "author": {"nickname": "测试作者"}, "video": {}}]}],
            "测试作者的抖音 - 抖音",
        ),
    )

    preview = creator_sync._preview_douyin_profile_in_browser(
        source_url="https://www.douyin.com/user/MS4wLjABAAATest",
        creator_key="MS4wLjABAAATest",
        limit=20,
        cutoff=None,
    )

    assert preview.creator_name == "测试作者"
    assert preview.videos[0].canonical_id == "741"


def test_creator_payload_parsers_keep_description_tags_and_interaction_stats():
    douyin = creator_sync._douyin_video(
        {
            "aweme_id": "741",
            "desc": "带话题的作品",
            "author": {"nickname": "测试作者"},
            "cha_list": [{"cha_name": "科技"}],
            "statistics": {"play_count": 100, "digg_count": 20, "collect_count": 3},
            "video": {},
        }
    )
    bilibili = creator_sync._bilibili_video(
        {
            "bvid": "BV1meta",
            "title": "B站作品",
            "description": "作品简介",
            "author": "测试 UP 主",
            "play": 88,
            "video_review": 9,
            "stat": {"like": 9, "favorite": 2},
        }
    )

    assert douyin and douyin.author_name == "测试作者"
    assert douyin.tags == ("科技",)
    assert douyin.stats == {"play": 100, "like": 20, "favorite": 3}
    assert bilibili and bilibili.description == "作品简介"
    assert bilibili.stats == {"play": 88, "like": 9, "favorite": 2, "comment": 9}


def test_douyin_browser_reader_allows_empty_incremental_result(monkeypatch):
    monkeypatch.setattr(
        creator_sync,
        "_capture_browser_pages",
        lambda **_kwargs: (
            [{"aweme_list": [{"aweme_id": "old", "desc": "旧作品", "create_time": 1, "video": {}}]}],
            "测试作者的抖音 - 抖音",
        ),
    )

    preview = creator_sync._preview_douyin_profile_in_browser(
        source_url="https://www.douyin.com/user/MS4wLjABAAATest",
        creator_key="MS4wLjABAAATest",
        limit=20,
        cutoff=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert preview.creator_name == "测试作者"
    assert preview.videos == []


def test_creator_capture_waits_for_variable_sized_douyin_pages():
    first_page = {
        "aweme_list": [{"aweme_id": str(index), "video": {}} for index in range(21)],
        "has_more": 1,
    }
    second_page = {
        "aweme_list": [{"aweme_id": str(index), "video": {}} for index in range(21, 39)],
        "has_more": 1,
    }
    final_page = {
        "aweme_list": [{"aweme_id": str(index), "video": {}} for index in range(39, 100)],
        "has_more": 0,
    }

    assert creator_sync._should_continue_creator_capture(
        [first_page, second_page], provider="douyin", limit=100, watermark=None
    )
    assert not creator_sync._should_continue_creator_capture(
        [first_page, second_page, final_page], provider="douyin", limit=100, watermark=None
    )


def test_creator_capture_stops_at_requested_item_limit_even_if_platform_has_more():
    pages = [
        {
            "aweme_list": [{"aweme_id": str(offset + index), "video": {}} for index in range(20)],
            "has_more": 1,
        }
        for offset in range(0, 100, 20)
    ]

    assert not creator_sync._should_continue_creator_capture(
        pages, provider="douyin", limit=100, watermark=None
    )


def test_creator_capture_has_a_hard_response_page_cap():
    page = {"aweme_list": [{"aweme_id": "1", "video": {}}], "has_more": 1}
    assert not creator_sync._should_continue_creator_capture(
        [page] * creator_sync.MAX_CREATOR_CAPTURE_RESPONSE_PAGES,
        provider="douyin",
        limit=creator_sync.MAX_CREATOR_SCAN_ITEMS,
        watermark=None,
    )


def test_parse_bilibili_browser_response_with_data_envelope():
    videos, creator_name, _cursor, has_more = creator_sync._parse_page(
        {
            "code": 0,
            "data": {
                "list": {
                    "vlist": [{"bvid": "BV1test", "title": "测试视频", "pic": "https://cover", "length": "01:15"}],
                    "page": {"pn": 1, "ps": 30, "count": 1},
                    "name": "测试 UP 主",
                }
            },
        },
        provider="bilibili",
    )

    assert creator_name == "测试 UP 主"
    assert has_more is False
    assert videos == [
        CreatorVideo("bilibili", "BV1test", "https://www.bilibili.com/video/BV1test", "测试视频", "https://cover", 75.0, None)
    ]


def test_bilibili_browser_reader_falls_back_to_signed_creator_list(monkeypatch):
    monkeypatch.setattr(
        creator_sync,
        "_capture_browser_pages",
        lambda **_kwargs: ([{"code": -403}], "测试 UP 主的个人空间"),
    )
    monkeypatch.setattr(
        "services.bilibili_creator_api.fetch_creator_profile_videos",
        lambda **_kwargs: ([{"bvid": "BV1fallback", "title": "回退作品"}], SimpleNamespace(name="测试 UP 主", avatar_url="", description="")),
    )

    preview = creator_sync._preview_bilibili_profile_in_browser(
        source_url="https://space.bilibili.com/42",
        creator_key="42",
        limit=10,
        cutoff=None,
    )

    assert preview.creator_name == "测试 UP 主"
    assert [video.canonical_id for video in preview.videos] == ["BV1fallback"]


def test_creator_sync_creates_creator_folder_deduplicates_and_queues_new_items(monkeypatch, tmp_path):
    # creator_sync reads database settings indirectly; patch the canonical object.
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="bilibili",
            source_kind="profile",
            source_url="https://space.bilibili.com/42",
            creator_key="42",
            creator_name="测试 UP 主",
            videos=[
                CreatorVideo("bilibili", "BV1test", "https://www.bilibili.com/video/BV1test", "测试视频"),
                CreatorVideo("bilibili", "BV2test", "https://www.bilibili.com/video/BV2test", "第二条视频"),
            ],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        queued = []
        monkeypatch.setattr(
            creator_sync.task_manager,
            "create",
            lambda request: queued.append(request) or SimpleNamespace(task_id=f"task-{len(queued)}"),
        )

        first = creator_sync.sync_creator_source(
            source_url=preview.source_url,
            limit=2,
            queue_limit=2,
        )
        second = creator_sync.sync_creator_source(
            source_url=preview.source_url,
            limit=2,
            queue_limit=2,
        )

        assert first.created_count == 2
        assert first.duplicate_count == 0
        assert first.task_ids == ["task-1", "task-2"]
        assert second.created_count == 0
        assert second.duplicate_count == 2
        assert len(queued) == 2
        initialize_database()
        with connect() as connection:
            folder = connection.execute("SELECT name FROM library_folders WHERE id = ?", (first.folder_id,)).fetchone()
            items = connection.execute(
                "SELECT canonical_source_id, library_folder_id FROM content_items ORDER BY canonical_source_id"
            ).fetchall()
        assert folder["name"] == "测试 UP 主"
        assert [(row["canonical_source_id"], row["library_folder_id"]) for row in items] == [
            ("BV1test", first.folder_id),
            ("BV2test", first.folder_id),
        ]
    finally:
        settings.data_dir = old_data_dir


def test_new_creator_subscription_uses_one_item_and_backfill_keeps_lightweight_scan(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="douyin",
            source_kind="collection",
            source_url="https://www.douyin.com/collection/1",
            creator_key="1",
            creator_name="测试合集",
            collection_id="1",
            videos=[
                CreatorVideo("douyin", "newest", "https://www.douyin.com/video/newest", "最新作品"),
                CreatorVideo("douyin", "older", "https://www.douyin.com/video/older", "历史作品"),
            ],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        monkeypatch.setattr(creator_sync.task_manager, "create", lambda _request: SimpleNamespace(task_id="task"))

        initial = creator_sync.sync_creator_source(source_url=preview.source_url)
        backfill = creator_sync.sync_creator_source(
            source_url=preview.source_url,
            limit=2,
            selected_video_ids=["older"],
        )

        assert initial.created_count == 1
        assert initial.content_item_ids
        assert backfill.created_count == 1
        with connect() as connection:
            row = connection.execute("SELECT sync_limit FROM creator_sources WHERE id=?", (initial.source_id,)).fetchone()
        assert row["sync_limit"] == 1
    finally:
        settings.data_dir = old_data_dir


def test_creator_sync_persists_platform_metadata(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            creator_avatar_url="https://avatar",
            creator_description="创作者简介",
            videos=[
                CreatorVideo(
                    "douyin", "741", "https://www.douyin.com/video/741", "作品", description="作品简介",
                    author_name="测试作者", tags=("科技",), stats={"like": 12, "play": 100},
                )
            ],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        monkeypatch.setattr(creator_sync.task_manager, "create", lambda _request: SimpleNamespace(task_id="task-1"))

        creator_sync.sync_creator_source(source_url=preview.source_url)

        with connect() as connection:
            row = connection.execute(
                "SELECT creator_name, work_description, tags_json, stats_json FROM creator_work_metadata"
            ).fetchone()
        assert tuple(row) == ("测试作者", "作品简介", '["科技"]', '{"like": 12, "play": 100}')
    finally:
        settings.data_dir = old_data_dir


def test_creator_sync_retries_items_not_queued_after_a_task_creation_error(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            videos=[
                CreatorVideo("douyin", "1", "https://www.douyin.com/video/1", "第一条"),
                CreatorVideo("douyin", "2", "https://www.douyin.com/video/2", "第二条"),
            ],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        calls = 0

        def create_task(_request):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("queue unavailable")
            return SimpleNamespace(task_id="task-1")

        monkeypatch.setattr(creator_sync.task_manager, "create", create_task)
        try:
            creator_sync.sync_creator_source(
                source_url=preview.source_url,
                limit=2,
                queue_limit=2,
            )
        except CreatorSyncError as exc:
            assert "创建处理任务失败" in str(exc)
        else:
            raise AssertionError("expected creator sync to fail")

        with connect() as connection:
            rows = connection.execute(
                "SELECT canonical_source_id, status FROM content_items ORDER BY canonical_source_id"
            ).fetchall()
        assert [(row["canonical_source_id"], row["status"]) for row in rows] == [("1", "processing")]

        retry = creator_sync.sync_creator_source(source_url=preview.source_url, limit=2, queue_limit=2)
        assert retry.created_count == 1
        assert retry.duplicate_count == 1
        with connect() as connection:
            rows = connection.execute(
                "SELECT canonical_source_id, status FROM content_items ORDER BY canonical_source_id"
            ).fetchall()
        assert [(row["canonical_source_id"], row["status"]) for row in rows] == [
            ("1", "processing"),
            ("2", "processing"),
        ]
    finally:
        settings.data_dir = old_data_dir


def test_creator_subscription_persists_settings_and_uses_watermark(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            videos=[
                CreatorVideo(
                    "douyin",
                    "1",
                    "https://www.douyin.com/video/1",
                    "第一条",
                    published_at="2025-01-02T00:00:00+00:00",
                )
            ],
        )
        calls = []
        monkeypatch.setattr(
            creator_sync,
            "preview_creator_source",
            lambda **kwargs: calls.append(kwargs) or preview,
        )
        monkeypatch.setattr(creator_sync.task_manager, "create", lambda _request: (_ for _ in ()).throw(AssertionError("should not queue")))

        first = creator_sync.sync_creator_source(
            source_url=preview.source_url,
            limit=100,
            auto_process=False,
            sync_interval_minutes=60,
        )
        source = creator_sync.get_creator_source(first.source_id)

        assert source["enabled"] is True
        assert source["auto_process"] is False
        assert source["sync_interval_minutes"] == 60
        assert source["last_seen_published_at"] == "2025-01-02T00:00:00+00:00"
        assert source["last_created_count"] == 1

        creator_sync.update_creator_source(first.source_id, enabled=False)
        try:
            creator_sync.sync_saved_creator_source(first.source_id)
        except CreatorSyncError as exc:
            assert "暂停" in str(exc)
        else:
            raise AssertionError("expected paused source to skip manual sync")

        creator_sync.update_creator_source(first.source_id, enabled=True)
        second = creator_sync.sync_saved_creator_source(first.source_id)
        assert second.created_count == 0
        assert calls[-1]["published_after"] == "2025-01-02T00:00:00+00:00"
    finally:
        settings.data_dir = old_data_dir


def test_manual_creator_sync_requeues_failed_items(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        initial_preview = CreatorPreview(
            provider="douyin",
            source_kind="collection",
            source_url="https://www.douyin.com/collection/7409286662292768779",
            creator_key="7409286662292768779",
            creator_name="科技补全",
            collection_id="7409286662292768779",
            videos=[CreatorVideo("douyin", "7409252926004170047", "https://www.douyin.com/video/7409252926004170047", "作品")],
        )
        empty_preview = CreatorPreview(
            provider=initial_preview.provider,
            source_kind=initial_preview.source_kind,
            source_url=initial_preview.source_url,
            creator_key=initial_preview.creator_key,
            creator_name=initial_preview.creator_name,
            collection_id=initial_preview.collection_id,
            videos=[],
        )
        previews = [initial_preview, empty_preview]
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: previews.pop(0))
        queued = []
        monkeypatch.setattr(
            creator_sync.task_manager,
            "create",
            lambda request: queued.append(request) or SimpleNamespace(task_id=f"task-{len(queued)}"),
        )

        created = creator_sync.sync_creator_source(source_url=initial_preview.source_url)
        with connect() as connection:
            ContentRepository(connection).update_status(created.content_item_ids[0], "failed")
            connection.commit()

        recovered = creator_sync.sync_saved_creator_source(created.source_id, retry_existing_items=True)
        assert recovered.created_count == 0
        assert recovered.task_ids == ["task-2"]
        assert recovered.content_item_ids == [created.content_item_ids[0]]
        assert len(queued) == 2
    finally:
        settings.data_dir = old_data_dir


def test_creator_subscription_treats_empty_incremental_check_as_success(monkeypatch, tmp_path):
    """No new video is a normal polling result and must not trigger retries."""
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        initial_preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            videos=[
                CreatorVideo(
                    "douyin",
                    "1",
                    "https://www.douyin.com/video/1",
                    "第一条",
                    published_at="2025-01-02T00:00:00+00:00",
                )
            ],
        )
        empty_incremental_preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url=initial_preview.source_url,
            creator_key="tester",
            creator_name="测试作者",
            videos=[],
        )
        previews = [initial_preview, empty_incremental_preview]
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: previews.pop(0))
        monkeypatch.setattr(creator_sync.task_manager, "create", lambda _request: SimpleNamespace(task_id="task-1"))

        created = creator_sync.sync_creator_source(source_url=initial_preview.source_url, sync_interval_minutes=60)
        result = creator_sync.sync_saved_creator_source(created.source_id)
        source = creator_sync.get_creator_source(created.source_id)

        assert result.created_count == 0
        assert result.duplicate_count == 0
        assert source["last_error"] is None
        assert source["last_discovered_count"] == 0
        assert source["next_sync_at"]
    finally:
        settings.data_dir = old_data_dir


def test_creator_sync_honors_selected_videos_processing_mode_and_queue_limit(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            videos=[
                CreatorVideo("douyin", "1", "https://www.douyin.com/video/1", "第一条"),
                CreatorVideo("douyin", "2", "https://www.douyin.com/video/2", "第二条"),
                CreatorVideo("douyin", "3", "https://www.douyin.com/video/3", "第三条"),
            ],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        queued = []
        monkeypatch.setattr(
            creator_sync.task_manager,
            "create",
            lambda request: queued.append(request) or SimpleNamespace(task_id=f"task-{len(queued)}"),
        )

        result = creator_sync.sync_creator_source(
            source_url=preview.source_url,
            limit=3,
            selected_video_ids=["1", "3"],
            processing_mode="full",
            queue_limit=1,
        )
        source = creator_sync.get_creator_source(result.source_id)
        with connect() as connection:
            rows = connection.execute(
                "SELECT canonical_source_id, status FROM content_items ORDER BY canonical_source_id"
            ).fetchall()

        assert result.discovered_count == 2
        assert result.created_count == 2
        assert result.queued_count == 1
        assert result.inbox_count == 1
        assert len(queued) == 1
        assert queued[0].processing_mode == "full"
        assert source["processing_mode"] == "full"
        assert source["queue_limit"] == 1
        assert [(row["canonical_source_id"], row["status"]) for row in rows] == [
            ("1", "processing"),
            ("3", "inbox"),
        ]
    finally:
        settings.data_dir = old_data_dir


def test_creator_sync_metadata_mode_skips_tasks_and_rejects_stale_selection(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="bilibili",
            source_kind="profile",
            source_url="https://space.bilibili.com/42",
            creator_key="42",
            creator_name="测试 UP 主",
            videos=[CreatorVideo("bilibili", "BV1test", "https://www.bilibili.com/video/BV1test", "测试视频")],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        monkeypatch.setattr(
            creator_sync.task_manager,
            "create",
            lambda _request: (_ for _ in ()).throw(AssertionError("metadata mode must not queue")),
        )

        result = creator_sync.sync_creator_source(
            source_url=preview.source_url,
            selected_video_ids=["BV1test"],
            processing_mode="metadata",
        )
        assert result.queued_count == 0
        assert result.inbox_count == 1
        try:
            creator_sync.sync_creator_source(
                source_url=preview.source_url,
                selected_video_ids=["missing"],
            )
        except CreatorSyncError as exc:
            assert "重新预览" in str(exc)
        else:
            raise AssertionError("expected stale selection to be rejected")
    finally:
        settings.data_dir = old_data_dir


def test_creator_retry_backoff_distinguishes_login_and_remote_failures():
    assert creator_sync._creator_retry_minutes("remote", 1, 30) == 30
    assert creator_sync._creator_retry_minutes("remote", 2, 30) == 60
    assert creator_sync._creator_retry_minutes("authorization", 4, 60) == 360
    assert creator_sync._creator_error_category("B 站请求返回 412，请更新 Cookie") == "authorization"
    assert creator_sync._creator_error_category("内置浏览器请求超时") == "remote"
    assert creator_sync._creator_error_category("错误码 -352：风控校验失败；请确认当前登录态可用") == "remote"


def test_creator_source_identity_is_stable_when_tracking_query_changes(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        expected = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            videos=[],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: expected)
        first = creator_sync.sync_creator_source(source_url="https://www.douyin.com/user/tester?from_tab_name=main")
        second = creator_sync.sync_creator_source(source_url="https://www.douyin.com/user/tester")

        assert first.source_id == second.source_id
        assert len(creator_sync.list_creator_sources()) == 1
    finally:
        settings.data_dir = old_data_dir


def test_creator_source_registry_tracks_due_enabled_sources(monkeypatch, tmp_path):
    from config import settings

    old_data_dir = settings.data_dir
    settings.data_dir = Path(tmp_path)
    try:
        preview = CreatorPreview(
            provider="douyin",
            source_kind="profile",
            source_url="https://www.douyin.com/user/tester",
            creator_key="tester",
            creator_name="测试作者",
            videos=[],
        )
        monkeypatch.setattr(creator_sync, "preview_creator_source", lambda **_kwargs: preview)
        created = creator_sync.sync_creator_source(source_url=preview.source_url)

        assert creator_source_registry.source_identity("douyin", "profile", "tester") == "douyin:profile:tester"
        assert creator_source_registry.due_creator_source_ids("9999-01-01T00:00:00+00:00") == [created.source_id]

        creator_source_registry.update_creator_source(created.source_id, enabled=False)
        assert creator_source_registry.due_creator_source_ids("9999-01-01T00:00:00+00:00") == []
    finally:
        settings.data_dir = old_data_dir
