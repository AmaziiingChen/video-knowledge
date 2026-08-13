"""Transport models for locally rendered article previews."""

from __future__ import annotations

import html
import re

from pydantic import BaseModel, Field

from services.campus_sources import is_campus_attachment_blacklisted


class ArticlePreviewResponse(BaseModel):
    content_item_id: str
    title: str
    author: str = ""
    published_at: str = ""
    html: str
    source_html: str = ""
    gallery: list[dict[str, object]] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)
    formatting_status: str = "not_applicable"
    formatting_detail: str = ""


def safe_article_attachments(value: object, *, filter_campus_navigation: bool = False) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value[:100]:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        name = str(raw.get("name") or "未命名附件").strip()[:300] or "未命名附件"
        if filter_campus_navigation and is_campus_attachment_blacklisted(name):
            continue
        seen.add(url)
        attachments.append({"name": name, "url": url, "download_type": "direct" if raw.get("download_type") == "direct" else "external"})
    return attachments


def xiaohongshu_description_from_html(body_html: str) -> str:
    """Recover legacy descriptions without ever reading OCR sidecars."""
    paragraphs = re.sub(r"</(?:p|div|section)\s*>", "\n", str(body_html or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", paragraphs)
    return html.unescape(text).strip()


def is_legacy_document_markdown_preview(article_info: dict, body_html: str) -> bool:
    document_ocr = article_info.get("document_ocr")
    if not isinstance(document_ocr, dict) or not document_ocr:
        return False
    return bool(re.search(r"&lt;/?(?:table|thead|tbody|tr|td|th)\b", body_html, re.IGNORECASE))
