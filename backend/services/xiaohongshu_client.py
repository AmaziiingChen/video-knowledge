"""Stable application contract for clean-room Xiaohongshu page reading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from config import settings

from services.xiaohongshu_capability import (
    require_xiaohongshu_feature,
    xiaohongshu_capabilities,
)


class XiaohongshuClientError(ValueError):
    """A safe, actionable error from the local XHS collector."""


@dataclass(frozen=True)
class XiaohongshuNote:
    note_id: str
    source_url: str
    title: str
    author: str
    author_url: str
    avatar_url: str
    description: str
    image_urls: tuple[str, ...]
    published_at: str
    tags: tuple[str, ...]
    stats: dict[str, int]
    ip_location: str
    comment_sample: tuple[dict[str, object], ...] = ()
    comments_complete: bool = False


def xiaohongshu_cookie_path() -> Path:
    return settings.data_dir / "xiaohongshu_cookie.txt"


def save_xiaohongshu_cookie(cookie: str) -> None:
    value = str(cookie or "").strip()
    if not value:
        raise XiaohongshuClientError("小红书 Cookie 不能为空")
    path = xiaohongshu_cookie_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        # Windows and a few network volumes do not expose POSIX permissions.
        pass


def clear_xiaohongshu_cookie() -> None:
    xiaohongshu_cookie_path().unlink(missing_ok=True)


def xiaohongshu_cookie_status(*, probe: bool = False) -> dict[str, object]:
    path = xiaohongshu_cookie_path()
    configured = path.is_file() and bool(path.read_text(encoding="utf-8", errors="ignore").strip())
    capabilities = xiaohongshu_capabilities()
    capability = capabilities["note_capture"]
    capability_fields = {
        "collector_available": bool(capability["available"]),
        "collector_reason": str(capability["reason"]),
        "capabilities": capabilities,
    }
    session_probe = capabilities["session_probe"]
    if not session_probe["available"]:
        return {
            "configured": configured,
            "state": "unavailable",
            "label": "小红书浏览器组件未准备",
            "detail": str(session_probe["reason"]),
            **capability_fields,
        }
    if not configured:
        return {
            "configured": False,
            "state": "missing",
            "label": "小红书登录态未连接",
            "detail": "请在应用内登录，或手动粘贴 Cookie。",
            **capability_fields,
        }
    if not probe:
        return {
            "configured": True,
            "state": "unknown",
            "label": "小红书登录态已保存",
            "detail": "已保存到本机；点击“检查可用性”验证。",
            **capability_fields,
        }
    try:
        from services.xiaohongshu_browser_collector import (
            XiaohongshuBrowserError,
            probe_xiaohongshu_session,
        )

        result = probe_xiaohongshu_session(path.read_text(encoding="utf-8").strip())
        if result.state == "valid":
            return {
                "configured": True,
                "state": "valid",
                "label": "小红书登录态可用",
                "detail": "会话已验证，可主动导入单篇图文。",
                **capability_fields,
            }
        return {
            "configured": True,
            "state": "invalid",
            "label": "小红书登录态需要更新",
            "detail": str(result.detail or "平台未确认当前会话")[:300],
            **capability_fields,
        }
    except XiaohongshuBrowserError:
        return {
            "configured": True,
            "state": "unknown",
            "label": "小红书登录态待确认",
            "detail": "小红书会话检查失败，请重新登录后重试",
            **capability_fields,
        }
    # Status is best effort. Never reflect runtime/cookie details to the UI.
    except Exception:  # noqa: BLE001
        return {
            "configured": True,
            "state": "unknown",
            "label": "小红书登录态待确认",
            "detail": "小红书会话检查失败，请稍后重试",
            **capability_fields,
        }


def normalize_note_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    note_id = parsed.path.rstrip("/").split("/")[-1]
    if not note_id or note_id in {"explore", "discovery", ""}:
        raise XiaohongshuClientError("不是有效的小红书笔记链接")
    query = parse_qs(parsed.query)
    token = str((query.get("xsec_token") or [""])[-1]).strip()
    source = str((query.get("xsec_source") or ["pc_search"])[-1]).strip() or "pc_search"
    suffix = f"?xsec_token={token}&xsec_source={source}" if token else f"?xsec_source={source}"
    return f"https://www.xiaohongshu.com/explore/{note_id}{suffix}"


def note_id_from_url(value: str) -> str:
    return urlparse(normalize_note_url(value)).path.rsplit("/", 1)[-1]


def fetch_note(
    source_url: str,
    *,
    include_comments: bool = False,
    comment_limit: int = 24,
    comment_pages: int = 1,
) -> XiaohongshuNote:
    del comment_limit, comment_pages
    if include_comments:
        require_xiaohongshu_feature("comments_refresh")
    require_xiaohongshu_feature("note_capture")
    url = normalize_note_url(source_url)
    try:
        raw_cookie = xiaohongshu_cookie_path().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise XiaohongshuClientError("请先在设置中连接小红书登录态") from exc
    if not raw_cookie:
        raise XiaohongshuClientError("请先在设置中连接小红书登录态")
    try:
        from services.xiaohongshu_browser_collector import (
            XiaohongshuBrowserError,
            fetch_xiaohongshu_note,
        )

        collected = fetch_xiaohongshu_note(
            url,
            raw_cookie=raw_cookie,
            expected_note_id=note_id_from_url(url),
        )
    except XiaohongshuBrowserError as exc:
        # Browser/runtime internals and response data must not cross the API.
        raise XiaohongshuClientError("小红书页面读取失败，请检查登录状态、网络或浏览器组件") from exc
    except Exception as exc:
        raise XiaohongshuClientError("小红书图文读取失败，请稍后重试") from exc
    return XiaohongshuNote(
        note_id=collected.note_id,
        source_url=url,
        title=collected.title,
        author=collected.author,
        author_url=(
            f"https://www.xiaohongshu.com/user/profile/{collected.author_id}"
            if collected.author_id
            else ""
        ),
        avatar_url=collected.avatar_url,
        description=collected.description,
        image_urls=collected.image_urls,
        published_at=_format_timestamp(collected.published_at_ms),
        tags=collected.tags,
        stats=collected.stats,
        ip_location=collected.ip_location,
    )


def fetch_my_favorites(*, limit: int = 5) -> list[XiaohongshuNote]:
    del limit
    require_xiaohongshu_feature("favorites_sync")
    return []


def fetch_my_favorites_preview(
    *,
    limit: int = 50,
    profile_user_id: str | None = None,
) -> tuple[list[XiaohongshuNote], dict[str, str]]:
    del limit, profile_user_id
    require_xiaohongshu_feature("favorites_sync")
    return [], {}


def _format_timestamp(value: object) -> str:
    try:
        from datetime import datetime
        return datetime.fromtimestamp(int(value) / 1000).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""
