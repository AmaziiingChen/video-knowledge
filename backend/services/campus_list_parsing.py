"""Pure DOM parsing and text normalization for campus source lists."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from services.campus_html_content import candidate_nodes
from services.campus_source_catalog import (
    CampusArticle,
    CampusSource,
    is_allowed_campus_host,
)
from services.published_at import extract_published_at

_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?(?!\d)")
_ENGLISH_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2}),\s*(20\d{2})\b",
    re.IGNORECASE,
)
_ARTICLE_URL_HINT_RE = re.compile(r"/(?:info|content|article|show)/|[?&](?:id|contentid)=", re.IGNORECASE)


def extract_date(text: str) -> str:
    return extract_published_at(text)


def clean_title(value: str) -> str:
    title = " ".join(str(value or "").split())
    title = _DATE_RE.sub("", title)
    title = _ENGLISH_DATE_RE.sub("", title)
    return re.sub(r"^\d+[.、\s]+", "", title).strip(" -|·")


def parse_campus_list(html: str, *, source: CampusSource, section: str) -> list[CampusArticle]:
    soup = BeautifulSoup(html or "", "html.parser")
    nodes = list(candidate_nodes(soup, source.list_selectors))
    if not nodes:
        nodes = _source_fallback_nodes(soup, source.slug)
    articles: list[CampusArticle] = []
    seen_urls: set[str] = set()
    for node in nodes:
        article = _parse_list_node(node, source=source, section=section)
        if not article or article.url in seen_urls:
            continue
        seen_urls.add(article.url)
        articles.append(article)
    return articles


def _source_fallback_nodes(soup: BeautifulSoup, source_slug: str) -> list[Tag]:
    selectors = {
        "ai": ".filterList_row[href], .havePictureList_list a[href], .news_list a[href]",
        "nmne": "li[id^='line_'], ul.list-gl li",
        "sgim": ".content-list .item, .item",
        "utl": "div.new_center_item, div.new_item",
        "hsee": ".n_tulist li, .n_list li",
        "cep": ".main_list li",
        "cop": ".article-card[onclick], .no-pic-article-item[onclick]",
        "design": "li.news-item, a.notice-item",
        "business": "ul.list-gl > li, ul.news-list > li, .list-box .list ul > li",
        "icoc": ".nopicturelist_main > ul > li, .havepicturelist1 > ul > li, ul.list_pic > li",
        "future-tech": "ul.hireBox > li, ul.listBox > li",
        "sfl": "ul.news_fly > li, ul.picture_fly > li",
        "music": "ul.picture_fly li, .list ul li, .news_list ul li, .list-box ul li",
    }
    selected = soup.select(selectors.get(source_slug, "main li, .content li, .list li, .news li"))
    return [node for node in selected if isinstance(node, Tag)]


def _parse_list_node(node: Tag, *, source: CampusSource, section: str) -> CampusArticle | None:
    if source.slug == "cop":
        return _parse_cop_list_node(node, source=source, section=section)
    anchor = node if node.name == "a" and node.get("href") else node.find("a", href=True)
    if not isinstance(anchor, Tag):
        return None
    href = str(anchor.get("href") or "").strip()
    if not href or href.lower().startswith(("javascript:", "mailto:", "#")):
        return None
    url = urljoin(source.base_url, href)
    host = (urlparse(url).hostname or "").lower()
    is_wechat_link = host == "mp.weixin.qq.com"
    if not is_allowed_campus_host(host) and not is_wechat_link:
        return None
    if is_wechat_link and not source.include_wechat_links:
        return None
    title = _extract_list_title(anchor, source_slug=source.slug) or anchor.get_text(" ", strip=True)
    title = clean_title(title)
    if len(title) < 4:
        return None
    published_at = _extract_list_date(node, source_slug=source.slug, section=section)
    if not published_at and not _ARTICLE_URL_HINT_RE.search(url):
        return None
    department = ""
    if source.slug == "gwt":
        department_node = node.select_one("div.width03 a")
        department = department_node.get_text(" ", strip=True) if department_node else ""
    return CampusArticle(
        title=title,
        url=url,
        published_at=published_at,
        section=section,
        source_slug=source.slug,
        source_name=source.name,
        department=department,
    )


def _parse_cop_list_node(
    node: Tag,
    *,
    source: CampusSource,
    section: str,
) -> CampusArticle | None:
    onclick = str(node.get("onclick") or "")
    match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)", onclick, re.IGNORECASE)
    if not match:
        return None
    url = urljoin(source.base_url, match.group(1).strip())
    title_node = node.select_one(".event-title, .article-item-title")
    title = clean_title(title_node.get_text(" ", strip=True) if title_node else "")
    if not title:
        image = node.find("img", alt=True)
        title = clean_title(str(image.get("alt") or "")) if isinstance(image, Tag) else ""
    date_node = node.select_one(".image-date, .article-item-date")
    published_at = extract_date(_node_text(date_node))
    if len(title) < 4 or not published_at:
        return None
    return CampusArticle(
        title=title,
        url=url,
        published_at=published_at,
        section=section,
        source_slug=source.slug,
        source_name=source.name,
    )


def _extract_list_date(node: Tag, *, source_slug: str, section: str) -> str:
    if source_slug == "utl" and section == "通知公告":
        year = _digits(_node_text(node.select_one(".year")))
        month = _digits(_node_text(node.select_one(".month")))
        day = _digits(_node_text(node.select_one(".day span, .day")))
        if year and month and day:
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    # Keep the date tied to the source template's date element. Searching the
    # whole card first can silently pick an older date mentioned in a summary.
    selectors = {
        "gwt": ".width06",
        "ai": "dl dd, .time-more",
        "nmne": "span",
        "sgim": ".date, span",
        "utl": ".day-time",
        "hsee": "h6, i",
        "cep": ".date",
        "design": ".date, i, time, .time",
        "business": ":scope > span, span",
        "icoc": ".date, p",
        "future-tech": "time, .time",
        "sfl": "span",
        "music": ".info span, span",
    }
    selector = selectors.get(source_slug)
    if selector:
        for date_node in node.select(selector):
            value = extract_date(_node_text(date_node))
            if value:
                return value
    return extract_date(node.get_text(" ", strip=True))


def _extract_list_title(anchor: Tag, *, source_slug: str) -> str:
    title = str(anchor.get("title") or "").strip()
    if title:
        return title
    selectors = {
        "icoc": ".b_t, h3",
        "sfl": "p[title], p",
        "sgim": ".title",
        "utl": "h4, h3",
        "hsee": "h4, h3",
    }
    selector = selectors.get(source_slug, "h1, h2, h3, h4, h5, p[title], .title, .name, .b_t")
    title_node = anchor.select_one(selector)
    if isinstance(title_node, Tag):
        return str(title_node.get("title") or "").strip() or title_node.get_text(" ", strip=True)
    return anchor.get_text(" ", strip=True)


def _node_text(node: Tag | None) -> str:
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else ""


def _digits(value: str) -> str:
    match = re.search(r"\d+", str(value or ""))
    return match.group(0) if match else ""


__all__ = ["clean_title", "extract_date", "parse_campus_list"]
