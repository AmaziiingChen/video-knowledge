from __future__ import annotations

from datetime import date
import logging
import re
import time
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

from services.network_policy import direct_requests_session
from bs4 import BeautifulSoup, Tag
from services.campus_source_catalog import (
    CAMPUS_SOURCES,
    CampusArticle,
    CampusSource,
    PROCUREMENT_SOURCE_SLUG as _PROCUREMENT_SOURCE_SLUG,
    campus_source_for_url,
    get_campus_source,
    is_allowed_campus_host as _is_allowed_campus_host,
    is_campus_article_url,
)
from services.campus_html_content import (
    absolutize_content_urls as _absolutize_content_urls,
    article_attachment_scope as _article_attachment_scope,
    attachment_name_from_url as _attachment_name_from_url,
    dedupe_attachments as _dedupe_attachments,
)
from services.campus_list_parsing import (
    clean_title as _clean_title,
    extract_date as _extract_date,
    parse_campus_list,
)
from services.campus_procurement_payloads import (
    PROCUREMENT_SECTION_PARAMS as _PROCUREMENT_SECTION_PARAMS,
    procurement_cms_content,
    procurement_detail_url as _procurement_detail_url,  # noqa: F401 - compatibility alias
    procurement_document_ocr_metadata as _procurement_document_ocr_metadata,
    procurement_fallback_article as _procurement_fallback_article,
    procurement_pdf_unavailable_text as _procurement_pdf_unavailable_text,
    procurement_provider_document_url as _procurement_provider_document_url,
    procurement_publish_id as _procurement_publish_id,
    procurement_publish_id_from_fragment as _procurement_publish_id_from_fragment,  # noqa: F401 - compatibility alias
    procurement_record_to_article as _procurement_record_to_article,
    provider_datetime as _provider_datetime,
)
from services.campus_document_rendering import (
    render_document_markdown_html,  # noqa: F401 - public compatibility re-export
    text_to_article_html as _text_to_article_html,
)
from services.paddle_ocr import recognize_document_bytes


logger = logging.getLogger(__name__)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_ATTACHMENT_URL_RE = re.compile(
    r"(?:download\.jsp|downloadattachurl|clickdown|\.(?:pdf|docx?|xlsx?|pptx?|zip|rar)(?:$|[?#]))",
    re.IGNORECASE,
)
_ATTACHMENT_NAME_BLACKLIST = ("实验室介绍", "返回顶部", "打印本页", "关闭窗口")
_ARTICLE_CONTENT_SELECTORS = (
    "div.v_news_content",
    "#vsb_content",
    "#js_content",
    ".article-content",
    ".article-body",
    ".news-content",
    ".news_conent_two_text",
    ".content_detail",
    ".show_content",
    ".content_m",
    "article",
    "main",
    "div.content",
)
_PROCUREMENT_API_URL = "https://ztb.sztu.edu.cn/sfw_cms/e"
_PROCUREMENT_PROVIDER_API_BASE_URL = "https://provider.yuncaitong.cn/api/publish/"
_PROCUREMENT_PROVIDER_HOST = "provider.yuncaitong.cn"



def discover_campus_articles(
    source_slug: str,
    *,
    section: str | None = None,
    limit: int = 20,
    published_after: date | None = None,
    published_before: date | None = None,
    known_urls: set[str] | None = None,
    session: requests.Session | None = None,
) -> list[CampusArticle]:
    source = get_campus_source(source_slug)
    if section and section not in source.sections:
        raise ValueError(f"{source.name} 没有板块“{section}”")
    selected_sections = {section: source.sections[section]} if section else source.sections
    owned_session = session is None
    client = session or direct_requests_session()
    try:
        maximum = max(1, min(int(limit), 300))
        if source.slug == _PROCUREMENT_SOURCE_SLUG:
            return _discover_sztu_procurement_articles(
                client,
                source=source,
                sections=selected_sections,
                maximum=maximum,
                published_after=published_after,
                published_before=published_before,
                known_urls=known_urls,
            )
        articles: list[CampusArticle] = []
        seen_urls: set[str] = set()
        failures: list[Exception] = []
        for section_name, section_url in selected_sections.items():
            try:
                if source.slug == "gwt" and published_after:
                    _discover_gwt_pages(
                        client,
                        source=source,
                        section=section_name,
                        section_url=section_url,
                        published_after=published_after,
                        published_before=published_before,
                        maximum=maximum,
                        articles=articles,
                    seen_urls=seen_urls,
                    known_urls=known_urls,
                    )
                    continue
                discovered = _discover_college_section(
                    client,
                    source=source,
                    section=section_name,
                    section_url=section_url,
                    maximum=maximum,
                    published_after=published_after,
                    published_before=published_before,
                    known_urls=known_urls,
                )
            except Exception as exc:
                failures.append(exc)
                logger.warning("校园来源 %s 的板块“%s”抓取失败: %s", source.name, section_name, exc)
                continue
            for article in discovered:
                if article.url in seen_urls:
                    continue
                seen_urls.add(article.url)
                articles.append(article)
        if not articles and failures:
            raise failures[0]
        articles.sort(key=lambda item: item.published_at or "", reverse=True)
        return articles[:maximum]
    finally:
        if owned_session:
            client.close()


def _discover_sztu_procurement_articles(
    session: requests.Session,
    *,
    source: CampusSource,
    sections: dict[str, str],
    maximum: int,
    published_after: date | None,
    published_before: date | None,
    known_urls: set[str] | None,
) -> list[CampusArticle]:
    """Read the public procurement feed exposed by the CMS' own front end."""
    articles: list[CampusArticle] = []
    seen_urls: set[str] = set()
    for section in sections:
        params = _PROCUREMENT_SECTION_PARAMS[section]
        payload = dict(params)
        payload["limit"] = maximum
        try:
            records = _query_sztu_procurement(session, payload).get("resultset") or []
        except Exception as exc:
            logger.warning("采购站板块“%s”抓取失败: %s", section, exc)
            continue
        reached_known = False
        for record in records:
            if not isinstance(record, dict):
                continue
            article = _procurement_record_to_article(record, source=source, section=section)
            if not article or article.url in seen_urls:
                continue
            seen_urls.add(article.url)
            if known_urls and article.url in known_urls:
                reached_known = True
                break
            article_date = _published_date(article.published_at)
            if article_date and published_after and article_date < published_after:
                continue
            if article_date and published_before and article_date > published_before:
                continue
            articles.append(article)
            if len(articles) >= maximum:
                break
        if reached_known or len(articles) >= maximum:
            break
    articles.sort(key=lambda item: item.published_at or "", reverse=True)
    return articles[:maximum]


def _query_sztu_procurement(
    session: requests.Session,
    params: dict[str, object],
) -> dict[str, object]:
    """Call the public JSON endpoint used by the procurement web UI."""
    payload: list[tuple[str, str]] = [
        ("page", "cms.psms.publish.query"),
        ("window_", "json"),
        ("request_method_", "ajax"),
        ("browser_", "notmsie"),
    ]
    for key, value in params.items():
        if isinstance(value, (tuple, list)):
            payload.extend((f"{key}[]", str(item)) for item in value)
        elif value is not None:
            payload.append((key, str(value)))
    response = session.post(
        _PROCUREMENT_API_URL,
        data=payload,
        headers={"User-Agent": _USER_AGENT, "X-Requested-With": "XMLHttpRequest"},
        timeout=(10, 30),
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("采购站公开接口返回了非对象数据")
    return data


def _discover_college_section(
    session: requests.Session,
    *,
    source: CampusSource,
    section: str,
    section_url: str,
    maximum: int,
    published_after: date | None = None,
    published_before: date | None = None,
    known_urls: set[str] | None = None,
) -> list[CampusArticle]:
    """Follow the site's real next-page links until this section has enough rows."""
    articles: list[CampusArticle] = []
    seen_articles: set[str] = set()
    seen_pages: set[str] = set()
    page_url = section_url
    for _ in range(50):
        if not page_url or page_url in seen_pages or len(articles) >= maximum:
            break
        seen_pages.add(page_url)
        response = _safe_get(session, page_url)
        page_articles = parse_campus_list(response.text, source=source, section=section)
        reached_known = False
        for article in page_articles:
            if article.url in seen_articles:
                continue
            seen_articles.add(article.url)
            if known_urls and article.url in known_urls:
                reached_known = True
                break
            article_date = _published_date(article.published_at)
            if article_date and published_after and article_date < published_after:
                continue
            if article_date and published_before and article_date > published_before:
                continue
            articles.append(article)
            if len(articles) >= maximum:
                break
        if reached_known:
            break
        page_url = _next_page_url(response.text, response.url)
    return articles


def _next_page_url(html: str, current_url: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for anchor in soup.find_all("a", href=True):
        label = "".join(anchor.get_text(" ", strip=True).split())
        if label not in {"下页", "下一页"}:
            continue
        href = str(anchor.get("href") or "").strip()
        if href and not href.lower().startswith(("javascript:", "#")):
            return urljoin(current_url, href)
    return ""


def _discover_gwt_pages(
    session: requests.Session,
    *,
    source: CampusSource,
    section: str,
    section_url: str,
    published_after: date,
    published_before: date | None,
    maximum: int,
    articles: list[CampusArticle],
    seen_urls: set[str],
    known_urls: set[str] | None = None,
) -> bool:
    """Read newest-first GWT pages until the requested date window is covered."""
    for page in range(1, 51):
        response = _safe_get(session, _gwt_page_url(section_url, page))
        discovered = parse_campus_list(response.text, source=source, section=section)
        if not discovered:
            return False

        page_dates: list[date] = []
        unseen_on_page = 0
        reached_known = False
        for article in discovered:
            article_date = _published_date(article.published_at)
            if article_date:
                page_dates.append(article_date)
            if article.url in seen_urls:
                continue
            seen_urls.add(article.url)
            if known_urls and article.url in known_urls:
                reached_known = True
                break
            unseen_on_page += 1
            if article_date and article_date < published_after:
                continue
            if article_date and published_before and article_date > published_before:
                continue
            articles.append(article)
            if len(articles) >= maximum:
                return True

        if reached_known:
            return True

        if unseen_on_page == 0:
            return False
        if page_dates and all(value < published_after for value in page_dates):
            return False
    return False


def _gwt_page_url(section_url: str, page: int) -> str:
    parsed = urlparse(section_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["PAGENUM"] = str(page)
    return urlunparse(parsed._replace(query=urlencode(query)))


def _published_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None



def fetch_campus_article(
    url: str,
    *,
    session: requests.Session | None = None,
    content_item_id: str | None = None,
) -> dict[str, object]:
    if not is_campus_article_url(url):
        raise ValueError("只允许抓取已配置的校园官网文章")
    owned_session = session is None
    client = session or direct_requests_session()
    try:
        return _fetch_campus_article_with_session(url, client, content_item_id=content_item_id)
    finally:
        if owned_session:
            client.close()


def _fetch_campus_article_with_session(
    url: str,
    session: requests.Session,
    *,
    content_item_id: str | None = None,
) -> dict[str, object]:
    if _is_sztu_procurement_article_url(url):
        return _fetch_sztu_procurement_article(url, session, content_item_id=content_item_id)
    response = _safe_get(session, url, allow_wechat_redirect=True)
    soup = BeautifulSoup(response.text or "", "html.parser")
    redirect_url = _wechat_redirect_target(response.url, response.text or "", soup)
    if redirect_url:
        return {
            "url": response.url,
            "platform": "wechat_redirect",
            "redirect_url": redirect_url,
        }
    source = campus_source_for_url(response.url) or campus_source_for_url(url)
    title = _extract_article_title(soup, source=source)
    published_at = _extract_article_date(soup)
    content = _first_node(soup, _ARTICLE_CONTENT_SELECTORS)
    if content is None:
        raise ValueError("未找到校园文章正文，可能是页面模板已调整")
    download_type = "direct" if source and source.slug == "gwt" else "external"
    attachments = _extract_attachments(
        _article_attachment_scope(content),
        response.url,
        download_type=download_type,
    )
    attachments.extend(
        _append_same_origin_iframe_content(
            content,
            response.url,
            download_type=download_type,
            session=session,
        )
    )
    attachments = _dedupe_attachments(attachments)
    for node in content.find_all(("script", "style", "noscript", "iframe", "form", "button")):
        node.decompose()
    images: list[str] = []
    for image in content.find_all("img"):
        src = str(image.get("data-src") or image.get("src") or "").strip()
        absolute = urljoin(response.url, src)
        if absolute.startswith(("http://", "https://")):
            image["src"] = absolute
            image.attrs.pop("data-src", None)
            if absolute not in images:
                images.append(absolute)
    for anchor in content.find_all("a", href=True):
        anchor["href"] = urljoin(response.url, str(anchor.get("href") or ""))
    body_text = _clean_text(content.get_text("\n", strip=True))
    if len(body_text) < 20 and not images and not attachments:
        raise ValueError("校园文章正文过短，页面可能只包含附件或图片")
    return {
        "url": response.url,
        "platform": "campus",
        "title": title or "未命名校园文章",
        "body_text": body_text,
        "body_html": str(content),
        "author": _extract_article_author(soup, source=source),
        "published_at": published_at,
        "images": images,
        "attachments": attachments,
    }


def _is_sztu_procurement_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        (parsed.hostname or "").lower() == "ztb.sztu.edu.cn"
        and bool(parse_qsl(parsed.query, keep_blank_values=True))
        and "record_id" in dict(parse_qsl(parsed.query, keep_blank_values=True))
    )


def _fetch_sztu_procurement_article(
    url: str,
    session: requests.Session,
    *,
    content_item_id: str | None = None,
) -> dict[str, object]:
    params = dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    record_id = params.get("record_id", "").strip()
    section = params.get("section", "").strip()
    keyword = params.get("keyword", "").strip()
    section_params = dict(_PROCUREMENT_SECTION_PARAMS.get(section, {}))
    section_params["limit"] = 25
    if keyword:
        section_params["keywords"] = keyword
    records = _query_sztu_procurement(session, section_params).get("resultset") or []
    record = next(
        (item for item in records if isinstance(item, dict) and str(item.get("id") or "") == record_id),
        None,
    )
    if not isinstance(record, dict):
        return _procurement_fallback_article(url, params)

    source = get_campus_source(_PROCUREMENT_SOURCE_SLUG)
    title = _clean_title(str(record.get("subject") or "")) or "未命名采购公告"
    published_at = _extract_date(str(record.get("beginTime") or record.get("syncTime") or record.get("pdate") or ""))
    content = _procurement_cms_content(record.get("contentHtml"))
    if content is None:
        provider_article = _fetch_sztu_procurement_provider_article(
            url,
            session,
            record=record,
            title=title,
            published_at=published_at,
            content_item_id=content_item_id,
        )
        return provider_article or _procurement_fallback_article(url, params, record=record)

    _absolutize_content_urls(content, _PROCUREMENT_API_URL)
    attachments = _extract_attachments(content, _PROCUREMENT_API_URL, download_type="external")
    images: list[str] = []
    for image in content.find_all("img"):
        image_url = str(image.get("src") or "").strip()
        if image_url.startswith(("http://", "https://")) and image_url not in images:
            images.append(image_url)
    for node in content.find_all(("script", "style", "noscript", "iframe", "form", "button")):
        node.decompose()
    body_text = _clean_text(content.get_text("\n", strip=True))
    if len(body_text) < 20:
        provider_article = _fetch_sztu_procurement_provider_article(
            url,
            session,
            record=record,
            title=title,
            published_at=published_at,
            content_item_id=content_item_id,
        )
        return provider_article or _procurement_fallback_article(url, params, record=record)
    return {
        "url": url,
        "platform": "campus",
        "title": title,
        "body_text": body_text,
        "body_html": str(content),
        "author": source.name,
        "published_at": published_at,
        "images": images,
        "attachments": attachments,
    }


def _procurement_cms_content(content_html: object) -> Tag | None:
    return procurement_cms_content(content_html, content_selectors=_ARTICLE_CONTENT_SELECTORS)


def _fetch_sztu_procurement_provider_article(
    url: str,
    session: requests.Session,
    *,
    record: dict[str, object],
    title: str,
    published_at: str,
    content_item_id: str | None,
) -> dict[str, object] | None:
    """Read a public Yuncaitong detail document linked by the provider SPA.

    The SZTU CMS list endpoint intentionally returns only announcement metadata
    for many records.  Its public provider page then uses the ``syncId`` to
    retrieve an HTML or PDF document from the Yuncaitong publication service.
    This stays limited to a fixed public host and a validated opaque ID.
    """
    publish_id = _procurement_publish_id(url, record)
    if not publish_id:
        return None
    detail = _fetch_procurement_provider_json(session, publish_id)
    if not detail:
        return None

    document_url = _procurement_provider_document_url(detail, publish_id)
    if not document_url:
        return None
    content_type = str(detail.get("contentType") or "").upper()
    resolved_title = _clean_title(str(detail.get("subject") or title)) or title
    resolved_published_at = published_at or _provider_datetime(detail.get("createTime"))
    if content_type == "PDF":
        return _fetch_procurement_provider_pdf(
            session,
            url=url,
            document_url=document_url,
            title=resolved_title,
            published_at=resolved_published_at,
            content_item_id=content_item_id,
        )
    if content_type == "HTML":
        return _fetch_procurement_provider_html(
            session,
            url=url,
            document_url=document_url,
            title=resolved_title,
            published_at=resolved_published_at,
        )
    return None


def _fetch_procurement_provider_json(
    session: requests.Session,
    publish_id: str,
) -> dict[str, object] | None:
    response = _safe_get_procurement_provider(
        session,
        f"{_PROCUREMENT_PROVIDER_API_BASE_URL}{publish_id}",
    )
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict) or str(payload.get("id") or "") != publish_id:
        return None
    return payload


def _fetch_procurement_provider_pdf(
    session: requests.Session,
    *,
    url: str,
    document_url: str,
    title: str,
    published_at: str,
    content_item_id: str | None,
) -> dict[str, object] | None:
    response = _safe_get_procurement_provider(session, document_url)
    payload = response.content
    if not payload.startswith(b"%PDF-"):
        return None
    ocr = recognize_document_bytes(
        payload,
        url=document_url,
        filename=f"{title or 'procurement-notice'}.pdf",
        content_type="application/pdf",
        content_item_id=content_item_id,
    )
    document_markdown = str(ocr.text or "").strip()
    body_text = _clean_text(document_markdown)
    attachment = {
        "name": f"{title or '采购公告'}.pdf",
        "url": document_url,
        "download_type": "external",
    }
    if len(body_text) < 20:
        body_text = _procurement_pdf_unavailable_text(ocr)
    return {
        "url": url,
        "platform": "campus",
        "title": title or "采购公告",
        "body_text": body_text,
        # Keep OCR Markdown intact for the reading view.  Its blank lines
        # carry heading/list boundaries and its embedded HTML tables retain
        # merged cells; ``body_text`` above is the compact search/AI form.
        "body_html": _text_to_article_html(document_markdown or body_text),
        "document_markdown": document_markdown,
        "author": get_campus_source(_PROCUREMENT_SOURCE_SLUG).name,
        "published_at": published_at,
        "images": [],
        "attachments": [attachment],
        "document_ocr": _procurement_document_ocr_metadata(ocr),
    }


def _fetch_procurement_provider_html(
    session: requests.Session,
    *,
    url: str,
    document_url: str,
    title: str,
    published_at: str,
) -> dict[str, object] | None:
    response = _safe_get_procurement_provider(session, document_url)
    soup = BeautifulSoup(response.text or "", "html.parser")
    content = _first_node(soup, (*_ARTICLE_CONTENT_SELECTORS, "body", "div"))
    if content is None:
        return None
    _absolutize_content_urls(content, document_url)
    body_text = _clean_text(content.get_text("\n", strip=True))
    if len(body_text) < 20:
        return None
    return {
        "url": url,
        "platform": "campus",
        "title": title or "采购公告",
        "body_text": body_text,
        "body_html": str(content),
        "author": get_campus_source(_PROCUREMENT_SOURCE_SLUG).name,
        "published_at": published_at,
        "images": [],
        "attachments": _extract_attachments(content, document_url, download_type="external"),
    }


def _safe_get_procurement_provider(session: requests.Session, url: str) -> requests.Response:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != _PROCUREMENT_PROVIDER_HOST:
        raise ValueError("采购公告正文地址不在允许的公开服务域名内")
    response = session.get(
        url,
        headers={"User-Agent": _USER_AGENT},
        timeout=(10, 30),
        allow_redirects=False,
    )
    response.raise_for_status()
    return response


def _extract_article_title(soup: BeautifulSoup, *, source: CampusSource | None) -> str:
    for attrs in (
        {"name": "ArticleTitle"},
        {"name": "Title"},
        {"property": "og:title"},
    ):
        meta = soup.find("meta", attrs=attrs)
        value = str(meta.get("content") or "").strip() if isinstance(meta, Tag) else ""
        if value:
            return _clean_title(value)

    raw = soup.title.get_text(" ", strip=True) if soup.title else ""
    title = " ".join(raw.split()).lstrip("|｜ ")
    aliases = {source.name, source.name.removesuffix("学院")} if source else set()
    while "-" in title:
        prefix, _, suffix = title.rpartition("-")
        suffix = suffix.strip()
        if not suffix:
            title = prefix.strip()
            continue
        if suffix in aliases or any(marker in suffix for marker in ("深圳技术大学", "学院", "School", "SZTU")):
            title = prefix.rstrip(" -|｜")
            continue
        break
    if title:
        return _clean_title(title)
    return _first_text(soup, (".article-title", ".content-title", "h1", "h2.title"))


def _extract_article_date(soup: BeautifulSoup) -> str:
    for selector in (
        "time[datetime]",
        ".c-ifo",
        ".detail_message .message_right",
        ".page_content_head",
        ".news_conent_two_js",
        ".parameter > .date",
        ".ar_title",
        ".con_title .info",
        ".newsd-left",
        ".show-time",
        ".article_box .sub_box",
        ".v_news_info",
        ".content_t",
        ".cnt_note",
        ".article-meta",
        ".news_info",
        ".article-time",
        ".detail_message",
        ".message_right",
    ):
        node = soup.select_one(selector)
        raw_value = ""
        if isinstance(node, Tag):
            raw_value = str(node.get("datetime") or "") or node.get_text(" ", strip=True)
        value = _extract_date(raw_value)
        if value:
            return value
    meta = soup.find("meta", attrs={"name": re.compile(r"^(?:PubDate|publishdate)$", re.IGNORECASE)})
    if isinstance(meta, Tag):
        value = _extract_date(str(meta.get("content") or ""))
        if value:
            return value
    return _extract_date(soup.get_text(" ", strip=True))


def _extract_article_author(soup: BeautifulSoup, *, source: CampusSource | None) -> str:
    for selector in (".c-ifo", ".v_news_info", ".article-meta", ".news_info"):
        node = soup.select_one(selector)
        if not isinstance(node, Tag):
            continue
        text = " ".join(node.get_text(" ", strip=True).split())
        match = re.search(
            r"信息来源\s*[:：]\s*(.*?)(?=\s*(?:浏览量|时间|发布日期)\s*[:：]|$)",
            text,
        )
        if match:
            author = _clean_title(match.group(1))
            if author:
                return author[:200]
    return source.name if source else "深圳技术大学"


def _append_same_origin_iframe_content(
    content: Tag,
    page_url: str,
    *,
    download_type: str,
    session: requests.Session,
) -> list[dict[str, str]]:
    page_host = (urlparse(page_url).hostname or "").lower()
    iframe_urls: list[str] = []
    for iframe in content.find_all(("iframe", "frame")):
        src = str(iframe.get("src") or iframe.get("data-src") or iframe.get("data-original") or "").strip()
        absolute = urljoin(page_url, src)
        if not absolute.startswith(("http://", "https://")):
            continue
        if (urlparse(absolute).hostname or "").lower() != page_host or absolute in iframe_urls:
            continue
        iframe_urls.append(absolute)
        if len(iframe_urls) >= 3:
            break
    if not iframe_urls:
        return []

    attachments: list[dict[str, str]] = []
    for iframe_url in iframe_urls:
        try:
            response = _safe_get(session, iframe_url)
        except Exception as exc:
            logger.warning("校园文章内嵌页面抓取失败 %s: %s", iframe_url, exc)
            continue
        frame_soup = BeautifulSoup(response.text or "", "html.parser")
        frame_content = _first_node(frame_soup, (*_ARTICLE_CONTENT_SELECTORS, "body"))
        if frame_content is None:
            continue
        attachments.extend(
            _extract_attachments(
                _article_attachment_scope(frame_content),
                response.url,
                download_type=download_type,
            )
        )
        _absolutize_content_urls(frame_content, response.url)
        wrapper_soup = BeautifulSoup("<section data-campus-iframe-content></section>", "html.parser")
        wrapper = wrapper_soup.section
        if isinstance(wrapper, Tag):
            wrapper.append(frame_content)
            content.append(wrapper)
    return attachments


def _extract_attachments(scope: Tag, base_url: str, *, download_type: str) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for anchor in scope.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if not _ATTACHMENT_URL_RE.search(absolute):
            continue
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = (urlparse(absolute).hostname or "").lower()
        # College attachments may legitimately live on a school CDN or a
        # third-party form service and are only opened in the user's browser.
        # GWT attachments are downloaded with the authenticated WebVPN session,
        # so those must remain on a configured campus host.
        if download_type == "direct" and not _is_allowed_campus_host(host):
            continue
        if absolute in seen_urls:
            continue
        name = _clean_title(anchor.get_text(" ", strip=True)) or _attachment_name_from_url(absolute)
        if is_campus_attachment_blacklisted(name):
            continue
        seen_urls.add(absolute)
        attachments.append(
            {
                "name": name[:300] or "未命名附件",
                "url": absolute,
                "download_type": download_type,
            }
        )
    return attachments


def is_campus_attachment_blacklisted(name: str) -> bool:
    normalized = _clean_title(name)
    return any(keyword in normalized for keyword in _ATTACHMENT_NAME_BLACKLIST)



def _safe_get(
    session: requests.Session,
    url: str,
    *,
    allow_wechat_redirect: bool = False,
) -> requests.Response:
    last_error: requests.RequestException | None = None
    for attempt in range(3):
        try:
            return _safe_get_once(
                session,
                url,
                allow_wechat_redirect=allow_wechat_redirect,
            )
        except requests.RequestException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code is not None and status_code not in {429, 500, 502, 503, 504}:
                raise
            last_error = exc
            if attempt < 2:
                time.sleep(0.2 * (2 ** attempt))
    if last_error:
        raise last_error
    raise ValueError("校园来源抓取失败")


def _safe_get_once(
    session: requests.Session,
    url: str,
    *,
    allow_wechat_redirect: bool,
) -> requests.Response:
    current_url = url
    for _ in range(4):
        host = (urlparse(current_url).hostname or "").lower()
        if not _is_allowed_campus_host(host) and not (
            allow_wechat_redirect and host == "mp.weixin.qq.com"
        ):
            raise ValueError("校园来源跳转到了未授权域名，已停止抓取")
        response = session.get(
            current_url,
            headers={"User-Agent": _USER_AGENT},
            timeout=(8, 25),
            allow_redirects=False,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = str(response.headers.get("Location") or "").strip()
            if not location:
                break
            current_url = urljoin(current_url, location)
            continue
        if response.status_code in {429, 500, 502, 503, 504}:
            response.raise_for_status()
        response.raise_for_status()
        if not response.encoding or response.encoding.lower() == "iso-8859-1":
            response.encoding = response.apparent_encoding or "utf-8"
        return response
    raise ValueError("校园来源重定向次数过多")


def _wechat_redirect_target(response_url: str, html: str, soup: BeautifulSoup) -> str:
    if (urlparse(response_url).hostname or "").lower() == "mp.weixin.qq.com":
        return response_url

    meta = soup.find("meta", attrs={"http-equiv": re.compile(r"^refresh$", re.IGNORECASE)})
    if meta:
        content = str(meta.get("content") or "")
        match = re.search(r"(?:^|;)\s*url\s*=\s*['\"]?([^'\";]+)", content, re.IGNORECASE)
        if match:
            candidate = urljoin(response_url, match.group(1).strip())
            if _is_wechat_article_target(candidate):
                return candidate

    script_match = re.search(
        r"(?:window\.)?location(?:\.href)?\s*=\s*['\"](https://mp\.weixin\.qq\.com/[^'\"]+)",
        html,
        re.IGNORECASE,
    )
    if script_match and _is_wechat_article_target(script_match.group(1)):
        return script_match.group(1)

    visible_text = _clean_text(soup.get_text("\n", strip=True))
    wechat_links = list(
        dict.fromkeys(
            urljoin(response_url, str(anchor.get("href") or "").strip())
            for anchor in soup.find_all("a", href=True)
            if _is_wechat_article_target(
                urljoin(response_url, str(anchor.get("href") or "").strip())
            )
        )
    )
    # A short intermediary page with one WeChat article link is a pointer, not
    # a second news document. Normal college articles can still contain WeChat
    # links without being redirected.
    if len(visible_text) < 200 and len(wechat_links) == 1:
        return wechat_links[0]
    return ""


def _is_wechat_article_target(value: str) -> bool:
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "mp.weixin.qq.com" and parsed.path.startswith("/s")



def _clean_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in str(value or "").splitlines()]
    return "\n".join(line for index, line in enumerate(lines) if line and (index == 0 or line != lines[index - 1]))


def _first_node(soup: BeautifulSoup, selectors: Iterable[str]) -> Tag | None:
    for selector in selectors:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            return node
    return None


def _first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    node = _first_node(soup, selectors)
    return node.get_text(" ", strip=True) if node else ""


__all__ = [
    "CAMPUS_SOURCES",
    "CampusArticle",
    "CampusSource",
    "campus_source_for_url",
    "discover_campus_articles",
    "fetch_campus_article",
    "get_campus_source",
    "is_campus_attachment_blacklisted",
    "is_campus_article_url",
    "parse_campus_list",
]
