"""Safe normalization for Xiaohongshu note and share-short URLs."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urljoin, urlparse

import requests

from services.network_policy import direct_requests_session


_SHORT_HOSTS = frozenset({
    "xhslink.com",
    "www.xhslink.com",
    "xhslink.cn",
    "www.xhslink.cn",
})
_NOTE_HOSTS = frozenset({"xiaohongshu.com", "www.xiaohongshu.com"})
_ALLOWED_REDIRECT_HOSTS = _SHORT_HOSTS | _NOTE_HOSTS
_MAX_REDIRECTS = 5


class XiaohongshuShareLinkError(ValueError):
    """A safe error raised while expanding a Xiaohongshu share link."""


def is_xiaohongshu_short_url(value: str) -> bool:
    return (urlparse(str(value or "").strip()).hostname or "").lower() in _SHORT_HOSTS


def _is_note_url(value: str) -> bool:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    return (
        parsed.scheme in {"http", "https"}
        and host in _NOTE_HOSTS
        and (
            path.startswith("/explore/")
            or path.startswith("/discovery/item/")
            or path.startswith("/search_result/")
        )
        and bool(path.rsplit("/", 1)[-1])
    )


def resolve_xiaohongshu_share_url(
    value: str,
    *,
    request_get: Callable[..., requests.Response] | None = None,
) -> str:
    """Expand an xhslink.com URL while allowing only Xiaohongshu redirects."""
    source_url = str(value or "").strip()
    if _is_note_url(source_url):
        return source_url
    if not is_xiaohongshu_short_url(source_url):
        raise XiaohongshuShareLinkError("不是有效的小红书笔记或分享短链接")

    session = None
    getter = request_get
    if getter is None:
        session = direct_requests_session()
        getter = session.get

    current_url = source_url
    try:
        for _ in range(_MAX_REDIRECTS):
            try:
                response = getter(
                    current_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"
                        )
                    },
                    timeout=10,
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                raise XiaohongshuShareLinkError("小红书分享短链接展开失败，请检查网络后重试") from exc

            if not 300 <= int(response.status_code) < 400:
                raise XiaohongshuShareLinkError("小红书分享短链接已失效或无法访问")
            location = str(response.headers.get("location") or "").strip()
            if not location:
                raise XiaohongshuShareLinkError("小红书分享短链接没有返回有效跳转地址")

            next_url = urljoin(current_url, location)
            parsed_next = urlparse(next_url)
            next_host = (parsed_next.hostname or "").lower()
            if parsed_next.scheme not in {"http", "https"} or next_host not in _ALLOWED_REDIRECT_HOSTS:
                raise XiaohongshuShareLinkError("小红书分享短链接跳转到了不受信任的地址")
            if _is_note_url(next_url):
                return next_url
            if next_host not in _SHORT_HOSTS:
                raise XiaohongshuShareLinkError("小红书分享短链接没有指向有效笔记")
            current_url = next_url
    finally:
        if session is not None:
            session.close()

    raise XiaohongshuShareLinkError("小红书分享短链接跳转次数过多")
