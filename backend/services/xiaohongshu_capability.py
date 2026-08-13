"""Feature-level capability boundary for clean-room Xiaohongshu support."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

XiaohongshuFeature = Literal[
    "credential_storage",
    "session_probe",
    "note_capture",
    "favorites_sync",
    "creator_sync",
    "comments_refresh",
]

NOTE_RUNTIME_UNAVAILABLE_REASON = (
    "未找到可用于小红书图文读取的 Chromium；请先在设置 > 设备准备中安装浏览器组件"
)
FAVORITES_UNAVAILABLE_REASON = "当前版本支持主动导入单篇图文；个人收藏与创作者同步暂未开放"
COMMENTS_UNAVAILABLE_REASON = "当前版本暂不采集小红书评论；正文、图片与页面互动数仍可读取"
# Compatibility name retained for callers/tests that consumed the former
# all-or-nothing public collector boundary.
PUBLIC_COLLECTOR_UNAVAILABLE_REASON = NOTE_RUNTIME_UNAVAILABLE_REASON


class XiaohongshuCollectorUnavailable(ValueError):
    """Raised before work requiring an unavailable XHS feature is accepted."""


def xiaohongshu_capabilities(*, browser_path: str | None = None) -> dict[str, dict[str, object]]:
    if browser_path is None:
        from services.runtime_components import browser_executable

        browser_path = browser_executable()
    browser_ready = bool(browser_path)
    return {
        "credential_storage": {"supported": True, "available": True, "reason": ""},
        "session_probe": {
            "supported": True,
            "available": browser_ready,
            "reason": "" if browser_ready else NOTE_RUNTIME_UNAVAILABLE_REASON,
        },
        "note_capture": {
            "supported": True,
            "available": browser_ready,
            "reason": "" if browser_ready else NOTE_RUNTIME_UNAVAILABLE_REASON,
        },
        "favorites_sync": {
            "supported": False,
            "available": False,
            "reason": FAVORITES_UNAVAILABLE_REASON,
        },
        "creator_sync": {
            "supported": False,
            "available": False,
            "reason": FAVORITES_UNAVAILABLE_REASON,
        },
        "comments_refresh": {
            "supported": False,
            "available": False,
            "reason": COMMENTS_UNAVAILABLE_REASON,
        },
    }


def require_xiaohongshu_feature(
    feature: XiaohongshuFeature,
    *,
    capabilities: Mapping[str, Mapping[str, object]] | None = None,
) -> None:
    snapshot = capabilities or xiaohongshu_capabilities()
    capability = snapshot[feature]
    if not capability.get("available"):
        raise XiaohongshuCollectorUnavailable(str(capability.get("reason") or "小红书功能当前不可用"))


def require_xiaohongshu_request(
    request: object,
    *,
    capabilities: Mapping[str, Mapping[str, object]] | None = None,
) -> None:
    """Classify queued XHS work before any task or content state is mutated."""
    from services.creator_source_registry import get_creator_source
    from services.database import connect
    from services.repository import ContentRepository
    from services.url_parser import parse_share_text

    sync_request = dict(getattr(request, "source_sync_request", None) or {})
    kind = str(sync_request.get("kind") or "")
    payload = dict(sync_request.get("payload") or {})
    if kind == "favorite_xiaohongshu":
        require_xiaohongshu_feature("favorites_sync", capabilities=capabilities)
        return
    if kind == "creator_saved":
        try:
            source = get_creator_source(str(sync_request.get("source_id") or ""))
        except LookupError:
            source = None
        if source is not None and source.get("provider") == "xiaohongshu":
            require_xiaohongshu_feature("creator_sync", capabilities=capabilities)
            return
    if kind == "creator_new":
        from urllib.parse import urlparse

        creator_values = (
            sync_request.get("source_url"),
            payload.get("source_url"),
        )
        xhs_hosts = {
            "xiaohongshu.com",
            "www.xiaohongshu.com",
            "xhslink.com",
            "www.xhslink.com",
            "xhslink.cn",
            "www.xhslink.cn",
        }
        if any(
            ((parsed := parse_share_text(str(value or ""))) is not None and parsed.platform == "xiaohongshu")
            or (urlparse(str(value or "")).hostname or "").lower() in xhs_hosts
            for value in creator_values
        ):
            require_xiaohongshu_feature("creator_sync", capabilities=capabilities)
            return

    content_item_id = str(
        sync_request.get("source_id")
        if kind == "source_context_refresh"
        else getattr(request, "content_item_id", None) or ""
    )
    item = None
    if content_item_id:
        try:
            with connect() as connection:
                item = ContentRepository(connection).get_content_item(content_item_id)
        except LookupError:
            item = None
    if kind == "source_context_refresh" and item is not None and item.source_provider == "xiaohongshu":
        require_xiaohongshu_feature("comments_refresh", capabilities=capabilities)
        return

    values = (
        getattr(request, "share_text", None),
        getattr(request, "source_url", None),
        sync_request.get("source_url"),
        payload.get("source_url"),
    )
    targets_xhs_note = any(
        (parsed := parse_share_text(str(value or ""))) is not None and parsed.platform == "xiaohongshu"
        for value in values
    ) or (item is not None and item.source_provider == "xiaohongshu")
    if targets_xhs_note:
        require_xiaohongshu_feature("note_capture", capabilities=capabilities)
