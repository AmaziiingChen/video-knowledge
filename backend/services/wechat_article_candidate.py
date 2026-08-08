from __future__ import annotations

import html
import logging
import re

from bs4 import BeautifulSoup

from services.article_ingest_preparation import enqueue_article_source_preparation
from services.content_source_text import cache_preloaded_wechat_article
from services.database import connect, utc_now_iso
from services.inbox import capture_link_to_inbox, process_inbox_item
from services.wechat_browser import fetch_wechat_page
from services.wechat_discovery_models import VerifiedArticle, WeChatDiscoveryError
from services.wechat_urls import (
    article_identity_from_html,
    article_identity_from_url,
    canonical_wechat_article_id,
    is_wechat_article_url,
    merge_article_identity,
    normalize_wechat_url,
)


logger = logging.getLogger(__name__)


def verify_article(url: str, *, expected_biz: str = "") -> VerifiedArticle:
    if not is_wechat_article_url(url):
        raise WeChatDiscoveryError("不是可识别的公众号文章链接")
    try:
        response = fetch_wechat_page(url, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code == 403:
            raise WeChatDiscoveryError("微信拒绝访问该文章，已停止导入此条") from exc
        if status_code == 404:
            raise WeChatDiscoveryError("文章不存在或已被删除") from exc
        raise WeChatDiscoveryError("文章页面暂时无法访问") from exc
    final_url = normalize_wechat_url(str(getattr(response, "url", "") or url))
    if not is_wechat_article_url(final_url):
        raise WeChatDiscoveryError("文章跳转到了非微信公众号页面")
    page = str(response.text or "")
    compact = re.sub(r"\s+", "", page)
    for marker, message in (
        ("访问过于频繁", "访问过于频繁，已停止导入此条"),
        ("请输入验证码", "页面要求验证码，已停止导入此条"),
        ("请在微信客户端打开", "文章要求在微信客户端打开"),
        ("该内容已被发布者删除", "文章已被发布者删除"),
        ("此内容因违规无法查看", "文章因平台限制无法查看"),
    ):
        if marker in compact:
            raise WeChatDiscoveryError(message)
    soup = BeautifulSoup(page, "lxml")
    if not (
        soup.select_one("#js_content")
        or "picture_page_info_list" in page
        or "text_page_info" in page
    ):
        raise WeChatDiscoveryError("页面中没有找到可读取的文章正文")
    final_identity = article_identity_from_url(final_url)
    input_identity = article_identity_from_url(url)
    html_identity = article_identity_from_html(page)
    observed_biz = {item.biz for item in (final_identity, input_identity, html_identity) if item.biz}
    if expected_biz and (not observed_biz or observed_biz != {expected_biz}):
        raise WeChatDiscoveryError("文章不属于目标公众号，已跳过")
    identity = merge_article_identity(html_identity, final_identity, input_identity)
    canonical_id = identity.canonical_id or canonical_wechat_article_id(final_url)
    title_node = soup.select_one("h1.rich_media_title")
    title = title_node.get_text(" ", strip=True) if title_node else ""
    if not title:
        meta = soup.find("meta", attrs={"property": "og:title"})
        title = str(meta.get("content") or "").strip() if meta else ""
    source_node = soup.select_one("#js_name")
    source_name = source_node.get_text(" ", strip=True) if source_node else ""
    published_node = soup.select_one("em#publish_time")
    published_at = published_node.get_text(" ", strip=True) if published_node else ""
    return VerifiedArticle(
        url=final_url,
        canonical_source_id=canonical_id,
        title=title or candidate_title_from_html(page) or "未命名公众号文章",
        source_name=source_name,
        biz=identity.biz,
        published_at=published_at,
        page_html=page,
    )


def candidate_title_from_html(page: str) -> str:
    match = re.search(r'window\.msg_title\s*=\s*window\.title\s*=\s*["\'](.+?)["\']', page)
    return html.unescape(match.group(1)).strip() if match else ""


def import_verified_article(
    article: VerifiedArticle,
    *,
    auto_analyze: bool,
    library_folder_id: str | None = None,
) -> tuple[str, bool]:
    with connect() as connection:
        existing = connection.execute(
            """
            SELECT id, status, source_url
            FROM content_items
            WHERE source_provider = 'wechat' AND canonical_source_id = ?
            """,
            (article.canonical_source_id,),
        ).fetchone()
    if existing:
        item_id = str(existing["id"])
        item_status = str(existing["status"])
        source_url = str(existing["source_url"] or article.url)
        duplicate = True
        created = False
    else:
        capture = capture_link_to_inbox(
            article.url,
            library_folder_id=library_folder_id,
        )
        if capture.error or capture.item is None:
            raise WeChatDiscoveryError(capture.error or "文章写入资料库失败")
        item_id = capture.item.id
        item_status = capture.item.status
        source_url = str(capture.item.source_url or article.url)
        duplicate = capture.duplicate
        created = capture.created
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            UPDATE content_items
            SET canonical_source_id = ?,
                title = CASE WHEN ? <> '' THEN ? ELSE title END,
                source_name = CASE WHEN ? <> '' THEN ? ELSE source_name END,
                published_at = COALESCE(NULLIF(?, ''), published_at),
                library_folder_id = COALESCE(?, library_folder_id),
                status = CASE WHEN ? = 0 AND status = 'inbox' THEN 'to_read' ELSE status END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                article.canonical_source_id,
                article.title,
                article.title,
                article.source_name,
                article.source_name,
                article.published_at,
                library_folder_id,
                int(auto_analyze),
                now,
                item_id,
            ),
        )
        connection.commit()
    if article.page_html:
        try:
            cache_preloaded_wechat_article(
                item_id,
                source_url,
                article.page_html,
                fallback_title=article.title,
            )
        except Exception:
            # Import remains durable even if an unusual page variant cannot be
            # converted from the verification response. The ordinary article
            # preparation worker will retry through its existing fetch path.
            logger.info("Could not reuse verified WeChat page for %s", item_id, exc_info=True)
    if auto_analyze and created and item_status == "inbox":
        process_inbox_item(item_id, use_cache=True, processing_mode="full")
    else:
        enqueue_article_source_preparation(item_id)
    return item_id, duplicate
