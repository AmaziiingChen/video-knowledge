from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from services.database import connect, initialize_database
from services.openclaw_conversations import list_conversation_tasks


CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _china_today() -> date:
    return datetime.now(CHINA_TIMEZONE).date()


def workspace_overview(
    *,
    for_date: date | None = None,
    conversation_key: str | None = None,
    content_limit: int = 12,
    task_limit: int = 12,
) -> dict[str, object]:
    """Return the same safe, read-only facts shown across the workbench.

    This intentionally exposes no credential, cookie, file path, message body,
    or hidden/deleted library item. Article bodies remain a separate explicit
    read operation, mirroring the workbench's open-one-item-at-a-time flow.
    """
    if not 1 <= content_limit <= 50 or not 1 <= task_limit <= 50:
        raise ValueError("工作台列表数量必须介于 1 到 50 之间")
    target_date = for_date or _china_today()
    initialize_database()
    with connect() as connection:
        library_total = int(connection.execute(
            """
            SELECT COUNT(*) FROM content_items
            WHERE deleted_at IS NULL AND library_visible = 1
            """
        ).fetchone()[0])
        recent_content_rows = connection.execute(
            """
            SELECT id, title, source_provider, content_type, status,
                   COALESCE(published_at, created_at) AS visible_at
            FROM content_items
            WHERE deleted_at IS NULL AND library_visible = 1
            ORDER BY COALESCE(published_at, created_at) DESC, id DESC
            LIMIT ?
            """,
            (content_limit,),
        ).fetchall()
        recent_task_rows = connection.execute(
            """
            SELECT tasks.id, tasks.status, tasks.progress, tasks.current_stage,
                   tasks.content_item_id, tasks.updated_at,
                   content_items.title
            FROM tasks
            LEFT JOIN content_items ON content_items.id = tasks.content_item_id
            ORDER BY tasks.updated_at DESC, tasks.id DESC
            LIMIT ?
            """,
            (task_limit,),
        ).fetchall()
        today_article_rows = connection.execute(
            """
            SELECT item.id, item.content_item_id, item.title, item.published_at,
                   subscription.mp_name AS publisher
            FROM wechat_subscription_items AS item
            JOIN wechat_subscriptions AS subscription ON subscription.id = item.subscription_id
            WHERE item.content_item_id IS NOT NULL
              AND substr(item.published_at, 1, 10) = ?
            ORDER BY item.published_at DESC, item.id DESC
            LIMIT 50
            """,
            (target_date.isoformat(),),
        ).fetchall()
        subscription_rows = connection.execute(
            """
            SELECT subscription.id, subscription.mp_name, subscription.enabled,
                   subscription.last_sync_at, subscription.next_sync_at,
                   subscription.last_error, account.status AS account_status
            FROM wechat_subscriptions AS subscription
            JOIN wechat_accounts AS account ON account.id = subscription.account_id
            ORDER BY subscription.mp_name COLLATE NOCASE ASC
            """
        ).fetchall()

    conversation_tasks = (
        list_conversation_tasks(session_key=conversation_key, limit=task_limit)
        if conversation_key and conversation_key.strip()
        else []
    )
    return {
        "generated_at": datetime.now(CHINA_TIMEZONE).isoformat(),
        "timezone": "Asia/Shanghai",
        "date": target_date.isoformat(),
        "library": {
            "total_visible_items": library_total,
            "recent_items": [
                {
                    "content_item_id": row["id"],
                    "title": row["title"] or "未命名内容",
                    "source_provider": row["source_provider"],
                    "content_type": row["content_type"],
                    "status": row["status"],
                    "visible_at": row["visible_at"],
                }
                for row in recent_content_rows
            ],
        },
        "tasks": [
            {
                "task_id": row["id"],
                "title": row["title"] or "未命名内容",
                "status": row["status"],
                "progress": float(row["progress"]),
                "stage": row["current_stage"],
                "content_item_id": row["content_item_id"],
                "updated_at": row["updated_at"],
            }
            for row in recent_task_rows
        ],
        "wechat": {
            "today_article_count": len(today_article_rows),
            "today_articles": [
                {
                    "article_id": row["id"],
                    "content_item_id": row["content_item_id"],
                    "publisher": row["publisher"],
                    "title": row["title"],
                    "published_at": row["published_at"],
                }
                for row in today_article_rows
            ],
            "subscriptions": [
                {
                    "subscription_id": row["id"],
                    "publisher": row["mp_name"],
                    "enabled": bool(row["enabled"]),
                    "account_status": row["account_status"],
                    "last_sync_at": row["last_sync_at"],
                    "next_sync_at": row["next_sync_at"],
                    "last_error": row["last_error"],
                }
                for row in subscription_rows
            ],
        },
        "conversation_tasks": conversation_tasks,
    }
