from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import html
import logging
import re
import time
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

from services.network_policy import direct_requests_session
from bs4 import BeautifulSoup, Tag
from markdown_it import MarkdownIt
from services.paddle_ocr import OcrImageResult, recognize_document_bytes
from services.published_at import extract_published_at


logger = logging.getLogger(__name__)
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_DATE_RE = re.compile(r"(?<!\d)(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?(?!\d)")
_ENGLISH_DATE_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2}),\s*(20\d{2})\b",
    re.IGNORECASE,
)
_ARTICLE_URL_HINT_RE = re.compile(r"/(?:info|content|article|show)/|[?&](?:id|contentid)=", re.IGNORECASE)
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
_PROCUREMENT_SOURCE_SLUG = "sztu-procurement"
_PROCUREMENT_API_URL = "https://ztb.sztu.edu.cn/sfw_cms/e"
_PROCUREMENT_LIST_BASE_URL = "https://ztb.sztu.edu.cn/sfw_cms/e?page=cms.psms.gglist"
_PROCUREMENT_PROVIDER_API_BASE_URL = "https://provider.yuncaitong.cn/api/publish/"
_PROCUREMENT_PROVIDER_PUBLISH_BASE_URL = "https://provider.yuncaitong.cn/publish/"
_PROCUREMENT_PROVIDER_HOST = "provider.yuncaitong.cn"
_PROCUREMENT_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9]{8,80}$")
_PROCUREMENT_PUBLISH_FRAGMENT_RE = re.compile(r"(?:^|/)publish/([A-Za-z0-9]{8,80})(?:$|/)")
_CHINA_TIMEZONE = timezone(timedelta(hours=8))
_DOCUMENT_MARKDOWN_RENDERER = MarkdownIt("commonmark", {"html": True})
_DOCUMENT_MATH_BLOCK_RE = re.compile(
    r"(?P<dollar>\$\$\s*(?P<dollar_value>[\s\S]*?)\s*\$\$)|"
    r"(?P<bracket>\\\[\s*(?P<bracket_value>[\s\S]*?)\s*\\\])"
)
_DOCUMENT_MATH_INLINE_RE = re.compile(
    r"(?P<dollar>\$(?!\$)\s*(?P<dollar_value>[^\n$]{1,4000}?)\s*\$(?!\$))|"
    r"(?P<paren>\\\(\s*(?P<paren_value>[^\n]{1,4000}?)\s*\\\))"
)
_PROCUREMENT_SECTION_PARAMS: dict[str, dict[str, object]] = {
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


@dataclass(frozen=True)
class CampusSource:
    slug: str
    name: str
    base_url: str
    sections: dict[str, str]
    list_selectors: tuple[str, ...] = field(default_factory=tuple)
    include_wechat_links: bool = True


@dataclass(frozen=True)
class CampusArticle:
    title: str
    url: str
    published_at: str = ""
    section: str = ""
    source_slug: str = ""
    source_name: str = ""
    department: str = ""


def _source(
    slug: str,
    name: str,
    base_url: str,
    sections: dict[str, str],
    *selectors: str,
    include_wechat_links: bool = True,
) -> CampusSource:
    return CampusSource(
        slug=slug,
        name=name,
        base_url=base_url,
        sections={label: urljoin(base_url.rstrip("/") + "/", path) for label, path in sections.items()},
        list_selectors=tuple(selectors),
        include_wechat_links=include_wechat_links,
    )


# College URLs and template selectors are adapted from MicroFlow's built-in
# SZTU spiders. Keeping every campus source in the same data registry makes
# source maintenance independent from ingestion and article reading.
CAMPUS_SOURCES: tuple[CampusSource, ...] = (
    _source(
        "gwt", "公文通", "https://nbw.sztu.edu.cn/",
        {"公文通": "list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029"},
        "ul.news-ul li.clearfix",
    ),
    _source(
        "sztu", "深圳技术大学", "https://www.sztu.edu.cn/",
        {"校园新闻": "jdjd/xyxw.htm"},
        "div.yy-lt > ul > li",
        include_wechat_links=False,
    ),
    _source(
        "ai", "人工智能学院", "https://ai.sztu.edu.cn/",
        {"院系新闻": "xwzx/yxxw1.htm", "通知公告": "xwzx/tzgg1/qb.htm"},
        ".havePictureList_list a", ".news_list a", "ul.list-gl a", ".filterList_row[href]",
    ),
    _source(
        "nmne", "新材料与新能源学院", "https://nmne.sztu.edu.cn/",
        {
            "学院动态": "xwzx/xydt.htm", "通知公告": "xwzx/tzgg.htm",
            "讲座通知": "xwzx/jzt.htm", "学术动态": "xwzx/xsd.htm",
            "合作交流": "xwzx/hzj.htm", "实验平台": "xwzx/sypt.htm",
        },
        "li[id^='line_u9_']", "ul.list-gl li",
    ),
    _source(
        "sgim", "中德智能制造学院", "https://sgim.sztu.edu.cn/",
        {
            "学院新闻": "xyxw.htm",
            "通知公告": "list2022.jsp?urltype=tree.TreeTempUrl&wbtreeid=1045",
        },
        ".content-list .item", "ul.list-gl li", "ul.news-list li",
    ),
    _source(
        "utl", "城市交通与物流学院", "https://utl.sztu.edu.cn/",
        {"学院动态": "xwzx/xydt.htm", "通知公告": "xwzx/tzgg.htm"},
        "div.new_center_item", "div.new_item",
    ),
    _source(
        "hsee", "健康与环境工程学院", "https://hsee.sztu.edu.cn/",
        {"学院动态": "xydt.htm", "通知公告": "tzgg.htm"},
        ".n_tulist ul li", ".n_list ul li.cleafix", "li.cleafix",
    ),
    _source(
        "cep", "工程物理学院", "https://cep.sztu.edu.cn/",
        {"新闻动态": "tzgg1/xwdt.htm", "通知公告": "tzgg1/tzg.htm"},
        ".main_list li",
    ),
    _source(
        "cop", "药学院", "https://cop.sztu.edu.cn/",
        {
            "学院新闻": "index/yyyw.htm",
            "党群通知": "index/tzgg/dq.htm",
            "教学通知": "index/tzgg/jx.htm",
            "学工通知": "index/tzgg/xg.htm",
            "科研通知": "index/tzgg/ky.htm",
            "行政通知": "index/tzgg/xz.htm",
            "竞赛通知": "index/tzgg/js.htm",
            "招生就业": "index/tzgg/zsjy.htm",
        },
        ".article-card[onclick]", ".no-pic-article-item[onclick]",
    ),
    _source(
        "design", "创意设计学院", "https://design.sztu.edu.cn/",
        {
            "学院焦点": "xydt/xyjd.htm", "院系新闻": "xydt/yxxw.htm",
            "通知公告": "xydt/tzgg.htm", "党团工作": "xydt/dtgz.htm",
            "社会服务": "xydt/shfw.htm", "校园生活": "xydt/xysh.htm",
        },
        "li.news-item", "a.notice-item",
    ),
    _source(
        "business", "商学院", "https://bs.sztu.edu.cn/",
        {
            "新闻动态": "index/xwdt.htm", "通知公告": "index/tzgg.htm",
            "学术动态": "index/xsdt.htm", "校园生活": "index/xysh.htm",
        },
        "ul.list-gl > li", "ul.news-list > li", ".list-box .list ul > li",
    ),
    _source(
        "icoc", "集成电路与光电芯片学院", "https://icoc.sztu.edu.cn/",
        {"通知公告": "xwzx/tzgg.htm", "学术成果": "kxyj/xscg.htm", "学院新闻": "xwzx/xyxw.htm"},
        "ul.list-gl > li", "ul.news-list > li", "ul.list_pic > li", ".nopicturelist_main > ul > li",
        ".havepicturelist1 > ul > li",
    ),
    _source(
        "future-tech", "未来技术学院", "https://futuretechnologyschool.sztu.edu.cn/",
        {
            "新闻中心": "xw_hd/xwzx.htm", "教务通知": "xw_hd/tzgg1/jw.htm",
            "科研通知": "xw_hd/tzgg1/ky.htm", "学工通知": "xw_hd/tzgg1/xg.htm",
            "校园通知": "xw_hd/tzgg1/xy.htm", "行政通知": "xw_hd/tzgg1/xz.htm",
        },
        "ul.hireBox > li", "ul.listBox > li",
    ),
    _source(
        "sfl", "外国语学院", "https://sfl.sztu.edu.cn/",
        {"通知公告": "tzgg.htm", "学院新闻": "xyxw.htm"},
        "ul.news_fly > li", "ul.picture_fly > li",
    ),
    _source(
        "music", "音乐学院", "https://musicyyds.sztu.edu.cn/",
        {"封面新闻": "zxdt/fmxw.htm", "学生事务": "zxdt/xssw.htm", "教研活动": "zxdt/jyhd.htm"},
        "ul.picture_fly li", ".list ul li", ".news_list ul li", ".list-box ul li", "ul.list-gl li",
    ),
    _source(
        _PROCUREMENT_SOURCE_SLUG, "采购与招投标管理中心", "https://ztb.sztu.edu.cn/sfw_cms/",
        {
            "采购公告": "e?page=cms.psms.gglist&typeDetail=XQ",
            "成交公告": "e?page=cms.psms.gglist&typeDetail=GG",
            "采购意向": "e?page=cms.psms.gglist&typeDetail=YX",
            "合同公示": "e?page=cms.psms.gglist&typeDetail=HT",
        },
        include_wechat_links=False,
    ),
)

_SOURCE_BY_SLUG = {source.slug: source for source in CAMPUS_SOURCES}
_ALLOWED_HOSTS = {urlparse(source.base_url).hostname or "" for source in CAMPUS_SOURCES}


def get_campus_source(slug: str) -> CampusSource:
    try:
        return _SOURCE_BY_SLUG[slug]
    except KeyError as exc:
        raise LookupError(f"未知校园来源: {slug}") from exc


def is_campus_article_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").lower()
    return _is_allowed_campus_host(host)


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


def _procurement_record_to_article(
    record: dict[str, object],
    *,
    source: CampusSource,
    section: str,
) -> CampusArticle | None:
    record_id = str(record.get("id") or "").strip()
    title = _clean_title(str(record.get("subject") or ""))
    if not record_id or len(title) < 4:
        return None
    published_at = _extract_date(str(record.get("beginTime") or record.get("syncTime") or record.get("pdate") or ""))
    keyword = str(record.get("tenderNo") or title).strip()
    detail_url = _procurement_detail_url(
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


def _procurement_detail_url(
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


def parse_campus_list(html: str, *, source: CampusSource, section: str) -> list[CampusArticle]:
    soup = BeautifulSoup(html or "", "html.parser")
    nodes = list(_candidate_nodes(soup, source.list_selectors))
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
    source = _source_for_url(response.url) or _source_for_url(url)
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
    """Return inline CMS content even when it is an HTML fragment.

    The procurement API usually supplies a page container, but correction
    notices also arrive as bare ``h2/p/table`` siblings.  Looking only for a
    ``div`` or ``body`` used to discard those valid notices and incorrectly
    send them to the provider/PDF fallback.  Wrap fragment siblings in a
    neutral section so they share the normal sanitation, attachment and table
    handling path.
    """
    raw_html = str(content_html or "").strip()
    if not raw_html:
        return None
    soup = BeautifulSoup(raw_html, "html.parser")
    content = _first_node(soup, (*_ARTICLE_CONTENT_SELECTORS, "body", "div"))
    if content is not None:
        return content
    fragment = soup.new_tag("section", attrs={"class": "procurement-cms-content"})
    for node in list(soup.contents):
        fragment.append(node.extract())
    return fragment if fragment.contents else None


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


def _procurement_publish_id(url: str, record: dict[str, object]) -> str:
    candidate = str(record.get("syncId") or "").strip()
    if not candidate:
        candidate = _procurement_publish_id_from_fragment(urlparse(url).fragment)
    return candidate if _PROCUREMENT_PROVIDER_ID_RE.fullmatch(candidate) else ""


def _procurement_publish_id_from_fragment(fragment: str) -> str:
    match = _PROCUREMENT_PUBLISH_FRAGMENT_RE.search(str(fragment or "").lstrip("#"))
    return match.group(1) if match else ""


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


def _procurement_provider_document_url(detail: dict[str, object], publish_id: str) -> str:
    created_at = _provider_datetime(detail.get("createTime"))
    if not created_at:
        return ""
    try:
        timestamp = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    content_type = str(detail.get("contentType") or "").upper()
    filename = "content.pdf" if content_type == "PDF" else "content.html" if content_type == "HTML" else ""
    if not filename:
        return ""
    return f"{_PROCUREMENT_PROVIDER_PUBLISH_BASE_URL}{timestamp:%Y/%m/%d}/{publish_id}/{filename}"


def _provider_datetime(value: object) -> str:
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return ""
    if milliseconds <= 0:
        return ""
    return datetime.fromtimestamp(milliseconds / 1000, _CHINA_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


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


def _procurement_pdf_unavailable_text(ocr: OcrImageResult) -> str:
    if ocr.status == "not_configured":
        return "公告正文以 PDF 形式发布；尚未配置 PaddleOCR，已保留原 PDF 附件。"
    if ocr.status == "empty":
        return "公告正文以 PDF 形式发布；PaddleOCR 未识别出可用文字，可能为扫描件，已保留原 PDF 附件。"
    return "公告正文以 PDF 形式发布；PaddleOCR 识别失败，已保留原 PDF 附件。"


def _procurement_document_ocr_metadata(ocr: OcrImageResult) -> dict[str, object]:
    return {
        "attempted": ocr.status != "not_configured",
        "status": ocr.status,
        "cloud_submitted": ocr.cloud_submitted,
        "error": ocr.error,
    }


def render_document_markdown_html(text: str) -> str:
    """Render PaddleOCR document Markdown for the existing article reader.

    PaddleOCR intentionally returns Markdown for document OCR: headings and
    lists retain their document structure, while complex tables are emitted as
    embedded HTML.  Treating every line as escaped text made both forms appear
    literally in the reader.  The article preview normalizer remains the
    security boundary for this generated fragment.
    """
    prepared = _replace_document_math_tokens(str(text or "").strip())
    rendered = _DOCUMENT_MARKDOWN_RENDERER.render(prepared)
    rendered = _promote_document_table_headers(rendered)
    return "<article class=\"procurement-pdf-content\">" + rendered + "</article>"


def _replace_document_math_tokens(text: str) -> str:
    """Mark constrained LaTeX tokens for the reader's deterministic renderer.

    OCR models commonly emit spaces just inside ``$`` delimiters.  CommonMark
    does not understand LaTeX, so retain the original document semantics in a
    safe data attribute instead of treating it as literal prose.  The iframe
    renderer later turns only these marked values into MathML with KaTeX.
    """
    def replacement(match: re.Match[str], *, display: bool) -> str:
        value = next((match.group(name) for name in ("dollar_value", "bracket_value", "paren_value") if match.groupdict().get(name) is not None), "")
        expression = str(value or "").strip()
        if not _looks_like_document_math(expression):
            return match.group(0)
        encoded = html.escape(expression, quote=True)
        fallback = html.escape(expression)
        return (
            f'<span class="article-math" data-latex="{encoded}" '
            f'data-display="{"block" if display else "inline"}">{fallback}</span>'
        )

    text = _DOCUMENT_MATH_BLOCK_RE.sub(lambda match: replacement(match, display=True), text)
    return _DOCUMENT_MATH_INLINE_RE.sub(lambda match: replacement(match, display=False), text)


def _looks_like_document_math(expression: str) -> bool:
    if not expression or len(expression) > 4000 or "\x00" in expression:
        return False
    # Do not mistake currency fragments for math.  OCR LaTeX normally carries
    # a command, braces, or an explicit mathematical operator/subscript.
    return bool(re.search(r"\\[A-Za-z]+|[{}_^]|(?:<=|>=|≤|≥|≈|≠|=)", expression))


def _text_to_article_html(text: str) -> str:
    """Compatibility alias for existing procurement PDF callers."""
    return render_document_markdown_html(text)


_DOCUMENT_TABLE_HEADER_HINT_RE = re.compile(
    r"(?:序号|项目|名称|型号|规格|数量|单位|品牌|预算|金额|日期|时间|联系人|地址|内容|要求|类别|标的|备注|姓名|学院|结果)"
)


def _promote_document_table_headers(fragment: str) -> str:
    """Give OCR document tables semantic headers without losing merged cells."""
    soup = BeautifulSoup(fragment, "html.parser")
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_rows = [rows[0]]
        first_cells = rows[0].find_all(["td", "th"], recursive=False)
        if any(str(cell.get("colspan") or "1") not in {"", "1"} for cell in first_cells) and len(rows) > 1:
            header_rows.append(rows[1])
        for row in header_rows:
            cells = row.find_all(["td", "th"], recursive=False)
            if not _looks_like_document_header_row(cells):
                continue
            for cell in cells:
                if cell.name == "td":
                    cell.name = "th"
                if not cell.get("scope"):
                    cell["scope"] = "colgroup" if str(cell.get("colspan") or "1") not in {"", "1"} else "col"
    return "".join(str(node) for node in soup.contents)


def _looks_like_document_header_row(cells: list[Tag]) -> bool:
    if len(cells) < 2 or any(not cell.get_text(" ", strip=True) for cell in cells):
        return False
    labels = [cell.get_text(" ", strip=True) for cell in cells]
    if any(len(label) > 32 for label in labels):
        return False
    hits = sum(bool(_DOCUMENT_TABLE_HEADER_HINT_RE.search(label)) for label in labels)
    return hits >= max(1, (len(labels) + 1) // 2)


def _procurement_fallback_article(
    url: str,
    params: dict[str, str],
    *,
    record: dict[str, object] | None = None,
) -> dict[str, object]:
    source = get_campus_source(_PROCUREMENT_SOURCE_SLUG)
    title = _clean_title(str((record or {}).get("subject") or params.get("keyword") or "采购公告"))
    published_at = _extract_date(str((record or {}).get("beginTime") or (record or {}).get("syncTime") or ""))
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


def _absolutize_content_urls(content: Tag, base_url: str) -> None:
    for image in content.find_all("img"):
        src = str(image.get("data-src") or image.get("data-original") or image.get("src") or "").strip()
        if src:
            image["src"] = urljoin(base_url, src)
            image.attrs.pop("data-src", None)
            image.attrs.pop("data-original", None)
    for anchor in content.find_all("a", href=True):
        anchor["href"] = urljoin(base_url, str(anchor.get("href") or ""))


def _dedupe_attachments(value: list[dict[str, str]]) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for attachment in value:
        url = str(attachment.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        attachments.append(attachment)
    return attachments


def _article_attachment_scope(content: Tag) -> Tag:
    """Keep attachment discovery inside the article wrapper when possible."""
    form = content.find_parent("form", attrs={"name": "_newscontent_fromname"})
    if isinstance(form, Tag):
        return form

    parent = content.parent
    if isinstance(parent, Tag):
        grandparent = parent.parent
        if isinstance(grandparent, Tag):
            return grandparent
        return parent
    return content


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


def _attachment_name_from_url(url: str) -> str:
    path_name = urlparse(url).path.rsplit("/", 1)[-1]
    return path_name if "." in path_name else "查看附件"


def _candidate_nodes(soup: BeautifulSoup, selectors: Iterable[str]) -> Iterable[Tag]:
    seen: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            if not isinstance(node, Tag) or id(node) in seen:
                continue
            seen.add(id(node))
            yield node


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
    if not _is_allowed_campus_host(host) and not is_wechat_link:
        return None
    if is_wechat_link and not source.include_wechat_links:
        return None
    title = _extract_list_title(anchor, source_slug=source.slug)
    if not title:
        title = anchor.get_text(" ", strip=True)
    title = _clean_title(title)
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
    title = _clean_title(title_node.get_text(" ", strip=True) if title_node else "")
    if not title:
        image = node.find("img", alt=True)
        title = _clean_title(str(image.get("alt") or "")) if isinstance(image, Tag) else ""
    date_node = node.select_one(".image-date, .article-item-date")
    published_at = _extract_date(_node_text(date_node))
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
            value = _extract_date(_node_text(date_node))
            if value:
                return value
    return _extract_date(node.get_text(" ", strip=True))


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
    selector = selectors.get(
        source_slug,
        "h1, h2, h3, h4, h5, p[title], .title, .name, .b_t",
    )
    title_node = anchor.select_one(selector)
    if isinstance(title_node, Tag):
        return str(title_node.get("title") or "").strip() or title_node.get_text(" ", strip=True)
    return anchor.get_text(" ", strip=True)


def _node_text(node: Tag | None) -> str:
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else ""


def _digits(value: str) -> str:
    match = re.search(r"\d+", str(value or ""))
    return match.group(0) if match else ""


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


def _extract_date(text: str) -> str:
    return extract_published_at(text)


def _clean_title(value: str) -> str:
    title = " ".join(str(value or "").split())
    title = _DATE_RE.sub("", title)
    title = _ENGLISH_DATE_RE.sub("", title)
    return re.sub(r"^\d+[.、\s]+", "", title).strip(" -|·")


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


def _source_for_url(url: str) -> CampusSource | None:
    host = (urlparse(url).hostname or "").lower()
    return next((source for source in CAMPUS_SOURCES if urlparse(source.base_url).hostname == host), None)


def campus_source_for_url(url: str) -> CampusSource | None:
    return _source_for_url(url)


def _is_allowed_campus_host(host: str) -> bool:
    normalized = str(host or "").lower().rstrip(".")
    return normalized in _ALLOWED_HOSTS or (
        normalized.startswith("www.") and normalized[4:] in _ALLOWED_HOSTS
    )


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
