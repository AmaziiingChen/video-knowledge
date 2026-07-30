from __future__ import annotations

from typing import Any

import requests

from services.network_policy import direct_requests_session


WECHAT_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://mp.weixin.qq.com/",
}


def fetch_wechat_page(url: str, *, timeout: int = 30) -> Any:
    """Fetch a public WeChat page inside the application.

    ``curl_cffi`` supplies a Chrome TLS fingerprint when it is bundled with the
    desktop app. Requests remains a deliberately compatible fallback for
    development environments where that optional wheel is unavailable.
    """
    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError:
        with direct_requests_session() as session:
            return session.get(url, headers=WECHAT_BROWSER_HEADERS, timeout=timeout)

    with CurlSession(impersonate="chrome120", trust_env=False) as session:
        return session.get(
            url,
            headers=WECHAT_BROWSER_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
