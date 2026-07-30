from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from services.database import connect, initialize_database, utc_now_iso
from services.campus_source_settings import load_campus_source_settings, update_campus_source_setting
from services.library_source_groups import list_library_source_groups, remove_library_source_group_member
from services import wechat_reports
from services.wechat_reports import _group_report_source_rows, create_group, delete_group, list_groups, preflight_report
from services.repository import ContentRepository


def test_report_preflight_only_reads_scope_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")
    rows = [{"content_item_id": "content-1", "title": "范围内文章"}]
    monkeypatch.setattr(wechat_reports, "_group_report_source_rows", lambda *_args, **_kwargs: rows)

    def unexpected_material_load(*_args, **_kwargs):
        raise AssertionError("预检不应读取全文或摘要缓存")

    monkeypatch.setattr(wechat_reports, "_load_group_report_sources", unexpected_material_load)

    result = preflight_report(
        group["id"],
        "range",
        window_start=datetime(2026, 7, 13, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )

    assert result["source_count"] == 1
    assert result["material_check_pending"] is True
    assert result["expected_calls"]["summary_calls"] is None


def test_report_source_loading_emits_incremental_progress(monkeypatch):
    rows = [
        {
            "content_item_id": f"content-{index}",
            "title": f"文章 {index}",
            "source_url": f"https://example.test/{index}",
            "published_at": "2026-07-15T10:00:00+00:00",
            "mp_name": "测试来源",
            "source_provider": "wechat",
        }
        for index in range(1, 12)
    ]
    monkeypatch.setattr(wechat_reports, "_group_report_source_rows", lambda *_args, **_kwargs: rows)
    monkeypatch.setattr(wechat_reports, "_source_material", lambda row: f"正文 {row['content_item_id']}")
    events = []

    sources = wechat_reports._load_group_report_sources(
        "group-1",
        datetime(2026, 7, 13, tzinfo=timezone.utc),
        datetime(2026, 7, 19, tzinfo=timezone.utc),
        campus_source_slugs=None,
        progress_callback=events.append,
    )

    assert len(sources) == 11
    assert [event["progress"] for event in events] == [2, 3, 15, 16]
    assert events[-1]["message"] == "正在装载素材与摘要缓存：11/11"


def test_delete_group_removes_all_subscription_labels_and_prompts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")
    now = utc_now_iso()

    with connect() as connection:
        connection.execute(
            "INSERT INTO wechat_accounts (id, display_name, keychain_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("account-1", "测试账号", "keychain-1", now, now),
        )
        for index in range(2):
            subscription_id = f"subscription-{index}"
            connection.execute(
                """INSERT INTO wechat_subscriptions
                   (id, account_id, fakeid, mp_name, group_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (subscription_id, "account-1", f"fakeid-{index}", f"公众号{index}", group["id"], now, now),
            )
            connection.execute(
                """INSERT INTO wechat_subscription_group_memberships
                   (subscription_id, group_id, created_at) VALUES (?, ?, ?)""",
                (subscription_id, group["id"], now),
            )
        connection.commit()

    result = delete_group(group["id"])

    assert result["affected_subscription_count"] == 2
    with connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM wechat_subscription_groups WHERE id=?", (group["id"],)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM wechat_subscription_group_memberships WHERE group_id=?", (group["id"],)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM wechat_subscriptions WHERE group_id IS NOT NULL"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM wechat_report_prompts WHERE group_id=?", (group["id"],)
        ).fetchone()[0] == 0


def test_report_source_coverage_column_is_available_after_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()

    with connect() as connection:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(wechat_reports)").fetchall()
        }

    assert "source_coverage_json" in columns


def test_existing_group_prompt_check_does_not_open_a_write_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")

    with connect() as connection:
        before = connection.total_changes
        wechat_reports._ensure_default_prompts(connection, group["id"])
        after = connection.total_changes

    assert after == before


def test_report_preparation_remains_readable_during_background_write(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    initialize_database()
    group = create_group("校园生活")
    monkeypatch.setattr(
        wechat_reports,
        "_generate_common_group_report",
        lambda *_args, **_kwargs: {"content_item_id": "report-probe"},
    )
    monkeypatch.setattr(wechat_reports, "attach_ai_calls_to_content", lambda *_args: None)
    monkeypatch.setattr(
        wechat_reports,
        "ai_call_usage_for_task",
        lambda *_args: {
            "call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "unreported_count": 0,
        },
    )
    monkeypatch.setattr(
        wechat_reports,
        "_merge_report_generation_metadata",
        lambda *_args, **_kwargs: None,
    )

    blocker = connect()
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute(
        "UPDATE wechat_subscription_groups SET updated_at=updated_at WHERE id=?",
        (group["id"],),
    )
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                wechat_reports.generate_report,
                group["id"],
                "weekly",
            )
            result = future.result(timeout=1)
    finally:
        blocker.rollback()
        blocker.close()

    assert result["content_item_id"] == "report-probe"


def test_group_source_collection_uses_campus_origin_not_gwt_department(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")
    with connect() as connection:
        repository = ContentRepository(connection)
        gwt_article = repository.create_content_item(
            source_provider="campus",
            content_type="article",
            source_url="https://nbw.sztu.edu.cn/info/1029/1001.htm",
            canonical_source_id="selected-gwt",
            title="公文通通知",
            published_at="2026-07-15T11:00:00+08:00",
            source_name="药学院",
            source_section="公文通",
        )
        college_article = repository.create_content_item(
            source_provider="campus",
            content_type="article",
            source_url="https://cop.sztu.edu.cn/info/1/2.htm",
            canonical_source_id="selected-cop",
            title="药学院官网文章",
            published_at="2026-07-15T11:00:00+08:00",
            source_name="药学院",
            source_section="学院新闻",
        )
        unassigned_article = repository.create_content_item(
            source_provider="campus",
            content_type="article",
            source_url="https://ai.sztu.edu.cn/info/1/2.htm",
            canonical_source_id="ignored-ai",
            title="未加入分组的学院文章",
            published_at="2026-07-15T11:00:00+08:00",
            source_name="人工智能学院",
            source_section="院系新闻",
        )
        connection.commit()

    gwt_rows = _group_report_source_rows(
        group["id"],
        window_start=datetime(2026, 7, 14, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 17, tzinfo=timezone.utc),
        campus_source_slugs=["gwt"],
    )
    college_rows = _group_report_source_rows(
        group["id"],
        window_start=datetime(2026, 7, 14, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 17, tzinfo=timezone.utc),
        campus_source_slugs=["cop"],
    )
    combined_rows = _group_report_source_rows(
        group["id"],
        window_start=datetime(2026, 7, 14, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 17, tzinfo=timezone.utc),
        campus_source_slugs=["gwt", "cop"],
    )

    assert {row["content_item_id"] for row in gwt_rows} == {gwt_article.id}
    assert {row["content_item_id"] for row in college_rows} == {college_article.id}
    assert {row["content_item_id"] for row in combined_rows} == {
        gwt_article.id,
        college_article.id,
    }
    assert unassigned_article.id not in {
        row["content_item_id"] for row in combined_rows
    }


def test_group_source_collection_includes_only_assigned_rss_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("科技资讯")
    now = utc_now_iso()
    with connect() as connection:
        repository = ContentRepository(connection)
        selected = repository.create_content_item(
            source_provider="rss",
            content_type="article",
            source_url="https://example.com/selected",
            canonical_source_id="rss-selected",
            title="已加入分组的 RSS 文章",
            published_at="2026-07-15T11:00:00+08:00",
            source_name="测试 RSS",
            source_section="RSS 订阅",
        )
        ignored = repository.create_content_item(
            source_provider="rss",
            content_type="article",
            source_url="https://example.com/ignored",
            canonical_source_id="rss-ignored",
            title="未加入分组的 RSS 文章",
            published_at="2026-07-15T11:00:00+08:00",
            source_name="未归类 RSS",
            source_section="RSS 订阅",
        )
        connection.execute(
            """INSERT INTO rss_sources (id, feed_url, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            ("rss-selected", "https://example.com/feed.xml", "测试 RSS", now, now),
        )
        connection.execute(
            """INSERT INTO rss_source_items (source_id, content_item_id, entry_identity, created_at)
               VALUES (?, ?, ?, ?)""",
            ("rss-selected", selected.id, "selected-entry", now),
        )
        connection.execute(
            """INSERT INTO rss_source_group_memberships (source_id, group_id, created_at)
               VALUES (?, ?, ?)""",
            ("rss-selected", group["id"], now),
        )
        connection.commit()

    rows = _group_report_source_rows(
        group["id"],
        window_start=datetime(2026, 7, 14, tzinfo=timezone.utc),
        window_end=datetime(2026, 7, 17, tzinfo=timezone.utc),
        campus_source_slugs=None,
    )

    assert {row["content_item_id"] for row in rows} == {selected.id}
    assert ignored.id not in {row["content_item_id"] for row in rows}
    listed_group = next(item for item in list_groups() if item["id"] == group["id"])
    assert listed_group["rss_source_count"] == 1
    assert listed_group["source_count"] == 1


def test_library_source_groups_list_and_remove_each_source_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    daily = create_group("每日新闻")
    other = create_group("其他")
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            "INSERT INTO wechat_accounts (id, display_name, keychain_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("account-1", "测试账号", "keychain-1", now, now),
        )
        connection.execute(
            """INSERT INTO wechat_subscriptions
               (id, account_id, fakeid, mp_name, group_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("wechat-1", "account-1", "fakeid-1", "新闻号", daily["id"], now, now),
        )
        connection.executemany(
            "INSERT INTO wechat_subscription_group_memberships (subscription_id, group_id, created_at) VALUES (?, ?, ?)",
            [("wechat-1", daily["id"], now), ("wechat-1", other["id"], now)],
        )
        connection.execute(
            "INSERT INTO rss_sources (id, feed_url, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("rss-1", "https://example.com/feed.xml", "新闻 RSS", now, now),
        )
        connection.execute(
            "INSERT INTO rss_source_group_memberships (source_id, group_id, created_at) VALUES (?, ?, ?)",
            ("rss-1", daily["id"], now),
        )
        connection.commit()
    update_campus_source_setting("gwt", group_ids=[daily["id"]])

    listed_daily = next(group for group in list_library_source_groups() if group["id"] == daily["id"])
    assert {(source["kind"], source["source_id"]) for source in listed_daily["sources"]} == {
        ("wechat", "wechat-1"), ("rss", "rss-1"), ("campus", "gwt")
    }

    remove_library_source_group_member(daily["id"], "wechat", "wechat-1")
    remove_library_source_group_member(daily["id"], "rss", "rss-1")
    remove_library_source_group_member(daily["id"], "campus", "gwt")

    with connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM wechat_subscription_group_memberships WHERE group_id=? AND subscription_id=?",
            (daily["id"], "wechat-1"),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT group_id FROM wechat_subscriptions WHERE id=?", ("wechat-1",)
        ).fetchone()[0] == other["id"]
        assert connection.execute(
            "SELECT COUNT(*) FROM rss_source_group_memberships WHERE group_id=? AND source_id=?",
            (daily["id"], "rss-1"),
        ).fetchone()[0] == 0
    campus = next(source for source in load_campus_source_settings() if source["slug"] == "gwt")
    assert daily["id"] not in campus["group_ids"]
