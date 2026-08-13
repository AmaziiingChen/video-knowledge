from __future__ import annotations

import json
from typing import Any

from services.database import connect
from services.wechat_report_layout import ReportSource, render_wechat_report


def render_report_html(
    report: dict[str, Any],
    markdown: str,
    digest: str,
    *,
    title: str | None = None,
) -> str:
    return render_wechat_report(
        title=str(title or report.get("title") or "报告"),
        markdown=markdown,
        digest=digest,
        report_type=str(report.get("report_type") or "range"),
        sources=report_sources(report),
    )


def report_sources(report: dict[str, Any]) -> list[ReportSource]:
    try:
        coverage = json.loads(str(report.get("source_coverage_json") or "[]"))
    except json.JSONDecodeError:
        coverage = []
    entries = [entry for entry in coverage if isinstance(entry, dict) and entry.get("citation_id") and entry.get("content_item_id")]
    if not entries:
        return []
    ids = [str(entry["content_item_id"]) for entry in entries]
    placeholders = ",".join("?" for _ in ids)
    with connect() as connection:
        rows = connection.execute(
            f"""SELECT c.id, c.title, c.source_url, c.published_at,
                       COALESCE(NULLIF(c.source_name, ''), ws.mp_name, rss.title, '') AS publisher
                  FROM content_items c
                  LEFT JOIN wechat_subscription_items wsi ON wsi.content_item_id=c.id
                  LEFT JOIN wechat_subscriptions ws ON ws.id=wsi.subscription_id
                  LEFT JOIN rss_source_items rsi ON rsi.content_item_id=c.id
                  LEFT JOIN rss_sources rss ON rss.id=rsi.source_id
                 WHERE c.id IN ({placeholders})""",
            ids,
        ).fetchall()
    by_id = {str(row["id"]): dict(row) for row in rows}
    return [
        ReportSource(
            citation_id=str(entry["citation_id"]),
            title=str((by_id.get(str(entry["content_item_id"])) or {}).get("title") or "原始文章"),
            url=str((by_id.get(str(entry["content_item_id"])) or {}).get("source_url") or ""),
            publisher=str((by_id.get(str(entry["content_item_id"])) or {}).get("publisher") or ""),
            published_at=str((by_id.get(str(entry["content_item_id"])) or {}).get("published_at") or ""),
        )
        for entry in entries
    ]
