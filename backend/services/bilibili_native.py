"""Small first-party Bilibili progressive-media resolver.

This intentionally handles only the single-file progressive response exposed
by Bilibili's web player API.  High-quality DASH streams and multi-segment
responses remain the responsibility of the mature yt-dlp compatibility
adapter, rather than silently producing an incomplete video.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from services.bilibili_auth import bilibili_playwright_cookies
from services.bilibili_url import extract_bvid, requested_page_number


_API_HEADERS = {"User-Agent": "Mozilla/5.0 KnowledgeHub/1.0", "Referer": "https://www.bilibili.com/"}


@dataclass(frozen=True)
class BilibiliProgressiveMedia:
    bvid: str
    cid: int
    title: str
    url: str
    headers: dict[str, str]
    page_number: int = 1


def resolve_progressive_media(url: str, *, client: httpx.Client | None = None) -> BilibiliProgressiveMedia:
    """Resolve a single-file Bilibili stream without invoking yt-dlp.

    A clear exception is preferable to selecting the first part of a segmented
    response: the caller can then safely use the compatibility adapter.
    """
    bvid = extract_bvid(url)
    if not bvid:
        raise ValueError("无法从 B站链接中提取 BV 号")
    cookies = {str(item["name"]): str(item["value"]) for item in bilibili_playwright_cookies() if item.get("name")}
    own_client = client is None
    active_client = client or httpx.Client(
        headers=_API_HEADERS,
        cookies=cookies,
        timeout=20,
        follow_redirects=True,
        trust_env=False,
    )
    try:
        view = _api_data(active_client, "/x/web-interface/view", {"bvid": bvid})
        page_number = requested_page_number(url)
        pages = view.get("pages") if isinstance(view.get("pages"), list) else []
        if page_number > len(pages) and (page_number > 1 or pages):
            raise ValueError(f"B站视频不存在第 {page_number} 个分 P")
        page = pages[page_number - 1] if pages else {}
        cid = int(page.get("cid") or (view.get("cid") if page_number == 1 else 0) or 0)
        if not cid:
            raise ValueError("B站未返回可播放分 P")
        play = _api_data(
            active_client,
            "/x/player/playurl",
            {"bvid": bvid, "cid": cid, "qn": 80, "fnval": 0, "fnver": 0, "fourk": 1},
        )
        streams = play.get("durl") or []
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
            raise ValueError("B站当前仅提供分段或 DASH 媒体，需使用兼容下载器")
        media_url = streams[0].get("url")
        if not isinstance(media_url, str) or not media_url:
            raise ValueError("B站未返回可下载媒体地址")
        headers = dict(_API_HEADERS)
        if cookies:
            headers["Cookie"] = "; ".join(f"{name}={value}" for name, value in cookies.items())
        title = str(view.get("title") or bvid)
        part_title = str(page.get("part") or "").strip()
        if page_number > 1 and part_title:
            title = f"{title} · P{page_number} {part_title}"
        return BilibiliProgressiveMedia(
            bvid=bvid,
            cid=cid,
            title=title,
            url=media_url,
            headers=headers,
            page_number=page_number,
        )
    finally:
        if own_client:
            active_client.close()


def _api_data(client: httpx.Client, path: str, params: dict[str, object]) -> dict:
    response = client.get(f"https://api.bilibili.com{path}", params=params, headers=_API_HEADERS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        raise ValueError(f"B站接口请求失败: {(payload or {}).get('message', '未知错误')}")
    return payload["data"]
