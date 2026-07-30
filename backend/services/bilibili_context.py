from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import httpx

from services.bilibili_auth import bilibili_playwright_cookies
from services.bilibili_url import extract_bvid, requested_page_number
from services.source_context import MAX_COMMENT_SAMPLE, MAX_STORED_COMMENTS, build_source_context


_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}


def fetch_bilibili_source_context(
    url: str,
    *,
    client: httpx.Client | None = None,
    comment_limit: int = MAX_COMMENT_SAMPLE,
    comment_pages: int = 1,
) -> dict[str, object]:
    """Fetch bounded public work metadata and a first-page comment sample."""
    bvid = extract_bvid(url)
    if not bvid:
        raise ValueError("无法从 B站链接中提取 BV 号")
    comment_limit = max(1, min(int(comment_limit), MAX_STORED_COMMENTS))
    comment_pages = max(1, min(int(comment_pages), 6))
    cookies = {
        str(item["name"]): str(item["value"])
        for item in bilibili_playwright_cookies()
        if item.get("name")
    }
    own_client = client is None
    active_client = client or httpx.Client(
        headers=_HEADERS,
        cookies=cookies,
        timeout=15,
        follow_redirects=True,
        trust_env=False,
    )
    try:
        view = _api_data(active_client, "/x/web-interface/view", {"bvid": bvid})
        page_number = requested_page_number(url)
        pages = view.get("pages") if isinstance(view.get("pages"), list) else []
        page = pages[page_number - 1] if 0 < page_number <= len(pages) and isinstance(pages[page_number - 1], dict) else {}
        stat = view.get("stat") if isinstance(view.get("stat"), dict) else {}
        owner = view.get("owner") if isinstance(view.get("owner"), dict) else {}
        part_title = str(page.get("part") or "").strip()
        work_description = str(view.get("desc") or "").strip()
        description_parts = []
        if part_title:
            description_parts.append(f"当前分集：{part_title}")
        if work_description and work_description != part_title:
            description_parts.append(f"视频简介：{work_description}")
        comments: list[dict[str, object]] = []
        comments_complete = False
        try:
            next_cursor = 0
            for _page_number in range(comment_pages):
                reply_data = _api_data(
                    active_client,
                    "/x/v2/reply/main",
                    {
                        "type": 1,
                        "oid": int(view.get("aid") or 0),
                        "mode": 3,
                        "next": next_cursor,
                        "ps": min(20, max(1, comment_limit - len(comments))),
                    },
                )
                roots = reply_data.get("replies") if isinstance(reply_data.get("replies"), list) else []
                _extend_unique_comments(
                    comments,
                    _bilibili_comments(roots, limit=comment_limit - len(comments)),
                    limit=comment_limit,
                )
                cursor = reply_data.get("cursor") if isinstance(reply_data.get("cursor"), dict) else {}
                comments_complete = bool(cursor.get("is_end"))
                if comments_complete or len(comments) >= comment_limit:
                    break
                next_value = cursor.get("next")
                try:
                    parsed_next = int(next_value)
                except (TypeError, ValueError):
                    break
                if parsed_next == next_cursor:
                    break
                next_cursor = parsed_next
        except (httpx.HTTPError, ValueError, TypeError):
            if not comments:
                try:
                    for page_number in range(1, comment_pages + 1):
                        reply_data = _api_data(
                            active_client,
                            "/x/v2/reply",
                            {
                                "type": 1,
                                "oid": int(view.get("aid") or 0),
                                "pn": page_number,
                                "ps": min(20, max(1, comment_limit - len(comments))),
                                "sort": 2,
                            },
                        )
                        roots = reply_data.get("replies") if isinstance(reply_data.get("replies"), list) else []
                        _extend_unique_comments(
                            comments,
                            _bilibili_comments(roots, limit=comment_limit - len(comments)),
                            limit=comment_limit,
                        )
                        if not roots or len(comments) >= comment_limit:
                            break
                    comments_complete = len(comments) >= int(stat.get("reply") or 0)
                except (httpx.HTTPError, ValueError, TypeError):
                    comments = []
        return build_source_context(
            provider="bilibili",
            author=str(owner.get("name") or ""),
            published_at=_timestamp_text(view.get("pubdate")),
            description=" ".join(description_parts),
            topics=[str(view.get("tname") or "")],
            engagement={
                "play": stat.get("view"),
                "like": stat.get("like"),
                "comment": stat.get("reply"),
                "collect": stat.get("favorite"),
                "share": stat.get("share"),
                "danmaku": stat.get("danmaku"),
            },
            comments=comments,
            comment_total=_as_int(stat.get("reply")),
            comments_complete=comments_complete,
        )
    finally:
        if own_client:
            active_client.close()


def _api_data(client: httpx.Client, path: str, params: dict[str, object]) -> dict[str, Any]:
    response = client.get(f"https://api.bilibili.com{path}", params=params, headers=_HEADERS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        message = payload.get("message", "未知错误") if isinstance(payload, dict) else "响应格式错误"
        raise ValueError(f"B站接口请求失败: {message}")
    return payload["data"]


def _bilibili_comments(roots: Iterable[object], *, limit: int) -> list[dict[str, object]]:
    normalized = []
    for root in roots:
        if not isinstance(root, dict):
            continue
        normalized.append(_bilibili_comment(root))
        for child in root.get("replies") if isinstance(root.get("replies"), list) else []:
            if isinstance(child, dict):
                normalized.append(_bilibili_comment(child, parent_id=str(root.get("rpid") or "")))
            if len(normalized) >= limit:
                return normalized
        if len(normalized) >= limit:
            break
    return normalized


def _extend_unique_comments(
    target: list[dict[str, object]],
    values: Iterable[dict[str, object]],
    *,
    limit: int,
) -> None:
    known_ids = {str(item.get("comment_id") or "") for item in target}
    for value in values:
        comment_id = str(value.get("comment_id") or "")
        if comment_id and comment_id in known_ids:
            continue
        target.append(value)
        if comment_id:
            known_ids.add(comment_id)
        if len(target) >= limit:
            break


def _bilibili_comment(raw: dict[str, object], *, parent_id: str = "") -> dict[str, object]:
    member = raw.get("member") if isinstance(raw.get("member"), dict) else {}
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    reply_control = raw.get("reply_control") if isinstance(raw.get("reply_control"), dict) else {}
    return {
        "comment_id": raw.get("rpid"),
        "parent_id": parent_id,
        "author": member.get("uname"),
        "text": content.get("message"),
        "like_count": raw.get("like"),
        "reply_count": raw.get("rcount"),
        "created_at": _timestamp_text(raw.get("ctime")),
        "ip_location": reply_control.get("location"),
    }


def _as_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _timestamp_text(value: object) -> str:
    from datetime import datetime, timezone

    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
