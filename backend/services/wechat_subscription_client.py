"""Bounded authenticated transport for the WeChat public-account admin site."""

from __future__ import annotations

import hashlib
import html
import json
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests

from services.wechat_subscription_errors import WeChatRateLimitError, WeChatRemoteError
from services.wechat_subscription_secrets import (
    SessionCredentials,
    WeChatAuthorizationError,
)


WECHAT_MP_BASE_URL = "https://mp.weixin.qq.com"
WECHAT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
WECHAT_REMOTE_CONNECT_TIMEOUT_SECONDS = 10
WECHAT_REMOTE_READ_TIMEOUT_SECONDS = 10
WECHAT_REMOTE_TOTAL_TIMEOUT_SECONDS = 35


@dataclass(frozen=True)
class WeChatAccountCandidate:
    fakeid: str
    name: str
    avatar_url: str = ""
    biz: str = ""
    description: str = ""


@dataclass(frozen=True)
class WeChatArticleCandidate:
    remote_article_id: str
    source_url: str
    title: str
    cover_url: str = ""
    published_at: str | None = None


def canonical_article_id(source_url: str) -> str:
    normalized = html.unescape(source_url or "").strip()
    query = parse_qs(urlparse(normalized).query)
    values = [query.get(key, [""])[0] for key in ("__biz", "mid", "idx", "sn")]
    if values[0] and values[1]:
        return "wechat:" + ":".join(values)
    return "wechat-url:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _is_rate_limit_response(ret: int, message: str) -> bool:
    normalized = message.lower()
    return ret == 200013 or "freq control" in normalized or "frequency" in normalized or "频" in message


def _is_authorization_response(ret: int, message: str) -> bool:
    normalized = message.lower()
    return ret in {200003, 200006, 200008} or any(
        marker in normalized
        for marker in ("login", "invalid session", "invalid token", "unauthorized", "credential")
    ) or any(marker in message for marker in ("登录", "授权", "会话失效"))


def _published_at(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    china_standard_time = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(timestamp, china_standard_time).strftime("%Y-%m-%d %H:%M")


def _normalize_article_title(value: Any) -> str:
    """Keep malformed admin payloads from storing an article excerpt as its title."""
    decoded = html.unescape(str(value or ""))
    first_line = next((line.strip() for line in decoded.splitlines() if line.strip()), "")
    title = re.sub(r"\s+", " ", first_line).strip()
    if len(title) > 120:
        title = f"{title[:119].rstrip()}…"
    return title or "未命名公众号文章"


class WeChatAdminClient:
    """Small adapter around the authenticated WeChat public-account web session."""

    def __init__(self, request_get: Callable[..., Any] = requests.get) -> None:
        self._request_get = request_get

    def _headers(self, credentials: SessionCredentials) -> dict[str, str]:
        return {"Cookie": credentials.cookie, "User-Agent": WECHAT_USER_AGENT}

    @staticmethod
    def _read_response_body(response: Any) -> bytes:
        """Read a remote response with a hard total deadline."""
        iterator = getattr(response, "iter_content", None)
        if not callable(iterator):
            return bytes(getattr(response, "content", b"") or b"")
        deadline = time.monotonic() + WECHAT_REMOTE_TOTAL_TIMEOUT_SECONDS
        chunks: list[bytes] = []
        try:
            for chunk in iterator(chunk_size=64 * 1024):
                if time.monotonic() > deadline:
                    raise requests.Timeout("微信公众平台响应超时")
                if chunk:
                    chunks.append(bytes(chunk))
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        return b"".join(chunks)

    def _request(self, path: str, credentials: SessionCredentials, params: dict[str, Any]) -> Any:
        result: dict[str, Any] = {}
        completed = Event()

        def issue_request() -> None:
            try:
                result["response"] = self._request_get(
                    f"{WECHAT_MP_BASE_URL}{path}",
                    headers=self._headers(credentials),
                    params=params,
                    timeout=(WECHAT_REMOTE_CONNECT_TIMEOUT_SECONDS, WECHAT_REMOTE_READ_TIMEOUT_SECONDS),
                    stream=True,
                )
            except BaseException as exc:  # forward the original requests error below
                result["error"] = exc
            finally:
                completed.set()

        # Some proxy/network combinations can keep the TLS handshake alive
        # with tiny packets, bypassing requests' socket-level timeout before a
        # response object even exists. This daemon worker bounds that phase as
        # well, so a timed-out socket cannot hold the shared WeChat lane forever.
        Thread(target=issue_request, name="wechat-remote-request", daemon=True).start()
        if not completed.wait(WECHAT_REMOTE_TOTAL_TIMEOUT_SECONDS):
            raise WeChatRemoteError("微信公众平台响应超时，请稍后重试")
        if "error" in result:
            raise result["error"]
        return result["response"]

    def _get_json(self, path: str, credentials: SessionCredentials, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._request(path, credentials, params)
            response.raise_for_status()
            body = self._read_response_body(response)
            payload = json.loads(body.decode("utf-8")) if body else response.json()
        except requests.RequestException as exc:
            raise WeChatRemoteError("访问微信公众平台失败，请检查网络后重试") from exc
        except (TypeError, ValueError) as exc:
            raise WeChatRemoteError("微信公众平台返回了无法解析的数据") from exc
        if not isinstance(payload, dict):
            raise WeChatRemoteError("微信公众平台返回了异常数据")
        base_response = payload.get("base_resp")
        if isinstance(base_response, dict):
            try:
                ret = int(base_response.get("ret", 0) or 0)
            except (TypeError, ValueError):
                ret = -1
            message = str(base_response.get("err_msg") or base_response.get("errmsg") or "").strip()
            if ret and _is_rate_limit_response(ret, message):
                raise WeChatRateLimitError("微信公众平台触发访问频控，已暂停自动检查")
            if ret and _is_authorization_response(ret, message):
                raise WeChatAuthorizationError("微信公众平台登录态已失效，请重新授权")
            if ret:
                raise WeChatRemoteError(f"微信公众平台请求失败（错误码 {ret}）")
        return payload

    def validate(self, credentials: SessionCredentials) -> bool:
        if not credentials.token or not credentials.cookie:
            return False
        try:
            response = self._request("/cgi-bin/home", credentials, {"token": credentials.token, "lang": "zh_CN"})
            response.raise_for_status()
            body = self._read_response_body(response)
        except (requests.RequestException, WeChatRemoteError):
            return False
        final_url = str(getattr(response, "url", ""))
        text = body.decode("utf-8", errors="replace") if body else str(getattr(response, "text", ""))
        return "login" not in final_url.lower() and "请使用微信扫码登录" not in text

    def search_accounts(
        self,
        credentials: SessionCredentials,
        query: str,
        *,
        limit: int = 10,
    ) -> list[WeChatAccountCandidate]:
        payload = self._get_json(
            "/cgi-bin/searchbiz",
            credentials,
            {
                "action": "search_biz",
                "begin": 0,
                "count": max(1, min(limit, 20)),
                "query": query.strip(),
                "token": credentials.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
        )
        page = _decode_json(payload.get("publish_page"))
        records: list[Any] = []
        if isinstance(page, dict):
            records = page.get("biz_list") or page.get("list") or []
        records = records or payload.get("list") or payload.get("biz_list") or []
        result: list[WeChatAccountCandidate] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            fakeid = str(record.get("fakeid") or record.get("id") or "").strip()
            if not fakeid:
                continue
            result.append(
                WeChatAccountCandidate(
                    fakeid=fakeid,
                    name=str(record.get("nickname") or record.get("name") or record.get("alias") or fakeid),
                    avatar_url=str(record.get("headimgurl") or record.get("round_head_img") or ""),
                    biz=str(record.get("biz") or ""),
                    description=str(record.get("signature") or record.get("intro") or ""),
                )
            )
        return result

    def list_articles(
        self,
        credentials: SessionCredentials,
        fakeid: str,
        *,
        max_pages: int = 2,
        page_size: int = 10,
        stop_when: Callable[[WeChatArticleCandidate], bool] | None = None,
        page_delay_range: tuple[float, float] | None = None,
        before_request: Callable[[], None] | None = None,
    ) -> list[WeChatArticleCandidate]:
        articles: list[WeChatArticleCandidate] = []
        seen: set[str] = set()
        for page_index in range(max(1, max_pages)):
            if page_index and page_delay_range:
                lower, upper = page_delay_range
                time.sleep(random.uniform(max(0.0, lower), max(lower, upper)))
            if before_request:
                before_request()
            payload = self._get_json(
                "/cgi-bin/appmsgpublish",
                credentials,
                {
                    "sub": "list",
                    "sub_action": "list_ex",
                    "begin": page_index * page_size,
                    "count": page_size,
                    "fakeid": fakeid,
                    "token": credentials.token,
                    "lang": "zh_CN",
                    "f": "json",
                    "ajax": "1",
                },
            )
            page = _decode_json(payload.get("publish_page"))
            if not isinstance(page, dict):
                break
            publish_list = page.get("publish_list") or []
            if not publish_list:
                break
            reached_known_article = False
            for published in publish_list:
                if not isinstance(published, dict):
                    continue
                publish_info = _decode_json(published.get("publish_info"))
                if not isinstance(publish_info, dict):
                    continue
                for item in publish_info.get("appmsgex") or []:
                    if not isinstance(item, dict):
                        continue
                    source_url = html.unescape(str(item.get("link") or "")).strip()
                    if not source_url:
                        continue
                    remote_id = canonical_article_id(source_url)
                    if remote_id in seen:
                        continue
                    seen.add(remote_id)
                    candidate = WeChatArticleCandidate(
                        remote_article_id=remote_id,
                        source_url=source_url,
                        title=_normalize_article_title(item.get("title")),
                        cover_url=str(item.get("cover") or item.get("cover_url") or "").strip(),
                        published_at=_published_at(item.get("update_time") or item.get("create_time")),
                    )
                    articles.append(candidate)
                    if stop_when and stop_when(candidate):
                        reached_known_article = True
            # Finish the current page so multi-article publications are not
            # split, then stop once the previous local boundary is reached.
            if reached_known_article or len(publish_list) < page_size:
                break
        return articles
