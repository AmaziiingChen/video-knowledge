"""Public-build capability boundary for the optional Xiaohongshu collector."""

from __future__ import annotations

from pathlib import Path
import sys


PUBLIC_COLLECTOR_UNAVAILABLE_REASON = "公开版未携带采集组件，已缓存资料仍可阅读"


class XiaohongshuCollectorUnavailable(ValueError):
    """Raised before a public build accepts work it cannot complete."""


def xiaohongshu_vendor_root() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return Path(getattr(sys, "_MEIPASS")) / "vendor" / "Spider_XHS"
    return Path(__file__).resolve().parents[1] / "vendor" / "Spider_XHS"


def xiaohongshu_collector_capability() -> dict[str, object]:
    root = xiaohongshu_vendor_root()
    available = (root / "apis" / "xhs_pc_apis.py").is_file() and (
        root / "xhs_utils" / "xhs_pc.py"
    ).is_file()
    return {
        "available": available,
        "reason": "" if available else PUBLIC_COLLECTOR_UNAVAILABLE_REASON,
    }


def require_xiaohongshu_collector() -> Path:
    capability = xiaohongshu_collector_capability()
    if not capability["available"]:
        raise XiaohongshuCollectorUnavailable(str(capability["reason"]))
    return xiaohongshu_vendor_root()


def require_xiaohongshu_request(request: object) -> None:
    """Reject queued work that resolves to the optional collector."""
    from services.creator_source_registry import get_creator_source
    from services.database import connect
    from services.repository import ContentRepository
    from services.url_parser import parse_share_text

    sync_request = dict(getattr(request, "source_sync_request", None) or {})
    kind = str(sync_request.get("kind") or "")
    payload = dict(sync_request.get("payload") or {})
    values = [getattr(request, "share_text", None), getattr(request, "source_url", None), sync_request.get("source_url"), payload.get("source_url")]
    targets_xhs = kind == "favorite_xiaohongshu" or any(
        (parsed := parse_share_text(str(value or ""))) is not None and parsed.platform == "xiaohongshu"
        for value in values
    )
    if not targets_xhs and kind == "creator_saved":
        try:
            source = get_creator_source(str(sync_request.get("source_id") or ""))
        except LookupError:
            source = None
        targets_xhs = source is not None and source.get("provider") == "xiaohongshu"
    content_item_id = str(sync_request.get("source_id") if kind == "source_context_refresh" else getattr(request, "content_item_id", None) or "")
    if not targets_xhs and content_item_id:
        try:
            with connect() as connection:
                item = ContentRepository(connection).get_content_item(content_item_id)
        except LookupError:
            item = None
        targets_xhs = item is not None and item.source_provider == "xiaohongshu"
    if targets_xhs:
        require_xiaohongshu_collector()
