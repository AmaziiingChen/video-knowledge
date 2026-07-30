"""Small, local Bilibili creator-list client used when page XHR is rejected.

The browser remains the preferred route because it follows Bilibili's current
web behaviour.  This module is a narrow fallback for the public WBI creator
list API; it deliberately does not introduce a third-party crawler service.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import md5
from pathlib import PurePosixPath
from time import time
from typing import Any
from urllib.parse import urlencode

import httpx

from services.bilibili_auth import bilibili_playwright_cookies


_MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"


class BilibiliCreatorApiError(ValueError):
    pass


@dataclass(frozen=True)
class BilibiliCreatorProfile:
    name: str = ""
    avatar_url: str = ""
    description: str = ""


def fetch_creator_profile_videos(*, mid: str, limit: int) -> tuple[list[dict[str, Any]], BilibiliCreatorProfile]:
    """Fetch up to ``limit`` posted videos through Bilibili's signed WBI API."""
    if not mid.isdigit():
        raise BilibiliCreatorApiError("B站创作者 ID 无效")
    cookies = {str(item["name"]): str(item["value"]) for item in bilibili_playwright_cookies() if item.get("name")}
    headers = {"User-Agent": _USER_AGENT, "Referer": f"https://space.bilibili.com/{mid}/"}
    try:
        with httpx.Client(headers=headers, cookies=cookies, timeout=12, follow_redirects=True, trust_env=False) as client:
            mixin_key = _fetch_mixin_key(client)
            profile = _fetch_profile(client, mid=mid, mixin_key=mixin_key)
            videos: list[dict[str, Any]] = []
            page_number = 1
            while len(videos) < limit:
                payload = _get_signed_json(
                    client,
                    "/x/space/wbi/arc/search",
                    {"mid": mid, "pn": page_number, "ps": min(50, limit - len(videos)), "order": "pubdate", "platform": "web"},
                    mixin_key,
                )
                data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
                listing = data.get("list") if isinstance(data.get("list"), dict) else {}
                rows = listing.get("vlist") if isinstance(listing.get("vlist"), list) else []
                videos.extend(row for row in rows if isinstance(row, dict))
                page = data.get("page") if isinstance(data.get("page"), dict) else {}
                total = _as_int(page.get("count")) or 0
                if not rows or page_number * max(1, _as_int(page.get("ps")) or len(rows)) >= total:
                    break
                page_number += 1
            return videos[:limit], profile
    except httpx.HTTPError as exc:
        raise BilibiliCreatorApiError(f"B站作品列表请求失败：{exc}") from exc


def _fetch_mixin_key(client: httpx.Client) -> str:
    response = client.get("https://api.bilibili.com/x/web-interface/nav")
    payload = _json_response(response)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    wbi_img = data.get("wbi_img") if isinstance(data.get("wbi_img"), dict) else {}
    image = PurePosixPath(str(wbi_img.get("img_url") or "")).stem
    sub = PurePosixPath(str(wbi_img.get("sub_url") or "")).stem
    source = image + sub
    if len(source) < 64:
        raise BilibiliCreatorApiError("B站未返回 WBI 签名密钥，请更新登录态后重试")
    return "".join(source[index] for index in _MIXIN_KEY_ENC_TAB)[:32]


def _fetch_profile(client: httpx.Client, *, mid: str, mixin_key: str) -> BilibiliCreatorProfile:
    try:
        payload = _get_signed_json(client, "/x/space/wbi/acc/info", {"mid": mid}, mixin_key)
    except BilibiliCreatorApiError:
        return BilibiliCreatorProfile()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return BilibiliCreatorProfile(
        name=str(data.get("name") or ""),
        avatar_url=_absolute_url(data.get("face")),
        description=str(data.get("sign") or ""),
    )


def _get_signed_json(client: httpx.Client, path: str, params: dict[str, Any], mixin_key: str) -> dict[str, Any]:
    signed = _sign_wbi_params(params, mixin_key)
    response = client.get(f"https://api.bilibili.com{path}", params=signed)
    payload = _json_response(response)
    code = _as_int(payload.get("code"))
    if response.status_code >= 400 or code not in {None, 0}:
        message = str(payload.get("message") or payload.get("msg") or response.status_code)
        raise BilibiliCreatorApiError(f"B站拒绝作品列表请求（错误码 {code if code is not None else response.status_code}）：{message}")
    return payload


def _sign_wbi_params(params: dict[str, Any], mixin_key: str) -> dict[str, str]:
    clean = {str(key): str(value).translate(str.maketrans("", "", "!'()*")) for key, value in params.items() if value is not None}
    clean["wts"] = str(int(time()))
    query = urlencode(sorted(clean.items()))
    clean["w_rid"] = md5(f"{query}{mixin_key}".encode()).hexdigest()
    return clean


def _json_response(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BilibiliCreatorApiError("B站返回了非 JSON 响应") from exc
    return payload if isinstance(payload, dict) else {}


def _absolute_url(value: Any) -> str:
    text = str(value or "")
    return f"https:{text}" if text.startswith("//") else text


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
