from __future__ import annotations

from datetime import date

from config import settings
from services.agent_workspace import workspace_overview
from services.database import connect, initialize_database, utc_now_iso
from services.repository import ContentRepository, TaskRepository, new_id


def test_workspace_overview_matches_safe_workbench_facts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        visible_item = repository.create_content_item(
            source_provider="wechat",
            content_type="article",
            title="工作台文章",
            source_url="https://mp.weixin.qq.com/s?test=1",
            canonical_source_id="workspace-visible",
            status="to_read",
            published_at="2026-07-23 09:00",
        )
        hidden_item = repository.create_content_item(
            source_provider="wechat",
            content_type="article",
            title="隐藏文章",
            source_url="https://mp.weixin.qq.com/s?test=2",
            canonical_source_id="workspace-hidden",
            status="to_read",
            library_visible=False,
        )
        task = TaskRepository(connection).create_task(
            task_type="process_video", task_id="workspace-task", content_item_id=visible_item.id
        )
        TaskRepository(connection).update_task_state(task.id, status="running", progress=40)
        now = utc_now_iso()
        account_id = new_id()
        subscription_id = new_id()
        connection.execute(
            "INSERT INTO wechat_accounts (id, display_name, keychain_ref, status, created_at, updated_at) VALUES (?, '测试账号', ?, 'active', ?, ?)",
            (account_id, f"workspace:{account_id}", now, now),
        )
        connection.execute(
            """INSERT INTO wechat_subscriptions (id, account_id, fakeid, mp_name, enabled, auto_process, sync_interval_minutes, next_sync_at, created_at, updated_at)
            VALUES (?, ?, 'fakeid-test', '测试公众号', 1, 0, 60, ?, ?, ?)""",
            (subscription_id, account_id, now, now, now),
        )
        connection.execute(
            """INSERT INTO wechat_subscription_items (id, subscription_id, remote_article_id, source_url, content_item_id, title, published_at, discovered_at)
            VALUES (?, ?, 'remote-workspace', ?, ?, '今日公众号文章', '2026-07-23 10:00', ?)""",
            (new_id(), subscription_id, visible_item.source_url, visible_item.id, now),
        )
        connection.commit()

    overview = workspace_overview(for_date=date(2026, 7, 23))

    assert overview["library"]["total_visible_items"] == 1
    assert [item["title"] for item in overview["library"]["recent_items"]] == ["工作台文章"]
    assert overview["tasks"][0]["task_id"] == "workspace-task"
    assert overview["wechat"]["today_article_count"] == 1
    assert overview["wechat"]["today_articles"][0]["title"] == "今日公众号文章"
    assert hidden_item.id not in {item["content_item_id"] for item in overview["library"]["recent_items"]}
