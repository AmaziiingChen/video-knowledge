"""Local completion-event ledger for the in-app and menu-bar notifications."""
from __future__ import annotations

import uuid
from typing import Any

from services.database import connect, ensure_database_initialized, utc_now_iso


def record_completion_notification(*, event_key: str, event_type: str, title: str, body: str = "", content_item_id: str | None = None, target_view: str = "library") -> bool:
    key = str(event_key or "").strip()
    if not key:
        raise ValueError("通知事件缺少稳定标识")
    ensure_database_initialized()
    with connect() as connection:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO completion_notifications
               (id, event_key, event_type, title, body, content_item_id, target_view, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(uuid.uuid4()), key, str(event_type or "completed")[:40], str(title or "完成")[:240], str(body or "")[:800], content_item_id or None, str(target_view or "library")[:40], utc_now_iso()),
        )
        connection.commit()
    return cursor.rowcount > 0


def list_pending_notifications(limit: int = 20) -> list[dict[str, Any]]:
    ensure_database_initialized()
    with connect() as connection:
        rows = connection.execute(
            """SELECT id, event_type, title, body, content_item_id, target_view, created_at
               FROM completion_notifications WHERE seen_at IS NULL
               ORDER BY created_at DESC LIMIT ?""",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_notifications_seen(notification_ids: list[str]) -> int:
    ids = list(dict.fromkeys(str(value).strip() for value in notification_ids if str(value).strip()))
    if not ids:
        return 0
    ensure_database_initialized()
    placeholders = ",".join("?" for _ in ids)
    with connect() as connection:
        cursor = connection.execute(
            f"UPDATE completion_notifications SET seen_at=? WHERE seen_at IS NULL AND id IN ({placeholders})",
            (utc_now_iso(), *ids),
        )
        connection.commit()
    return int(cursor.rowcount)


def notification_policy_for_content(content_item_id: str) -> tuple[bool, bool, str]:
    """Return (enabled, waits_for_analysis, title) for a source-owned article."""
    if not content_item_id:
        return False, False, ""
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            """SELECT item.title, item.source_provider, item.source_name,
                      subscription.notify_on_new AS wechat_notify, subscription.auto_process AS wechat_auto,
                      rss.notify_on_new AS rss_notify, rss.auto_analyze AS rss_auto
               FROM content_items item
               LEFT JOIN wechat_subscription_items subscription_item ON subscription_item.content_item_id=item.id
               LEFT JOIN wechat_subscriptions subscription ON subscription.id=subscription_item.subscription_id
               LEFT JOIN rss_source_items rss_item ON rss_item.content_item_id=item.id
               LEFT JOIN rss_sources rss ON rss.id=rss_item.source_id
               WHERE item.id=?""",
            (content_item_id,),
        ).fetchone()
    if row is None:
        return False, False, ""
    title = str(row["title"] or "新资料")
    if str(row["source_provider"] or "") == "wechat":
        return bool(row["wechat_notify"]), bool(row["wechat_auto"]), title
    if str(row["source_provider"] or "") == "rss":
        return bool(row["rss_notify"]), bool(row["rss_auto"]), title
    if str(row["source_provider"] or "") == "campus":
        try:
            from services.campus_source_settings import load_campus_source_settings
            setting = next((item for item in load_campus_source_settings() if str(item.get("name") or "") == str(row["source_name"] or "")), {})
            return bool(setting.get("notify_on_new")), bool(setting.get("auto_analyze")), title
        except Exception:
            return False, False, title
    return False, False, title


def record_content_ready(content_item_id: str, *, after_analysis: bool) -> bool:
    enabled, waits_for_analysis, title = notification_policy_for_content(content_item_id)
    if not enabled or waits_for_analysis != after_analysis:
        return False
    stage = "分析完成" if after_analysis else "正文已解析"
    return record_completion_notification(
        event_key=f"content-ready:{content_item_id}:{stage}", event_type="source_article_ready",
        title=title, body=stage, content_item_id=content_item_id,
    )


def record_manual_media_ready(content_item_id: str, title: str) -> bool:
    return record_completion_notification(
        event_key=f"manual-media-ready:{content_item_id}", event_type="media_ready",
        title=title or "媒体资料已处理完成", body="转写与摘要已完成", content_item_id=content_item_id,
    )
