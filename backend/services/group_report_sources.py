"""Source selection and material loading for group reports."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from services.campus_sources import CAMPUS_SOURCES
from services.content_source_text import load_content_source_text
from services.database import connect
from services.report_time_rules import in_window


def group_report_source_rows(
    group_id: str,
    *,
    window_start: datetime,
    window_end: datetime,
    campus_source_slugs: list[str] | None,
    include_external_imports: bool = False,
) -> list[dict]:
    """Collect only sources explicitly assigned to this group.

    WeChat, campus websites and RSS feeds enter through their durable group
    memberships. External imports are deliberately opt-in for one report run.
    """
    start_date = (window_start.date() - timedelta(days=1)).isoformat()
    end_date = (window_end.date() + timedelta(days=1)).isoformat()
    selected_slugs = {str(value) for value in campus_source_slugs or []}
    selected_names = tuple(
        source.name
        for source in CAMPUS_SOURCES
        if source.slug in selected_slugs and source.slug != "gwt"
    )
    include_gwt = "gwt" in selected_slugs
    with connect() as connection:
        wechat_rows = connection.execute(
            """SELECT i.id AS content_item_id, i.title, i.source_url,
                      COALESCE(w.published_at, i.published_at, i.created_at) AS published_at,
                      s.mp_name, i.source_name, i.source_section, i.source_provider,
                      sync.markdown_draft_path
               FROM wechat_subscription_items w
               JOIN wechat_subscriptions s ON s.id=w.subscription_id
               JOIN wechat_subscription_group_memberships membership ON membership.subscription_id=s.id
               JOIN content_items i ON i.id=w.content_item_id
               LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
               WHERE membership.group_id=?
                 AND i.deleted_at IS NULL
                 AND date(COALESCE(w.published_at, i.published_at, i.created_at)) BETWEEN ? AND ?""",
            (group_id, start_date, end_date),
        ).fetchall()
        campus_rows = []
        campus_source_conditions: list[str] = []
        campus_source_params: list[str] = []
        if selected_names:
            placeholders = ",".join("?" for _ in selected_names)
            # GWT stores its publishing department in source_name. Exclude it
            # from ordinary campus-name matching so a department such as
            # "药学院" cannot leak into the college website source.
            campus_source_conditions.append(
                f"(i.source_name IN ({placeholders}) "
                "AND COALESCE(i.source_section, '') != '公文通')"
            )
            campus_source_params.extend(selected_names)
        if include_gwt:
            # source_section is the stable GWT marker already written by both
            # normal sync and snapshot import. source_name is deliberately the
            # publishing department and therefore cannot identify this source.
            campus_source_conditions.append(
                "(i.source_section='公文通' OR i.source_name='公文通')"
            )
        if campus_source_conditions:
            campus_rows = connection.execute(
                f"""SELECT i.id AS content_item_id, i.title, i.source_url,
                          COALESCE(i.published_at, i.created_at) AS published_at,
                          i.source_name AS mp_name, i.source_name, i.source_section, i.source_provider,
                          sync.markdown_draft_path
                   FROM content_items i
                   LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
                   WHERE i.deleted_at IS NULL
                     AND i.content_type='article'
                     AND i.source_provider='campus'
                     AND ({' OR '.join(campus_source_conditions)})
                     AND date(COALESCE(i.published_at, i.created_at)) BETWEEN ? AND ?""",
                (*campus_source_params, start_date, end_date),
            ).fetchall()
        rss_rows = connection.execute(
            """SELECT i.id AS content_item_id, i.title, i.source_url,
                      COALESCE(i.published_at, i.created_at) AS published_at,
                      rss.title AS mp_name, i.source_name, i.source_section, i.source_provider,
                      sync.markdown_draft_path
               FROM rss_source_group_memberships membership
               JOIN rss_source_items rss_item ON rss_item.source_id=membership.source_id
               JOIN rss_sources rss ON rss.id=rss_item.source_id
               JOIN content_items i ON i.id=rss_item.content_item_id
               LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
               WHERE membership.group_id=?
                 AND i.deleted_at IS NULL
                 AND i.content_type='article'
                 AND i.source_provider='rss'
                 AND date(COALESCE(i.published_at, i.created_at)) BETWEEN ? AND ?""",
            (group_id, start_date, end_date),
        ).fetchall()
        local_rows = []
        if include_external_imports:
            local_rows = connection.execute(
                """SELECT i.id AS content_item_id, i.title, i.source_url,
                          i.created_at AS published_at,
                          '外部导入' AS mp_name, i.source_name, i.source_section, i.source_provider,
                          sync.markdown_draft_path
                   FROM content_items i
                   LEFT JOIN obsidian_sync sync ON sync.content_item_id=i.id
                   WHERE i.deleted_at IS NULL
                     AND i.source_provider IN ('local_markdown', 'local_file')
                     AND i.content_type IN ('document', 'image')
                     AND date(i.created_at) BETWEEN ? AND ?""",
                (start_date, end_date),
            ).fetchall()
    by_id: dict[str, dict] = {}
    for raw in [*wechat_rows, *campus_rows, *rss_rows, *local_rows]:
        row = dict(raw)
        if in_window(str(row.get("published_at") or ""), window_start, window_end):
            by_id[str(row["content_item_id"])] = row
    return list(by_id.values())


def group_source_sort_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("published_at") or ""),
        str(row.get("source_name") or row.get("mp_name") or ""),
        str(row.get("content_item_id") or ""),
    )


def source_material(
    source: dict,
    *,
    load_text: Callable[[str], Any] = load_content_source_text,
) -> str:
    header = f"## {source['mp_name']}｜{source['title']}\n日期：{source['published_at']}\n链接：{source['source_url']}"
    content_item_id = str(source.get("content_item_id") or "").strip()
    if content_item_id:
        try:
            article = load_text(content_item_id)
        except Exception:
            article = None
        if article and article.text.strip():
            return f"{header}\n\n原文正文（含图片文字识别结果）：\n{article.text.strip()}"

    draft_path = source.get("markdown_draft_path")
    if not draft_path:
        return header
    try:
        content = Path(str(draft_path)).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return header
    if not content:
        return header
    return f"{header}\n\n原文正文：\n{original_body_from_markdown(content)}"


def original_body_from_markdown(markdown: str) -> str:
    marker = "<summary>原文正文</summary>"
    if marker not in markdown:
        return markdown
    body = markdown.split(marker, 1)[1]
    if "</details>" in body:
        body = body.rsplit("</details>", 1)[0]
    return body.strip() or markdown
