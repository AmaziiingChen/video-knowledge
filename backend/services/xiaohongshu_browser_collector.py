"""Clean-room XHS reader that observes responses made by the visible web page.

The collector never implements XHS request signing and never calls private API
endpoints itself. It loads a user-supplied page in Playwright and accepts only
two narrowly allowlisted JSON responses initiated by that page.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.parse import urlparse

from services.network_policy import direct_browser_launch_options
from services.runtime_components import browser_executable

_ALLOWED_HOSTS = frozenset({"xiaohongshu.com", "www.xiaohongshu.com"})
_NOTE_PATH = "/api/sns/h5/v1/note_info"
_PROFILE_PATH = "/api/sns/web/v2/user/me"
_RESPONSE_TYPES = frozenset({"fetch", "xhr"})
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_NOTE_IMAGES = 20
_LOCK_TIMEOUT_SECONDS = 5.0
_BROWSER_LOCK = Lock()


class XiaohongshuBrowserError(ValueError):
    """Safe browser-reader failure; never contains response or credential data."""


@dataclass(frozen=True)
class XiaohongshuSessionProbe:
    state: str
    user_id: str = ""
    nickname: str = ""
    detail: str = ""


@dataclass(frozen=True)
class CollectedXiaohongshuNote:
    note_id: str
    title: str
    author: str
    author_id: str
    avatar_url: str
    description: str
    image_urls: tuple[str, ...]
    published_at_ms: object
    tags: tuple[str, ...]
    stats: dict[str, int]
    ip_location: str


def playwright_cookies_from_header(raw_cookie: str) -> list[dict[str, object]]:
    cookies: list[dict[str, object]] = []
    for part in (piece.strip() for piece in str(raw_cookie or "").split(";") if piece.strip()):
        if "=" not in part:
            continue
        name, value = (item.strip() for item in part.split("=", 1))
        if not name or not value or any(char in f"{name}{value}" for char in "\r\n"):
            continue
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".xiaohongshu.com",
            "path": "/",
            "secure": True,
        })
    if not cookies:
        raise XiaohongshuBrowserError("未读取到有效的小红书登录凭据，请重新登录")
    return cookies


def parse_user_me_payload(payload: object) -> XiaohongshuSessionProbe:
    if not isinstance(payload, dict):
        return XiaohongshuSessionProbe(state="invalid", detail="平台未确认当前登录会话")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    user_id = str(data.get("user_id") or data.get("userid") or "").strip()
    guest = data.get("guest") is True or str(data.get("guest") or "").lower() in {"1", "true", "yes"}
    if not user_id or guest:
        return XiaohongshuSessionProbe(state="invalid", detail="当前登录会话已失效，请重新登录")
    return XiaohongshuSessionProbe(
        state="valid",
        user_id=user_id,
        nickname=str(data.get("nickname") or data.get("nick_name") or "").strip(),
        detail="会话已验证，可主动导入单篇图文",
    )


def parse_note_info_payload(payload: object, *, expected_note_id: str) -> CollectedXiaohongshuNote:
    if not isinstance(payload, dict):
        raise XiaohongshuBrowserError("小红书页面未返回可读取的图文数据")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for key in ("items", "notes"):
        value = data.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    if isinstance(data.get("note"), dict):
        candidates.append(data["note"])
    if isinstance(data.get("item"), dict):
        candidates.append(data["item"])
    if not candidates and any(key in data for key in ("note_card", "noteCard", "id", "note_id")):
        candidates.append(data)
    expected = str(expected_note_id or "").strip()
    raw = next((item for item in candidates if _note_id(item) == expected), None)
    if raw is None:
        raise XiaohongshuBrowserError("小红书页面返回的图文与当前链接不一致，已拒绝保存")
    card = raw.get("note_card") or raw.get("noteCard") or raw.get("note") or raw
    if not isinstance(card, dict):
        raise XiaohongshuBrowserError("小红书页面未返回可读取的图文数据")
    user = card.get("user") if isinstance(card.get("user"), dict) else {}
    description = str(card.get("desc") or card.get("description") or "").strip()
    title = str(card.get("title") or "").strip() or " ".join(description.split())[:80]
    if not title:
        title = f"小红书图文 · {expected[:12]}"
    image_urls: list[str] = []
    for image in list(card.get("image_list") or card.get("imageList") or [])[:_MAX_NOTE_IMAGES]:
        if not isinstance(image, dict):
            continue
        variants = image.get("info_list") or image.get("infoList") or []
        candidate = next(
            (str(item.get("url") or "") for item in reversed(variants) if isinstance(item, dict) and item.get("url")),
            str(image.get("url") or image.get("url_default") or ""),
        )
        if candidate.startswith("https://"):
            image_urls.append(candidate)
    interaction = card.get("interact_info") or card.get("interactInfo") or {}
    if not isinstance(interaction, Mapping):
        interaction = {}
    tags = card.get("tag_list") or card.get("tagList") or []
    return CollectedXiaohongshuNote(
        note_id=expected,
        title=title,
        author=str(user.get("nickname") or "小红书用户").strip(),
        author_id=str(user.get("user_id") or user.get("userId") or "").strip(),
        avatar_url=str(user.get("avatar") or user.get("image") or "").strip(),
        description=description,
        image_urls=tuple(dict.fromkeys(image_urls)),
        published_at_ms=card.get("time") or card.get("publish_time"),
        tags=tuple(
            str(tag.get("name") or "").strip()
            for tag in tags
            if isinstance(tag, dict) and str(tag.get("name") or "").strip()
        ),
        stats={
            "liked": _as_int(interaction.get("liked_count") or interaction.get("likedCount")),
            "collected": _as_int(interaction.get("collected_count") or interaction.get("collectedCount")),
            "comment": _as_int(interaction.get("comment_count") or interaction.get("commentCount")),
            "shared": _as_int(interaction.get("share_count") or interaction.get("shareCount")),
        },
        ip_location=str(card.get("ip_location") or card.get("ipLocation") or ""),
    )


def probe_xiaohongshu_session(raw_cookie: str) -> XiaohongshuSessionProbe:
    payload = _observe_page_response(
        "https://www.xiaohongshu.com/",
        raw_cookie=raw_cookie,
        expected_path=_PROFILE_PATH,
    )
    return parse_user_me_payload(payload)


def fetch_xiaohongshu_note(source_url: str, *, raw_cookie: str, expected_note_id: str) -> CollectedXiaohongshuNote:
    payload = _observe_page_response(source_url, raw_cookie=raw_cookie, expected_path=_NOTE_PATH)
    return parse_note_info_payload(payload, expected_note_id=expected_note_id)


def _observe_page_response(
    source_url: str,
    *,
    raw_cookie: str,
    expected_path: str,
    timeout_ms: int = 30_000,
    playwright_factory: Callable[[], object] | None = None,
) -> object:
    executable = browser_executable()
    if not executable:
        raise XiaohongshuBrowserError(
            "未找到可用于小红书图文读取的 Chromium；请先在设置 > 设备准备中安装浏览器组件"
        )
    parsed_source = urlparse(source_url)
    if parsed_source.scheme != "https" or (parsed_source.hostname or "").lower() not in _ALLOWED_HOSTS:
        raise XiaohongshuBrowserError("拒绝打开非小红书网页")
    cookies = playwright_cookies_from_header(raw_cookie)
    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise XiaohongshuBrowserError("小红书图文读取所需的浏览器组件不可用") from exc
        playwright_factory = sync_playwright

    captured: list[object] = []
    if not _BROWSER_LOCK.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
        raise XiaohongshuBrowserError("小红书页面读取正忙，请稍后重试")
    try:
        try:
            with playwright_factory() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=executable,
                    **direct_browser_launch_options("--disable-blink-features=AutomationControlled"),
                )
                context = None
                try:
                    context = browser.new_context(locale="zh-CN", viewport={"width": 1440, "height": 1000})
                    context.add_cookies(cookies)
                    page = context.new_page()

                    def capture(response) -> None:
                        parsed = urlparse(str(response.url or ""))
                        request = getattr(response, "request", None)
                        if (
                            parsed.scheme != "https"
                            or (parsed.hostname or "").lower() not in _ALLOWED_HOSTS
                            or parsed.path != expected_path
                            or getattr(request, "resource_type", "") not in _RESPONSE_TYPES
                        ):
                            return
                        status = int(getattr(response, "status", 0) or 0)
                        headers = response.headers or {}
                        content_type = str(headers.get("content-type") or "").split(";", 1)[0].strip().lower()
                        if not 200 <= status < 300 or not (
                            content_type in {"application/json", "text/json"}
                            or content_type.startswith("application/") and content_type.endswith("+json")
                        ):
                            return
                        try:
                            body = response.body()
                            if not isinstance(body, bytes) or len(body) > _MAX_RESPONSE_BYTES:
                                return
                            payload = json.loads(body)
                        # Browser response wrappers may raise backend-specific
                        # exceptions; all details are discarded at this boundary.
                        except Exception:  # noqa: BLE001
                            return
                        if isinstance(payload, dict):
                            captured.append(payload)

                    page.on("response", capture)
                    deadline = time.monotonic() + timeout_ms / 1000
                    page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    while not captured and time.monotonic() < deadline:
                        page.wait_for_timeout(200)
                finally:
                    try:
                        if context is not None:
                            context.close()
                    finally:
                        browser.close()
        except XiaohongshuBrowserError:
            raise
        except Exception as exc:
            raise XiaohongshuBrowserError("小红书页面读取失败，请检查登录状态、网络或浏览器组件") from exc
    finally:
        _BROWSER_LOCK.release()
    if not captured:
        raise XiaohongshuBrowserError("小红书页面未返回可读取数据，请重新登录后重试")
    return captured[-1]


def _note_id(raw: dict[str, Any]) -> str:
    card = raw.get("note_card") or raw.get("noteCard") or raw.get("note") or {}
    return str(
        raw.get("id")
        or raw.get("note_id")
        or raw.get("noteId")
        or (card.get("id") if isinstance(card, dict) else "")
        or (card.get("note_id") if isinstance(card, dict) else "")
        or (card.get("noteId") if isinstance(card, dict) else "")
        or ""
    ).strip()


def _as_int(value: object) -> int:
    try:
        return int(str(value or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0
