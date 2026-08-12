"""Narrow local bridge to the bundled Spider_XHS PC collector.

Only read-side note and personal-favorites calls are exposed here.  Keeping
the third-party signing runtime behind this module prevents it leaking into
the normal provider, task, and reader contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import sys
from threading import Lock
from urllib.parse import parse_qs, urlparse

from config import settings
from services.source_context import MAX_STORED_COMMENTS
from services.xiaohongshu_capability import (
    require_xiaohongshu_collector,
    xiaohongshu_collector_capability,
)


_IMPORT_LOCK = Lock()


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


def _is_guest_session(profile_data: object) -> bool:
    if not isinstance(profile_data, dict):
        return False
    value = profile_data.get("guest")
    return value is True or value == 1 or str(value or "").strip().lower() in {"1", "true", "yes"}


def xiaohongshu_cookie_status(*, probe: bool = False) -> dict[str, object]:
    path = xiaohongshu_cookie_path()
    configured = path.is_file() and bool(path.read_text(encoding="utf-8", errors="ignore").strip())
    capability = xiaohongshu_collector_capability()
    capability_fields = {
        "collector_available": bool(capability["available"]),
        "collector_reason": str(capability["reason"]),
    }
    if not capability["available"]:
        return {
            "configured": configured,
            "state": "unavailable",
            "label": "小红书采集不可用",
            "detail": str(capability["reason"]),
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
        success, message, profile = _api().get_user_me()
        profile_data = (profile or {}).get("data") or {}
        user_id = str(profile_data.get("user_id") or "").strip()
        if success and user_id and not _is_guest_session(profile_data):
            return {
                "configured": True,
                "state": "valid",
                "label": "小红书登录态可用",
                "detail": "会话已验证，可读取图文和“我的收藏”。",
                **capability_fields,
            }
        if success and _is_guest_session(profile_data):
            return {
                "configured": True,
                "state": "invalid",
                "label": "小红书登录态需要更新",
                "detail": "当前 Cookie 被小红书识别为访客会话，请重新登录并完成授权。",
                **capability_fields,
            }
        return {
            "configured": True,
            "state": "invalid",
            "label": "小红书登录态需要更新",
            "detail": str(message or "平台未确认当前会话")[:300],
            **capability_fields,
        }
    except Exception as exc:
        return {
            "configured": True,
            "state": "unknown",
            "label": "小红书登录态待确认",
            "detail": str(exc)[:300],
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
    include_comments: bool = True,
    comment_limit: int = 24,
    comment_pages: int = 1,
) -> XiaohongshuNote:
    api = _api()
    url = normalize_note_url(source_url)
    try:
        success, message, payload = api.get_note_info(url)
    except Exception as exc:  # Signing/runtime details must not leak to the UI.
        raise XiaohongshuClientError(f"小红书笔记读取失败：{exc}") from exc
    if not success or not isinstance(payload, dict):
        raise XiaohongshuClientError(f"小红书笔记读取失败：{message or '未知错误'}")
    try:
        raw = ((payload.get("data") or {}).get("items") or [])[0]
        note = _note_from_raw(raw, source_url=url)
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise XiaohongshuClientError("小红书未返回可读取的图文笔记") from exc
    if not include_comments:
        return note
    comments, complete = _fetch_note_comment_sample(
        api,
        url,
        limit=comment_limit,
        pages=comment_pages,
    )
    return replace(note, comment_sample=tuple(comments), comments_complete=complete)


def fetch_my_favorites(*, limit: int = 5) -> list[XiaohongshuNote]:
    notes, _account = fetch_my_favorites_preview(limit=limit)
    return notes


def fetch_my_favorites_preview(
    *,
    limit: int = 50,
    profile_user_id: str | None = None,
) -> tuple[list[XiaohongshuNote], dict[str, str]]:
    """Read a bounded, paginated preview of the current account's favorites.

    The bundled collector exposes a cursor API with 30 entries per page.  The
    old synchronizer intentionally read one page and then silently sliced it
    to five.  Creator subscriptions need an explicit user-selected breadth,
    so this bridge follows cursors only until that bounded request is met.
    """
    requested_limit = max(1, min(int(limit), 500))
    api = _api()
    try:
        success, message, profile = api.get_user_me()
        profile_data = (profile or {}).get("data") or {}
        user_id = str(profile_data.get("user_id") or "").strip()
        if not success or not user_id:
            raise XiaohongshuClientError(message or "未读取到当前登录账号")
        if _is_guest_session(profile_data):
            raise XiaohongshuClientError("当前小红书登录态为访客会话，请在设置中重新登录并完成授权")
        collection_user_id = str(profile_user_id or user_id).strip()
        if not collection_user_id:
            raise XiaohongshuClientError("未读取到收藏页账号标识")
        account = {
            "user_id": user_id,
            "collection_user_id": collection_user_id,
            "nickname": str(profile_data.get("nickname") or profile_data.get("nick_name") or "我的小红书收藏").strip(),
            "avatar_url": str(profile_data.get("image") or profile_data.get("avatar") or "").strip(),
        }
        raw_notes: list[dict] = []
        seen_note_ids: set[str] = set()
        cursor = ""
        # 500 / 30 is 17; the extra guard protects against an upstream cursor
        # loop without turning an interactive search into an endless task.
        for _page in range(18):
            success, message, payload = api.get_user_collect_note_info(
                collection_user_id,
                cursor,
                xsec_source="pc_user",
            )
            if not success or not isinstance(payload, dict):
                raise XiaohongshuClientError(message or "小红书未返回收藏列表")
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            page_notes = data.get("notes") if isinstance(data.get("notes"), list) else []
            for entry in page_notes:
                if not isinstance(entry, dict):
                    continue
                note_id = str(entry.get("note_id") or entry.get("id") or "").strip()
                if note_id and note_id in seen_note_ids:
                    continue
                raw_notes.append(entry)
                if note_id:
                    seen_note_ids.add(note_id)
                if len(raw_notes) >= requested_limit:
                    break
            if len(raw_notes) >= requested_limit or not bool(data.get("has_more")):
                break
            next_cursor = str(data.get("cursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    except Exception as exc:
        raise XiaohongshuClientError(f"读取小红书收藏失败：{exc}") from exc
    resolved: list[XiaohongshuNote] = []
    for entry in raw_notes[:requested_limit]:
        note_id = str(entry.get("note_id") or entry.get("id") or "").strip()
        token = str(entry.get("xsec_token") or "").strip()
        if not note_id:
            continue
        url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_user"
        try:
            # List cards already expose the metadata used by the creator
            # preview. Avoid serially reopening every note during search; the
            # regular processing pipeline fetches full content after a user
            # explicitly subscribes it.
            resolved.append(_note_from_raw(entry, source_url=url))
        except XiaohongshuClientError:
            try:
                resolved.append(fetch_note(url, include_comments=False))
            except XiaohongshuClientError:
                continue
        except (KeyError, TypeError, ValueError):
            try:
                resolved.append(fetch_note(url, include_comments=False))
            except XiaohongshuClientError:
                continue
    return resolved, account


def _api():
    vendor_root = require_xiaohongshu_collector()
    cookie_path = xiaohongshu_cookie_path()
    try:
        cookie = cookie_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise XiaohongshuClientError("请先在设置中填写小红书 Cookie") from exc
    if not cookie:
        raise XiaohongshuClientError("请先在设置中填写小红书 Cookie")
    with _IMPORT_LOCK:
        vendor = str(vendor_root)
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        from apis.xhs_pc_apis import XHS_Apis
        from xhs_utils.xhs_pc import XHSPcAuth
    try:
        return XHS_Apis(XHSPcAuth.from_cookie(cookie)).bootstrap()
    except Exception as exc:
        raise XiaohongshuClientError("小红书登录状态失效，请重新填写 Cookie") from exc


def _note_from_raw(raw: dict, *, source_url: str) -> XiaohongshuNote:
    card = raw.get("note_card") or {}
    user = card.get("user") or {}
    images = []
    for image in list(card.get("image_list") or []):
        info_list = list(image.get("info_list") or [])
        candidate = next((str(item.get("url") or "") for item in reversed(info_list) if item.get("url")), "")
        if candidate:
            images.append(candidate)
    interaction = card.get("interact_info") or {}
    raw_id = str(raw.get("id") or note_id_from_url(source_url))
    description = str(card.get("desc") or "").strip()
    title = str(card.get("title") or "").strip()
    # Title is optional on XHS notes.  Prefer the first readable description
    # line over a generic placeholder; when a note is genuinely textless, its
    # stable note ID still makes the row identifiable and retryable.
    if not title and description:
        title = " ".join(description.split())[:80]
    if not title:
        title = f"小红书图文 · {raw_id[:12]}"
    return XiaohongshuNote(
        note_id=raw_id,
        source_url=normalize_note_url(source_url),
        title=title,
        author=str(user.get("nickname") or "小红书用户").strip(),
        author_url=f"https://www.xiaohongshu.com/user/profile/{str(user.get('user_id') or '').strip()}",
        avatar_url=str(user.get("avatar") or ""),
        description=description,
        image_urls=tuple(images),
        published_at=_format_timestamp(card.get("time")),
        tags=tuple(str(tag.get("name") or "").strip() for tag in list(card.get("tag_list") or []) if tag.get("name")),
        stats={key: _as_int(interaction.get(field)) for key, field in {"liked": "liked_count", "collected": "collected_count", "comment": "comment_count", "shared": "share_count"}.items()},
        ip_location=str(card.get("ip_location") or ""),
    )


def _fetch_note_comment_sample(
    api,
    source_url: str,
    *,
    limit: int,
    pages: int,
) -> tuple[list[dict[str, object]], bool]:
    query = parse_qs(urlparse(source_url).query)
    token = str((query.get("xsec_token") or [""])[-1]).strip()
    if not token:
        return [], False
    bounded_limit = max(1, min(int(limit), MAX_STORED_COMMENTS))
    bounded_pages = max(1, min(int(pages), 6))
    comments: list[dict[str, object]] = []
    known_ids: set[str] = set()
    cursor = ""
    complete = False
    for _page_number in range(bounded_pages):
        try:
            success, _message, payload = api.get_note_out_comment(
                note_id_from_url(source_url),
                cursor,
                token,
            )
        except Exception:
            break
        if not success or not isinstance(payload, dict):
            break
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        roots = data.get("comments") if isinstance(data.get("comments"), list) else []
        for root in roots:
            if not isinstance(root, dict):
                continue
            root_id = str(root.get("id") or "")
            _append_xiaohongshu_comment(comments, known_ids, root, limit=bounded_limit)
            for child in root.get("sub_comments") if isinstance(root.get("sub_comments"), list) else []:
                if isinstance(child, dict):
                    _append_xiaohongshu_comment(
                        comments,
                        known_ids,
                        child,
                        parent_id=root_id,
                        limit=bounded_limit,
                    )
                if len(comments) >= bounded_limit:
                    break
            if len(comments) >= bounded_limit:
                break
        complete = not bool(data.get("has_more"))
        if complete or len(comments) >= bounded_limit:
            break
        next_cursor = str(data.get("cursor") or "").strip()
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return comments, complete


def _append_xiaohongshu_comment(
    target: list[dict[str, object]],
    known_ids: set[str],
    raw: dict[str, object],
    *,
    parent_id: str = "",
    limit: int,
) -> None:
    if len(target) >= limit:
        return
    comment_id = str(raw.get("id") or "")
    if comment_id and comment_id in known_ids:
        return
    target.append(_xiaohongshu_comment(raw, parent_id=parent_id))
    if comment_id:
        known_ids.add(comment_id)


def _xiaohongshu_comment(raw: dict[str, object], *, parent_id: str = "") -> dict[str, object]:
    user = raw.get("user_info") if isinstance(raw.get("user_info"), dict) else {}
    return {
        "comment_id": raw.get("id"),
        "parent_id": parent_id,
        "author": user.get("nickname"),
        "text": raw.get("content"),
        "like_count": raw.get("like_count"),
        "reply_count": raw.get("sub_comment_count"),
        "created_at": _format_timestamp(raw.get("create_time")),
        "ip_location": raw.get("ip_location"),
    }


def _format_timestamp(value: object) -> str:
    try:
        from datetime import datetime
        return datetime.fromtimestamp(int(value) / 1000).astimezone().strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _as_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
