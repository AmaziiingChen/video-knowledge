from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html import unescape
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup
try:
    from curl_cffi.requests import RequestsError
except ImportError:  # Keep service startup available in partial dev environments.
    class RequestsError(Exception):
        pass
from services.cache import cache_dir_for_url
from services.paddle_ocr import OcrImageResult, is_paddle_ocr_configured, recognize_wechat_images
from services.paddle_ocr_settings import paddle_ocr_model
from services.wechat_browser import WECHAT_BROWSER_HEADERS, fetch_wechat_page
from services.wechat_content_filters import apply_filters
from services.campus_sources import fetch_campus_article
from services.published_at import extract_published_at
from services.public_url import get_public_http_response


WECHAT_HEADERS = WECHAT_BROWSER_HEADERS


@dataclass(frozen=True)
class ArticleFetchResult:
    url: str
    platform: str
    title: str
    body_text: str
    body_html: str = ""
    author: str = ""
    published_at: str = ""
    images: list[str] = field(default_factory=list)
    image_ocr: dict[str, object] = field(default_factory=dict)
    document_ocr: dict[str, object] = field(default_factory=dict)
    document_markdown: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)


def fetch_article(
    url: str,
    platform: str,
    *,
    content_item_id: str | None = None,
    include_image_ocr: bool = True,
) -> ArticleFetchResult:
    if platform == "wechat":
        kwargs: dict[str, object] = {}
        if content_item_id:
            kwargs["content_item_id"] = content_item_id
        if not include_image_ocr:
            kwargs["include_image_ocr"] = False
        return fetch_wechat_article(url, **kwargs)
    if platform == "campus":
        payload = fetch_campus_article(url, content_item_id=content_item_id) if content_item_id else fetch_campus_article(url)
        redirect_url = str(payload.get("redirect_url") or "").strip()
        if redirect_url:
            kwargs = {}
            if content_item_id:
                kwargs["content_item_id"] = content_item_id
            if not include_image_ocr:
                kwargs["include_image_ocr"] = False
            return fetch_wechat_article(redirect_url, **kwargs)
        content = BeautifulSoup(str(payload.get("body_html") or ""), "html.parser")
        images, image_nodes, hard_filter_counts = _article_images(content)
        image_ocr = _append_image_ocr(
            content,
            image_nodes,
            article_url=str(payload.get("url") or url),
            hard_filter_counts=hard_filter_counts,
            content_item_id=content_item_id,
        ) if include_image_ocr else _pending_image_ocr_metadata(image_nodes, hard_filter_counts)
        return ArticleFetchResult(
            url=str(payload["url"]),
            platform="campus",
            title=str(payload["title"]),
            body_text=_clean_article_text(content.get_text("\n", strip=True)),
            body_html=str(content),
            author=str(payload.get("author") or ""),
            published_at=str(payload.get("published_at") or ""),
            images=images,
            image_ocr=image_ocr,
            document_ocr=dict(payload.get("document_ocr") or {}),
            document_markdown=str(payload.get("document_markdown") or ""),
            attachments=list(payload.get("attachments") or []),
        )
    if platform == "rss":
        return fetch_rss_article(
            url,
            content_item_id=content_item_id,
            include_image_ocr=include_image_ocr,
        )
    raise ValueError(f"不支持的文章平台: {platform}")


_RSS_ARTICLE_HEADERS = {
    "User-Agent": "KnowledgeHub RSS Reader/1.0 (+local)",
    "Accept": "text/html,application/xhtml+xml",
}
_RSS_ARTICLE_MAX_BYTES = 8 * 1024 * 1024
_RSS_ARTICLE_MAX_REDIRECTS = 5


def fetch_rss_article(
    url: str,
    *,
    content_item_id: str | None = None,
    include_image_ocr: bool = True,
) -> ArticleFetchResult:
    """Fetch and extract the linked page for a summary-only RSS entry."""
    final_url, html = _fetch_rss_article_html(url)
    soup = BeautifulSoup(html, "lxml")
    title = _text(soup.select_one("h1")) or _meta(soup, "og:title") or _text(soup.title)
    author = _meta(soup, "author")
    published_at = extract_published_at(str(soup))
    content = _rss_article_content(soup)
    for tag in content.find_all(["script", "style", "noscript", "iframe", "video", "audio", "form"]):
        tag.decompose()
    images, image_nodes, hard_filter_counts = _article_images(content)
    image_ocr = _append_image_ocr(
        content,
        image_nodes,
        article_url=final_url,
        hard_filter_counts=hard_filter_counts,
        content_item_id=content_item_id,
    ) if include_image_ocr else _pending_image_ocr_metadata(image_nodes, hard_filter_counts)
    body_html = str(content)
    body_text = _clean_article_text(content.get_text("\n", strip=True))
    if not body_text:
        raise ValueError("RSS 原文页面没有可提取的正文")
    return ArticleFetchResult(
        url=final_url,
        platform="rss",
        title=title or "未命名 RSS 文章",
        body_text=body_text,
        body_html=body_html,
        author=author,
        published_at=published_at,
        images=images,
        image_ocr=image_ocr,
    )


def _fetch_rss_article_html(url: str) -> tuple[str, str]:
    current_url = str(url or "").strip()
    try:
        response, final_url = get_public_http_response(
            current_url,
            invalid_message="RSS 原文链接无效",
            blocked_message="RSS 原文链接不可访问",
            redirect_invalid_message="RSS 原文页面重定向地址无效",
            redirect_limit_message="RSS 原文重定向次数过多",
            max_redirects=_RSS_ARTICLE_MAX_REDIRECTS,
            headers=_RSS_ARTICLE_HEADERS,
            timeout=30.0,
        )
        try:
            response.raise_for_status()
            content_type = str(response.headers.get("content-type") or "").lower()
            if content_type and "html" not in content_type and "xhtml" not in content_type:
                raise ValueError("RSS 原文链接未返回网页内容")
            try:
                content_length = int(response.headers.get("content-length") or 0)
            except ValueError:
                content_length = 0
            if content_length > _RSS_ARTICLE_MAX_BYTES:
                raise ValueError("RSS 原文页面过大，已跳过抓取")
            content = response.content
            if len(content) > _RSS_ARTICLE_MAX_BYTES:
                raise ValueError("RSS 原文页面过大，已跳过抓取")
            return final_url, response.text
        finally:
            response.close()
    except ValueError:
        raise
    except RequestsError as exc:
        raise ValueError(f"RSS 原文抓取失败：{exc}") from exc
    raise ValueError("RSS 原文重定向次数过多")


def _rss_article_content(soup: BeautifulSoup):
    selectors = (
        "article",
        "main article",
        "main",
        "[role='main']",
        ".entry-content",
        ".post-content",
        ".article-content",
        ".article-body",
        ".post-body",
    )
    for selector in selectors:
        content = soup.select_one(selector)
        if content and content.get_text(" ", strip=True):
            return content
    for selector in ("nav", "header", "footer", "aside"):
        for node in soup.select(selector):
            node.decompose()
    return soup.body or soup


def fetch_wechat_article(
    url: str,
    *,
    content_item_id: str | None = None,
    include_image_ocr: bool = True,
) -> ArticleFetchResult:
    """Fetch an article in-process; no local HTTP service or Docker is needed."""
    return _fetch_wechat_article_direct(
        url,
        content_item_id=content_item_id,
        include_image_ocr=include_image_ocr,
    )


def _fetch_wechat_article_direct(
    url: str,
    *,
    content_item_id: str | None = None,
    include_image_ocr: bool = True,
) -> ArticleFetchResult:
    try:
        response = fetch_wechat_page(url, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code:
            raise ValueError(_wechat_http_error_message(status_code)) from exc
        if "timeout" in str(exc).lower() or "timed out" in str(exc).lower():
            raise ValueError("微信公众号正文抓取超时，请稍后重试，或确认链接能在浏览器中打开") from exc
        raise ValueError("微信公众号正文抓取失败，请检查网络连接或稍后重试") from exc
    return parse_wechat_article_html(
        url,
        response.text or "",
        content_item_id=content_item_id,
        include_image_ocr=include_image_ocr,
    )


def parse_wechat_article_html(
    url: str,
    page_html: str,
    *,
    content_item_id: str | None = None,
    include_image_ocr: bool = True,
) -> ArticleFetchResult:
    """Extract a WeChat article from an already-downloaded public page."""
    _raise_for_wechat_intercept(page_html)
    soup = BeautifulSoup(page_html, "lxml")

    title = _text(soup.select_one("h1.rich_media_title")) or _meta(soup, "og:title")
    author = _text(soup.select_one("#js_name")) or _meta(soup, "author")
    published_at = _wechat_publish_time(page_html, soup)

    content = soup.select_one("div.rich_media_content#js_content") or soup.select_one("#js_content")
    if not content:
        content, share_title, share_author = _wechat_share_page_content(page_html)
        title = title or share_title
        author = author or share_author
    if not content:
        raise ValueError("未找到微信公众号正文。可能是链接失效、文章被删除，或微信页面要求在客户端内打开")

    for tag in content.find_all(["script", "style", "noscript", "iframe", "video"]):
        tag.decompose()
    apply_filters(content, url)

    images, image_nodes, hard_filter_counts = _article_images(content)
    image_ocr = _append_image_ocr(
        content,
        image_nodes,
        article_url=url,
        hard_filter_counts=hard_filter_counts,
        content_item_id=content_item_id,
    ) if include_image_ocr else _pending_image_ocr_metadata(image_nodes, hard_filter_counts)

    body_html = str(content)
    body_text = _clean_article_text(content.get_text("\n", strip=True))
    if not body_text:
        if images:
            # Keep image-only articles in the capture/OCR pipeline.  Without a
            # small local placeholder this branch used to raise before the
            # deferred OCR worker could persist its annotations, leaving
            # graphic notices permanently unavailable.
            placeholder = content.new_tag("p")
            placeholder["data-wechat-image-only-placeholder"] = "true"
            placeholder.string = f"图文内容，共 {len(images)} 张图片。图片文字正在后台解析。"
            content.insert(0, placeholder)
            body_html = str(content)
            body_text = _clean_article_text(content.get_text("\n", strip=True))
        else:
            raise ValueError("微信公众号正文为空，可能是纯图片文章、链接被拦截，或正文需要登录后查看")

    return ArticleFetchResult(
        url=url,
        platform="wechat",
        title=title or "未命名公众号文章",
        body_text=body_text,
        body_html=body_html,
        author=author,
        published_at=published_at,
        images=images,
        image_ocr=image_ocr,
    )


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _meta(soup: BeautifulSoup, key: str) -> str:
    node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    return str(node.get("content") or "").strip() if node else ""


def _wechat_http_error_message(status_code: int | None) -> str:
    if status_code == 403:
        return "微信公众号页面拒绝访问，可能触发了微信风控；请稍后重试或换一个可直接打开的链接"
    if status_code == 404:
        return "微信公众号文章不存在或已被删除"
    if status_code and status_code >= 500:
        return "微信服务器暂时不可用，请稍后重试"
    if status_code:
        return f"微信公众号页面访问失败（HTTP {status_code}）"
    return "微信公众号页面访问失败"


def _raise_for_wechat_intercept(html: str) -> None:
    text = re.sub(r"\s+", "", html or "")
    checks = [
        ("该内容已被发布者删除", "微信公众号文章已被发布者删除"),
        ("此内容因违规无法查看", "微信公众号文章因平台限制无法查看"),
        ("访问过于频繁", "访问微信公众号过于频繁，触发了临时限制，请稍后重试"),
        ("请在微信客户端打开", "该公众号文章要求在微信客户端打开，当前无法直接抓取正文"),
        ("环境异常", "微信页面提示访问环境异常，当前无法抓取正文"),
        ("请输入验证码", "微信页面要求验证，当前无法自动抓取正文"),
    ]
    for marker, message in checks:
        if marker in text:
            raise ValueError(message)


def _wechat_publish_time(html: str, soup: BeautifulSoup) -> str:
    visible = extract_published_at(_text(soup.select_one("em#publish_time")))
    if visible:
        return visible

    publish_match = re.search(r'var\s+publish_time\s*=\s*"([^"]+)"', html)
    if publish_match:
        raw_value = publish_match.group(1).strip()
        return extract_published_at(raw_value) or raw_value

    ct_match = re.search(r'(?:var\s+|window\.)ct\s*=\s*["\'](\d+)["\']', html)
    if ct_match:
        try:
            china_standard_time = timezone(timedelta(hours=8))
            return datetime.fromtimestamp(int(ct_match.group(1)), china_standard_time).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return ""


def _wechat_share_page_content(html: str):
    """Build a local body for WeChat text- and image-share pages.

    Some mobile share links do not expose the ordinary ``#js_content`` DOM.
    Their content instead lives in page JavaScript as either an image list or
    ``text_page_info.content``.  The generated section must belong to its
    BeautifulSoup document: later OCR enrichment inserts annotations through
    ``content.new_tag()``, which otherwise raises for a detached Tag.
    """
    image_list = _extract_js_array_assignment(html, "window.picture_page_info_list")
    if not image_list:
        image_list = _extract_js_array_assignment(html, "picture_page_info_list")
    images = _js_object_string_values(image_list, "cdn_url") if image_list else []
    text_content = _first_js_string(
        html,
        r"text_page_info\s*(?:=|:)\s*\{\s*content\s*:\s*",
    )
    if not images and not text_content:
        return None, "", ""
    title = _first_js_string(html, r"window\.msg_title\s*=\s*window\.title\s*=\s*")
    if not _is_usable_wechat_share_title(title):
        title = ""
    author = _first_js_string(html, r"nick_name\s*:\s*")
    caption = (
        _first_js_string(image_list, r"content_noencode\s*:\s*")
        or _first_js_string(image_list, r"desc\s*:\s*")
    ) if image_list else ""

    document = BeautifulSoup("", "html.parser")
    content = document.new_tag("section", id="js_content")
    document.append(content)
    if images:
        content["data-wechat-picture-page"] = "true"
        paragraph = document.new_tag("p")
        if caption:
            paragraph.string = caption
        else:
            paragraph["data-wechat-image-only-placeholder"] = "true"
            paragraph.string = f"图文内容，共 {len(images)} 张图片。图片文字会在后台 OCR 后补齐。"
        content.append(paragraph)
    else:
        content["data-wechat-text-page"] = "true"
        for line in text_content.splitlines():
            paragraph_text = line.strip()
            if not paragraph_text:
                continue
            paragraph = document.new_tag("p")
            paragraph.string = paragraph_text
            content.append(paragraph)
    for image_url in images:
        image = document.new_tag("img")
        image["data-src"] = image_url
        content.append(image)
    return content, title, author


def _wechat_picture_page_content(html: str):
    """Backward-compatible alias for callers using the original helper."""
    return _wechat_share_page_content(html)


def _is_usable_wechat_share_title(value: str) -> bool:
    """Reject share-page values that are actually the full text body."""
    normalized = str(value or "").strip()
    return bool(normalized) and "\n" not in normalized and len(normalized) <= 200


def _extract_js_array_assignment(source: str, name: str) -> str:
    """Extract a JavaScript array literal without evaluating remote page code."""
    match = re.search(rf"{re.escape(name)}\s*=\s*\[", source)
    if not match:
        return ""
    start = source.find("[", match.start())
    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return ""


def _js_object_string_values(source: str, key: str) -> list[str]:
    pattern = re.compile(rf"\b{re.escape(key)}\s*:\s*(['\"])((?:\\.|(?!\1).)*)\1", re.DOTALL)
    values = [_decode_js_string(match.group(2)) for match in pattern.finditer(source)]
    return list(dict.fromkeys(value for value in values if value.startswith(("http://", "https://"))))


def _first_js_string(source: str, prefix_pattern: str) -> str:
    pattern = re.compile(rf"{prefix_pattern}(['\"])((?:\\.|(?!\1).)*)\1", re.DOTALL)
    match = pattern.search(source)
    return _decode_js_string(match.group(2)) if match else ""


def _decode_js_string(value: str) -> str:
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "v": "\v",
        "0": "\0",
        "\\": "\\",
        "'": "'",
        '"': '"',
        "/": "/",
    }

    def replace(match: re.Match[str]) -> str:
        escaped = match.group(1)
        if escaped.startswith("x") and len(escaped) == 3:
            return chr(int(escaped[1:], 16))
        if escaped.startswith("u") and len(escaped) == 5:
            return chr(int(escaped[1:], 16))
        return escapes.get(escaped, escaped)

    return unescape(re.sub(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", replace, value)).strip()


def _clean_article_text(text: str) -> str:
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    cleaned: list[str] = []
    previous = ""
    for line in lines:
        if not line or line == previous:
            continue
        cleaned.append(line)
        previous = line
    return "\n".join(cleaned).strip()


def _article_images(content) -> tuple[list[str], list[tuple[object, str]], dict[str, int]]:
    """Return images in DOM order, excluding video posters and decorative art."""
    unique_urls: list[str] = []
    nodes: list[tuple[object, str]] = []
    filter_counts: dict[str, int] = {}
    for image in content.find_all("img"):
        filter_reason = _image_filter_reason(image)
        if filter_reason:
            filter_counts[filter_reason] = filter_counts.get(filter_reason, 0) + 1
            continue
        src = str(image.get("data-src") or image.get("src") or "").strip()
        if not src.startswith(("http://", "https://")):
            continue
        nodes.append((image, src))
        if src not in unique_urls:
            unique_urls.append(src)
    return unique_urls, nodes, filter_counts


def _is_meaningful_article_image(image) -> bool:
    return not bool(_image_filter_reason(image))


def _image_filter_reason(image) -> str:
    image_type = str(image.get("data-type") or image.get("type") or "").lower()
    class_name = " ".join(image.get("class") or []).lower()
    src = str(image.get("data-src") or image.get("src") or "").lower()
    if image_type == "video" or "video" in class_name:
        return "video"
    if image_type == "gif" or "wx_fmt=gif" in src or src.endswith(".gif"):
        return "gif"
    if any(marker in src for marker in ("wx_emoticon", "/emoji/", "emoji.")):
        return "decorative"
    if any(marker in src or marker in class_name for marker in ("qrcode", "qr_code", "qr-code")):
        return "qrcode"
    if any(marker in src or marker in class_name for marker in ("avatar", "headimg", "head_img", "logo")):
        return "avatar_or_logo"
    try:
        width = float(image.get("data-w") or image.get("width") or 0)
        ratio = float(image.get("data-ratio") or 0)
        height = width * ratio if width and ratio else 0
        if width and width < 90:
            return "decorative"
        if height and height < 90:
            return "decorative"
        if width and height and width / height >= 8:
            return "divider"
        if width and height and width <= 180 and 0.75 <= width / height <= 1.34:
            return "avatar_or_logo"
    except (TypeError, ValueError):
        pass
    return ""


def _append_image_ocr(
    content,
    image_nodes: list[tuple[object, str]],
    *,
    article_url: str,
    hard_filter_counts: dict[str, int] | None = None,
    content_item_id: str | None = None,
) -> dict[str, object]:
    configured = is_paddle_ocr_configured()
    if not image_nodes:
        return {
            "configured": configured,
            "attempted": False,
            "image_count": 0,
            "recognized_count": 0,
            "failed_count": 0,
            "hard_filter_counts": hard_filter_counts or {},
        }
    if not configured:
        return {"configured": False, "attempted": False, "image_count": len(image_nodes), "recognized_count": 0, "failed_count": 0}

    unique_urls = list(dict.fromkeys(url for _, url in image_nodes))
    kwargs = {"content_item_id": content_item_id} if content_item_id else {}
    results = recognize_wechat_images(
        unique_urls,
        article_url=article_url,
        image_cache_dir=cache_dir_for_url(article_url) / "article_images",
        **kwargs,
    )
    by_url = {result.url: result for result in results}
    recognized = 0
    failed = 0
    pending = 0
    cached_paths: set[str] = set()
    inserted_for_url: set[str] = set()
    errors: list[str] = []
    cloud_submitted_count = sum(1 for result in results if result.cloud_submitted)
    cached_ocr_count = sum(1 for result in results if result.skip_reason == "duplicate_cache")
    for position, (image, url) in enumerate(image_nodes, start=1):
        result = by_url.get(url) or OcrImageResult(url=url, status="failed")
        if result.cached_path:
            # The raw HTML keeps the local path as a marker. The preview endpoint
            # turns it into its own authenticated-safe /api/media URL at render
            # time, so a saved snapshot does not depend on WeChat's image CDN.
            image["data-local-media-path"] = result.cached_path
            cached_paths.add(result.cached_path)
        if result.status == "failed":
            failed += 1
            if result.error and result.error not in errors:
                errors.append(result.error)
        elif result.status == "pending":
            pending += 1
        if not result.text or url in inserted_for_url:
            continue
        inserted_for_url.add(url)
        recognized += 1
        annotation = content.new_tag("p")
        annotation["data-wechat-image-ocr"] = "true"
        annotation.string = f"\n[图片文字 {position}]\n{result.text}\n[/图片文字 {position}]\n"
        image.insert_after(annotation)
    return {
        "configured": True,
        "attempted": True,
        "model": paddle_ocr_model(),
        "image_count": len(image_nodes),
        "unique_image_count": len(unique_urls),
        "cached_image_count": len(cached_paths),
        "recognized_count": recognized,
        "failed_count": failed,
        "pending_count": pending,
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors[:3],
        "hard_filter_counts": hard_filter_counts or {},
        # Kept as an empty compatibility field for existing metadata readers.
        # Image content is no longer judged by device-side OCR before upload.
        "local_filter_counts": {},
        "cloud_submitted_count": cloud_submitted_count,
        "cached_ocr_count": cached_ocr_count,
    }


def enrich_cached_article_image_ocr(
    body_html: str,
    *,
    article_url: str,
    content_item_id: str | None = None,
) -> tuple[str, str, list[str], dict[str, object]]:
    """Add OCR annotations to an already-captured article snapshot.

    Keeping this separate from ``fetch_article`` lets the ingestion service
    make the readable local snapshot available immediately, then enrich the
    same HTML without downloading the article page a second time.
    """
    content = BeautifulSoup(body_html or "", "html.parser")
    # A legacy snapshot can already contain partial OCR annotations. Replacing
    # them before re-enrichment preserves the image-to-text order and avoids
    # duplicate blocks when an older local prefilter had skipped a real table.
    for annotation in content.select("[data-wechat-image-ocr]"):
        annotation.decompose()
    images, image_nodes, hard_filter_counts = _article_images(content)
    image_ocr = _append_image_ocr(
        content,
        image_nodes,
        article_url=article_url,
        hard_filter_counts=hard_filter_counts,
        content_item_id=content_item_id,
    )
    return (
        _clean_article_text(content.get_text("\n", strip=True)),
        str(content),
        images,
        image_ocr,
    )


def _pending_image_ocr_metadata(
    image_nodes: list[tuple[object, str]],
    hard_filter_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    """Describe image OCR that was deliberately deferred to the background."""
    return {
        "configured": is_paddle_ocr_configured(),
        "attempted": False,
        "pending": bool(image_nodes) and is_paddle_ocr_configured(),
        "image_count": len(image_nodes),
        "recognized_count": 0,
        "failed_count": 0,
        "hard_filter_counts": hard_filter_counts or {},
    }
