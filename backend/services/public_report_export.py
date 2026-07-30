"""Export immutable public-report inputs without exposing local workspace data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from config import settings
from services.database import connect, initialize_database
from services.markdown_sync import get_markdown_state


class PublicReportExportError(RuntimeError):
    """A report cannot yet become a safe public artifact."""


def public_report_slug(report: dict[str, Any]) -> str:
    report_type = str(report.get("report_type") or "range").strip().lower()
    period_start = str(report.get("period_start") or "").strip()
    period_end = str(report.get("period_end") or "").strip()
    content_id = str(report.get("content_item_id") or report.get("id") or "").strip()
    if not content_id or not re.fullmatch(r"[A-Za-z0-9_-]+", content_id):
        raise PublicReportExportError("报告缺少稳定标识，无法生成公开地址")
    period = period_start if period_start == period_end else f"{period_start}--{period_end}"
    period = re.sub(r"[^0-9-]", "", period) or "undated"
    return f"{report_type}-{period}--{content_id[:12]}"


def public_report_url(base_url: str, slug: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized.startswith("https://"):
        raise PublicReportExportError("请先在公众号发布设置中填写 HTTPS 公开网站地址")
    return urljoin(f"{normalized}/", f"reports/{slug}/")


def export_report(content_item_id: str, *, public_base_url: str = "") -> dict[str, Any]:
    """Write one report's public input file and return its immutable address."""
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """SELECT c.id AS content_item_id, c.title, r.report_type, r.period_start,
                      r.period_end, r.source_count, r.source_coverage_json,
                      g.name AS group_name
                 FROM content_items c
                 JOIN wechat_reports r ON r.content_item_id=c.id
                 LEFT JOIN wechat_subscription_groups g ON g.id=r.group_id
                WHERE c.id=? AND c.deleted_at IS NULL""",
            (content_item_id,),
        ).fetchone()
    if row is None:
        raise PublicReportExportError("只有已生成的日报、周报或区间报告可以导出公开页")
    report = dict(row)
    markdown = _redact_public_markdown(get_markdown_state(content_item_id).markdown)
    if not markdown.strip():
        raise PublicReportExportError("报告正文为空，无法生成公开页")
    slug = public_report_slug(report)
    period_start = str(report.get("period_start") or "")
    period_end = str(report.get("period_end") or "")
    source_coverage = _json_list(report.get("source_coverage_json"))
    cited_source_count = len(re.findall(r"(?m)^\[\^[A-Za-z0-9_-]+\]:", markdown))
    payload = {
        "id": content_item_id,
        "slug": slug,
        "title": str(report.get("title") or "报告"),
        "groupName": str(report.get("group_name") or "知识简报"),
        "reportLabel": _report_label(str(report.get("report_type") or "range")),
        "periodLabel": _period_label(period_start, period_end),
        "dayCount": _day_count(period_start, period_end),
        "sourceCount": int(report.get("source_count") or 0),
        "citedSourceCount": cited_source_count,
        "sectionCount": len(re.findall(r"(?m)^##\s+", markdown)),
        "markdown": markdown,
    }
    report_dir = _public_source_root() / "reports" / slug
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(report_dir / "report.json", payload)
    return {
        "slug": slug,
        "relative_path": f"reports/{slug}/",
        "local_path": str(report_dir / "report.json"),
        "public_url": public_report_url(public_base_url, slug) if public_base_url else "",
        **payload,
    }


def refresh_published_manifest() -> dict[str, Any]:
    """Rebuild the public archive from confirmed, not merely drafted, reports."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT p.id, p.report_title, p.public_report_slug, p.public_report_url,
                      p.wechat_article_url, p.published_at, r.report_type, r.period_start,
                      r.period_end, r.source_count, r.source_coverage_json
                 FROM wechat_publications p
                 JOIN wechat_reports r ON r.content_item_id=p.content_item_id
                WHERE p.status='published'
                  AND p.public_report_url != ''
                  AND p.published_at IS NOT NULL
                ORDER BY p.published_at DESC, p.id DESC"""
        ).fetchall()
    reports = []
    for raw in rows:
        row = dict(raw)
        reports.append({
            "id": str(row["id"]),
            "status": "published",
            "title": str(row["report_title"] or "报告"),
            "type": str(row["report_type"] or "range"),
            "period": _period_label(str(row["period_start"] or ""), str(row["period_end"] or "")),
            "publishedAt": str(row["published_at"]),
            "articleCount": int(row["source_count"] or 0),
            "publicUrl": str(row["public_report_url"]),
            "wechatUrl": str(row["wechat_article_url"] or ""),
        })
    payload = {"reports": reports}
    _write_json(_public_source_root() / "published-reports.json", payload)
    return payload


def _public_source_root() -> Path:
    root = Path(settings.public_report_source_dir).expanduser()
    if not root.name:
        raise PublicReportExportError("公开网站导出目录无效")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _json_list(value: Any) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []


def _report_label(value: str) -> str:
    return {"daily": "日报", "weekly": "周报", "range": "区间汇总"}.get(value, "知识简报")


def _period_label(start: str, end: str) -> str:
    if start and end:
        return start if start == end else f"{start} — {end}"
    return start or end or "未标注时间"


def _day_count(start: str, end: str) -> int:
    try:
        from datetime import date
        return max(1, (date.fromisoformat(end) - date.fromisoformat(start)).days + 1)
    except ValueError:
        return 1


def _redact_public_markdown(markdown: str) -> str:
    value = str(markdown or "")
    value = re.sub(r"(?i)(密码(?:为|是|：|:)?\s*`?)[^`\n\s]+", r"\1[已省略]", value)
    value = re.sub(r"(?i)(?:access[_ -]?token|appsecret|cookie)\s*(?:=|：|:)\s*[^\s`]+", "[敏感配置已省略]", value)
    return value
