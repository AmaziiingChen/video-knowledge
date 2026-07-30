from __future__ import annotations

import re

import httpx

from services.source_context import (
    MAX_COMMENT_SAMPLE,
    MAX_STORED_COMMENTS,
    douyin_comments_from_payload,
    find_douyin_aweme,
    source_context_from_douyin_aweme,
)


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.douyin.com/",
}


def fetch_douyin_source_context(
    url_or_id: str,
    *,
    client: httpx.Client | None = None,
    comment_limit: int = MAX_COMMENT_SAMPLE,
    comment_pages: int = 1,
) -> dict[str, object]:
    comment_limit = max(1, min(int(comment_limit), MAX_STORED_COMMENTS))
    comment_pages = max(1, min(int(comment_pages), 6))
    own_client = client is None
    active_client = client or httpx.Client(
        follow_redirects=True,
        timeout=12,
        trust_env=False,
        headers=_HEADERS,
    )
    try:
        video_id = _video_id(url_or_id)
        if not video_id and str(url_or_id or "").startswith(("http://", "https://")):
            resolved = active_client.get(str(url_or_id), timeout=12)
            resolved.raise_for_status()
            video_id = _video_id(str(resolved.url)) or _video_id(resolved.text)
        if not video_id:
            raise ValueError("无法从抖音链接中提取作品 ID")
        detail_response = active_client.get(
            "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/",
            params={"item_ids": video_id},
        )
        detail_response.raise_for_status()
        aweme = find_douyin_aweme(detail_response.json(), video_id)
        if not aweme:
            return _fetch_douyin_source_context_via_browser(
                video_id,
                comment_limit=comment_limit,
                comment_pages=comment_pages,
            )
        comments = []
        comments_complete = False
        try:
            cursor = 0
            known_ids: set[str] = set()
            for _page_number in range(comment_pages):
                comment_response = active_client.get(
                    "https://www.iesdouyin.com/web/api/v2/comment/list/",
                    params={
                        "aweme_id": video_id,
                        "cursor": cursor,
                        "count": min(20, max(1, comment_limit - len(comments))),
                    },
                    timeout=5,
                )
                comment_response.raise_for_status()
                payload = comment_response.json()
                page_comments, comments_complete = douyin_comments_from_payload(payload)
                for comment in page_comments:
                    comment_id = str(comment.get("comment_id") or "")
                    if comment_id and comment_id in known_ids:
                        continue
                    comments.append(comment)
                    if comment_id:
                        known_ids.add(comment_id)
                    if len(comments) >= comment_limit:
                        break
                if comments_complete or len(comments) >= comment_limit or not isinstance(payload, dict):
                    break
                try:
                    next_cursor = int(payload.get("cursor"))
                except (TypeError, ValueError):
                    break
                if next_cursor == cursor:
                    break
                cursor = next_cursor
        except (httpx.HTTPError, ValueError):
            comments_complete = False
        return source_context_from_douyin_aweme(
            aweme,
            comments=comments,
            comments_complete=comments_complete,
        )
    finally:
        if own_client:
            active_client.close()


def _video_id(value: str) -> str:
    match = re.search(r"(?:/video/|/note/|modal_id=)?(\d{8,})", str(value or ""))
    return match.group(1) if match else ""


def _fetch_douyin_source_context_via_browser(
    video_id: str,
    *,
    comment_limit: int,
    comment_pages: int,
) -> dict[str, object]:
    """Capture signed work/comment responses without downloading the media."""
    try:
        from playwright.sync_api import sync_playwright
        from services.downloader import _load_cookies_for_playwright
        from services.network_policy import direct_browser_launch_options
        from services.runtime_components import browser_executable
    except ImportError as exc:
        raise ValueError("抖音公开作品接口不可用，且浏览器采集组件未安装") from exc

    executable = browser_executable()
    if not executable:
        raise ValueError("抖音公开作品接口不可用，且未找到浏览器采集组件")
    comments: list[dict[str, object]] = []
    known_comments: set[str] = set()
    aweme: dict[str, object] | None = None
    comments_complete = False

    def on_response(response) -> None:
        nonlocal aweme, comments_complete
        try:
            url = str(response.url)
            if "/aweme/v1/web/" in url and any(part in url for part in ("aweme/detail", "feed", "mix/aweme")):
                matched = find_douyin_aweme(response.json(), video_id)
                if matched:
                    aweme = matched
                return
            if "/aweme/v1/web/comment/list" not in url and "/web/api/v2/comment/list" not in url:
                return
            page_comments, complete = douyin_comments_from_payload(response.json())
            for comment in page_comments:
                identity = str(comment.get("comment_id") or "").strip()
                if not identity:
                    identity = f"{comment.get('author', '')}\n{comment.get('text', '')}"
                if identity in known_comments:
                    continue
                known_comments.add(identity)
                comments.append(comment)
                if len(comments) >= comment_limit:
                    break
            comments_complete = comments_complete or complete
        except Exception:
            # Other page responses remain useful even when one payload changes.
            return

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=executable,
                **direct_browser_launch_options("--disable-blink-features=AutomationControlled"),
            )
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                cookies = _load_cookies_for_playwright()
                if cookies:
                    context.add_cookies(cookies)
                page = context.new_page()
                page.on("response", on_response)
                page.goto(
                    f"https://www.douyin.com/video/{video_id}",
                    wait_until="commit",
                    timeout=20_000,
                )
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=8_000)
                except Exception:
                    pass
                # The desktop work page loads comments lazily. Small bounded
                # scrolls exercise the same visible list and its signed cursor
                # requests without fabricating private API signatures.
                for _ in range(max(2, comment_pages * 2)):
                    if aweme and (comments_complete or len(comments) >= comment_limit):
                        break
                    page.mouse.wheel(0, 1_400)
                    page.wait_for_timeout(800)
                page.wait_for_timeout(1_000)
            finally:
                browser.close()
    except Exception as exc:
        raise ValueError(f"抖音浏览器互动数据采集失败：{exc.__class__.__name__}") from exc

    if not aweme:
        raise ValueError("抖音浏览器页面未返回目标作品信息")
    return source_context_from_douyin_aweme(
        aweme,
        comments=comments[:comment_limit],
        comments_complete=comments_complete,
    )
