from __future__ import annotations

from random import uniform
from threading import Lock
from time import monotonic, sleep
from typing import Any


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
WECHAT_PUBLIC_REQUEST_INTERVAL_RANGE = (2.5, 4.0)
_WECHAT_PUBLIC_REQUEST_LOCK = Lock()
_next_wechat_public_request_at = 0.0


def fetch_wechat_page(
    url: str,
    *,
    timeout: int = 30,
    headers: dict[str, str] | None = None,
) -> Any:
    """Fetch a public WeChat page inside the application.

    ``curl_cffi`` supplies a Chrome TLS fingerprint when it is bundled with the
    desktop app. Requests remains a deliberately compatible fallback for
    development environments where that optional wheel is unavailable.
    """
    request_headers = dict(WECHAT_BROWSER_HEADERS)
    request_headers.update(headers or {})
    global _next_wechat_public_request_at
    with _WECHAT_PUBLIC_REQUEST_LOCK:
        wait_seconds = max(0.0, _next_wechat_public_request_at - monotonic())
        if wait_seconds:
            sleep(wait_seconds)
        try:
            try:
                from curl_cffi.requests import Session as CurlSession
            except ImportError:
                with direct_requests_session() as session:
                    return session.get(url, headers=request_headers, timeout=timeout)

            with CurlSession(impersonate="chrome120", trust_env=False) as session:
                return session.get(
                    url,
                    headers=request_headers,
                    timeout=timeout,
                    allow_redirects=True,
                    # curl itself still reads HTTPS_PROXY when no explicit
                    # proxy option is set, even though the wrapper receives
                    # trust_env=False. An explicit empty mapping value sends
                    # CURLOPT_PROXY="" and guarantees the local-first direct
                    # network policy used by the requests fallback.
                    proxies={"all": ""},
                )
        finally:
            _next_wechat_public_request_at = monotonic() + uniform(*WECHAT_PUBLIC_REQUEST_INTERVAL_RANGE)


def next_wechat_public_request_in_seconds() -> float:
    # This is status-only telemetry. Do not wait behind an active 30-second
    # network request just to render the desktop status bar.
    return round(max(0.0, _next_wechat_public_request_at - monotonic()), 1)
