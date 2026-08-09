from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse

from services.creator_capture_status import (
    begin_creator_browser_capture,
    finish_creator_browser_capture,
    record_creator_list_check,
    set_creator_capture_stage,
    wait_for_creator_browser,
)
from services.creator_sync_models import CreatorSyncError
from services.network_policy import direct_browser_launch_options


CREATOR_PAGE_RESPONSE_WAIT_MS = 5_000
MAX_CREATOR_LOAD_ATTEMPTS = 3
_CREATOR_BROWSER_LOCK = Lock()


def capture_creator_browser_pages(
    *,
    source_url: str,
    response_matcher,
    payload_matcher=None,
    limit: int,
    provider: str,
    stop_at: datetime | None,
    known_item_ids: set[str] | None = None,
    should_continue: Callable[..., bool],
) -> tuple[list[dict[str, Any]], str]:
    try:
        from playwright.sync_api import sync_playwright
        from services.bilibili_auth import bilibili_playwright_cookies
        from services.downloader import _load_cookies_for_playwright, browser_executable
    except ImportError as exc:
        raise CreatorSyncError("内置浏览器组件不可用；请在设置中安装 Chromium 后重试") from exc

    executable = browser_executable()
    if not executable:
        raise CreatorSyncError("未找到内置 Chromium；请在设置 > 设备准备中安装后重试")
    pages: list[dict[str, Any]] = []
    bilibili_favorites_page_url = ""
    wait_for_creator_browser(provider)
    with _CREATOR_BROWSER_LOCK:
        begin_creator_browser_capture(provider)
        try:
            with sync_playwright() as playwright:
                set_creator_capture_stage("启动内置浏览器")
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=executable,
                    **direct_browser_launch_options("--disable-blink-features=AutomationControlled"),
                )
                try:
                    # Keep the browser's own UA and network fingerprint in
                    # sync. The previous fixed Chrome/131 UA diverged from
                    # the bundled Chromium as it was updated, which makes the
                    # request look synthetic to Bilibili's risk controls.
                    context = browser.new_context(
                        locale="zh-CN",
                        viewport={"width": 1440, "height": 1000},
                    )
                    cookies = _load_cookies_for_playwright() + bilibili_playwright_cookies()
                    if cookies:
                        context.add_cookies(cookies)
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                    # Douyin and Bilibili both use virtualized grids. A grid
                    # can prefetch a page without changing document height, so
                    # tying collection to one scroll event loses responses.
                    # Observe every matching API response for this page and
                    # use scrolling only as a nudge to request the next one.
                    def capture_response(response) -> None:
                        nonlocal bilibili_favorites_page_url
                        url_matches = response_matcher(response.url)
                        # A provider may rename a list endpoint without
                        # changing its schema. A caller can opt into a narrow
                        # payload fallback, limited to fetch/XHR traffic so
                        # document and asset responses are never inspected.
                        may_match_payload = bool(
                            payload_matcher
                            and response.request.resource_type in {"fetch", "xhr"}
                        )
                        if not url_matches and not may_match_payload:
                            return
                        try:
                            payload = response.json()
                        except Exception:
                            return
                        payload_matches = bool(
                            payload_matcher
                            and isinstance(payload, dict)
                            and payload_matcher(payload)
                        )
                        if isinstance(payload, dict) and (url_matches or payload_matches):
                            pages.append(payload)
                            if provider == "bilibili":
                                next_url = next_bilibili_favorites_page_url(response.url)
                                if next_url:
                                    bilibili_favorites_page_url = next_url

                    page.on("response", capture_response)
                    set_creator_capture_stage("读取创作者页面")
                    page.goto(source_url, wait_until="domcontentloaded", timeout=30_000)
                    if not wait_for_creator_page_count(page, pages, expected_count=1, timeout_ms=30_000):
                        raise CreatorSyncError("创作者页面没有返回作品列表；请确认链接公开且当前登录态可用")

                    while should_continue(
                        pages,
                        provider=provider,
                        limit=limit,
                        watermark=stop_at,
                        known_item_ids=known_item_ids,
                    ):
                        set_creator_capture_stage("加载更多作品")
                        captured_count = len(pages)
                        received_next_page = False
                        for _ in range(MAX_CREATOR_LOAD_ATTEMPTS):
                            if bilibili_favorites_page_url:
                                request_creator_api_page(page, bilibili_favorites_page_url)
                            else:
                                nudge_creator_page_load(page)
                            if wait_for_creator_page_count(
                                page,
                                pages,
                                expected_count=captured_count + 1,
                                timeout_ms=CREATOR_PAGE_RESPONSE_WAIT_MS,
                            ):
                                received_next_page = True
                                break
                        if not received_next_page:
                            break
                    title = page.title()
                    context.close()
                finally:
                    browser.close()
        except CreatorSyncError:
            record_creator_list_check(provider, state="failed", detail="未取得作品列表")
            raise
        except Exception as exc:
            record_creator_list_check(provider, state="failed", detail=str(exc))
            raise CreatorSyncError(f"内置浏览器采集失败：{exc}") from exc
        finally:
            finish_creator_browser_capture()
    return pages, title


def next_bilibili_favorites_page_url(response_url: str) -> str:
    """Build the next page URL from Bilibili's browser-originated list call."""
    parsed = urlparse(response_url)
    if parsed.path != "/x/v3/fav/resource/list":
        return ""
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    try:
        current_page = max(1, int(query.get("pn") or 1))
    except (TypeError, ValueError):
        current_page = 1
    query["pn"] = str(current_page + 1)
    return parsed._replace(query=urlencode(query)).geturl()


def request_creator_api_page(page, url: str) -> None:
    """Request a known next page inside the captured browser session."""
    try:
        page.evaluate(
            """(nextUrl) => { void fetch(nextUrl, { credentials: 'include' }); }""",
            url,
        )
    except Exception:
        # The usual scroll nudge on the following retry is the compatible
        # fallback when a navigation briefly invalidates the page context.
        nudge_creator_page_load(page)


def wait_for_creator_page_count(page, pages: list[dict[str, Any]], *, expected_count: int, timeout_ms: int) -> bool:
    """Wait for a response event without relying on a scrollable document."""
    elapsed_ms = 0
    while elapsed_ms < timeout_ms:
        if len(pages) >= expected_count:
            return True
        page.wait_for_timeout(250)
        elapsed_ms += 250
    return len(pages) >= expected_count


def nudge_creator_page_load(page) -> None:
    """Ask both ordinary and virtualized creator grids to load their next page."""
    try:
        page.mouse.wheel(0, 900)
        page.evaluate(
            """() => {
                window.scrollBy(0, Math.max(720, window.innerHeight * 0.9));
                window.scrollTo(0, document.documentElement.scrollHeight || document.body.scrollHeight);
                // Douyin keeps the profile grid in an overflow container;
                // scrolling window alone never reaches its intersection
                // sentinel. Class names are hashed, so identify the few
                // actual vertical scroll containers structurally instead.
                const containers = [...document.querySelectorAll('*')]
                    .filter((node) => {
                        const style = getComputedStyle(node);
                        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
                            && node.scrollHeight > node.clientHeight + 24;
                    })
                    .sort((left, right) => right.clientHeight - left.clientHeight)
                    .slice(0, 3);
                for (const container of containers) {
                    container.scrollTop = container.scrollHeight;
                    container.dispatchEvent(new Event('scroll', { bubbles: true }));
                }
            }"""
        )
    except Exception:
        # A navigation or a grid re-render can invalidate the frame briefly.
        # The response wait remains authoritative and a later nudge retries.
        return
