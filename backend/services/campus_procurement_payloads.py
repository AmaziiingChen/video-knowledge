"""Pure payload normalization for SZTU procurement feeds and documents."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode, urlparse

from bs4 import BeautifulSoup, Tag

from services.campus_list_parsing import clean_title, extract_date
from services.campus_source_catalog import (
    PROCUREMENT_SOURCE_SLUG,
    CampusArticle,
    CampusSource,
    get_campus_source,
)

_PROCUREMENT_LIST_BASE_URL = "https://ztb.sztu.edu.cn/sfw_cms/e?page=cms.psms.gglist"
_PROCUREMENT_PROVIDER_PUBLISH_BASE_URL = "https://provider.yuncaitong.cn/publish/"
_PROCUREMENT_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9]{8,80}$")
_PROCUREMENT_PUBLISH_FRAGMENT_RE = re.compile(r"(?:^|/)publish/([A-Za-z0-9]{8,80})(?:$|/)")
_CHINA_TIMEZONE = timezone(timedelta(hours=8))

PROCUREMENT_SECTION_PARAMS: dict[str, dict[str, object]] = {
    "采购公告": {
        "type": ("ZCXQ", "YQXQ", "BYXQ", "CSXQ"),
        "notCollectType": "orient",
        "categoryId": "104791",
        "ggType": "XQ",
        "sort": "sync_time desc",
    },
    "成交公告": {
        "type": ("ZCGG", "ZCGS", "FBGG", "BGGG"),
        "categoryId": "104910",
        "ggType": "GG",
        "sort": "sync_time desc",
    },
    "采购意向": {
        "type": ("YXGK",),
        "categoryId": "103980",
        "sort": "begin_time desc",
    },
    "合同公示": {
        "type": ("HTGS", "HTBG"),
        "categoryId": "104557",
        "sort": "is_top desc,pdate desc",
    },
}


class OcrResult(Protocol):
    status: str
    cloud_submitted: bool
    error: str


def procurement_record_to_article(
    record: dict[str, object],
    *,
    source: CampusSource,
    section: str,
) -> CampusArticle | None:
    record_id = str(record.get("id") or "").strip()
    title = clean_title(str(record.get("subject") or ""))
    if not record_id or len(title) < 4:
        return None
    published_at = extract_date(
        str(record.get("beginTime") or record.get("syncTime") or record.get("pdate") or "")
    )
    keyword = str(record.get("tenderNo") or title).strip()
    detail_url = procurement_detail_url(
        record_id=record_id,
        keyword=keyword,
        section=section,
        sync_id=str(record.get("syncId") or "").strip(),
        new_type=str(record.get("newType") or "").strip(),
        catalog=str(record.get("catalog") or "").strip(),
    )
    return CampusArticle(
        title=title,
        url=detail_url,
        published_at=published_at,
        section=section,
        source_slug=source.slug,
        source_name=source.name,
    )


def procurement_detail_url(
    *,
    record_id: str,
    keyword: str,
    section: str,
    sync_id: str,
    new_type: str,
    catalog: str,
) -> str:
    extra = urlencode({"record_id": record_id, "keyword": keyword, "section": section})
    if sync_id:
        return f"https://ztb.sztu.edu.cn/provider/?{extra}#/publish/{sync_id}"
    if section == "合同公示":
        return f"https://ztb.sztu.edu.cn/sfw_cms/e?page=cms.cgtext&id={record_id}&{extra}"
    if new_type == "1" and catalog:
        return f"https://ztb.sztu.edu.cn/sfw_cms/e?page=cms.detail&cid={catalog}&aid={record_id}&{extra}"
    return f"{_PROCUREMENT_LIST_BASE_URL}&{extra}"


def procurement_cms_content(content_html: object, *, content_selectors: tuple[str, ...]) -> Tag | None:
    """Return inline CMS content, wrapping valid sibling fragments when needed."""
    raw_html = str(content_html or "").strip()
    if not raw_html:
        return None
    soup = BeautifulSoup(raw_html, "html.parser")
    content = _first_node(soup, (*content_selectors, "body", "div"))
    if content is not None:
        return content
    fragment = soup.new_tag("section", attrs={"class": "procurement-cms-content"})
    for node in list(soup.contents):
        fragment.append(node.extract())
    return fragment if fragment.contents else None


def procurement_publish_id(url: str, record: dict[str, object]) -> str:
    candidate = str(record.get("syncId") or "").strip()
    if not candidate:
        candidate = procurement_publish_id_from_fragment(urlparse(url).fragment)
    return candidate if _PROCUREMENT_PROVIDER_ID_RE.fullmatch(candidate) else ""


def procurement_publish_id_from_fragment(fragment: str) -> str:
    match = _PROCUREMENT_PUBLISH_FRAGMENT_RE.search(str(fragment or "").lstrip("#"))
    return match.group(1) if match else ""


def procurement_provider_document_url(detail: dict[str, object], publish_id: str) -> str:
    created_at = provider_datetime(detail.get("createTime"))
    if not created_at:
        return ""
    content_type = str(detail.get("contentType") or "").upper()
    filename = "content.pdf" if content_type == "PDF" else "content.html" if content_type == "HTML" else ""
    if not filename:
        return ""
    date_path = created_at[:10].replace("-", "/")
    return f"{_PROCUREMENT_PROVIDER_PUBLISH_BASE_URL}{date_path}/{publish_id}/{filename}"


def provider_datetime(value: object) -> str:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return ""
    if milliseconds <= 0:
        return ""
    return datetime.fromtimestamp(milliseconds / 1000, _CHINA_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def procurement_pdf_unavailable_text(ocr: OcrResult) -> str:
    if ocr.status == "not_configured":
        return "公告正文以 PDF 形式发布；尚未配置 PaddleOCR，已保留原 PDF 附件。"
    if ocr.status == "empty":
        return "公告正文以 PDF 形式发布；PaddleOCR 未识别出可用文字，可能为扫描件，已保留原 PDF 附件。"
    return "公告正文以 PDF 形式发布；PaddleOCR 识别失败，已保留原 PDF 附件。"


def procurement_document_ocr_metadata(ocr: OcrResult) -> dict[str, object]:
    return {
        "attempted": ocr.status != "not_configured",
        "status": ocr.status,
        "cloud_submitted": ocr.cloud_submitted,
        "error": ocr.error,
    }


def procurement_fallback_article(
    url: str,
    params: dict[str, str],
    *,
    record: dict[str, object] | None = None,
) -> dict[str, object]:
    source = get_campus_source(PROCUREMENT_SOURCE_SLUG)
    title = clean_title(str((record or {}).get("subject") or params.get("keyword") or "采购公告"))
    published_at = extract_date(
        str((record or {}).get("beginTime") or (record or {}).get("syncTime") or "")
    )
    lines = [
        f"公告类别：{params.get('section') or '采购信息'}",
        f"公告标题：{title}",
    ]
    tender_no = str((record or {}).get("tenderNo") or "").strip()
    if tender_no:
        lines.append(f"项目编号：{tender_no}")
    if published_at:
        lines.append(f"发布时间：{published_at}")
    lines.append("正文暂未由该公开接口返回，请通过原始链接查看。")
    body_text = "\n".join(lines)
    return {
        "url": url,
        "platform": "campus",
        "title": title or "采购公告",
        "body_text": body_text,
        "body_html": "<section><p>" + "</p><p>".join(html.escape(line) for line in lines) + "</p></section>",
        "author": source.name,
        "published_at": published_at,
        "images": [],
        "attachments": [],
    }


def _first_node(soup: BeautifulSoup, selectors: tuple[str, ...]) -> Tag | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return None


__all__ = [
    "PROCUREMENT_SECTION_PARAMS",
    "procurement_cms_content",
    "procurement_detail_url",
    "procurement_document_ocr_metadata",
    "procurement_fallback_article",
    "procurement_pdf_unavailable_text",
    "procurement_provider_document_url",
    "procurement_publish_id",
    "procurement_publish_id_from_fragment",
    "procurement_record_to_article",
    "provider_datetime",
]
