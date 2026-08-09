from __future__ import annotations

import base64
import hashlib
import html
import json
import random
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests
from config import settings

from services.article_ingest_preparation import enqueue_article_source_preparation
from services.content_index import ensure_wechat_subscription_folder
from services.database import connect, initialize_database, utc_now_iso
from services.inbox import capture_link_to_inbox, process_inbox_item
from services.repository import new_id
from services.wechat_initial_sync_queue import WeChatInitialSyncQueue
from services.wechat_subscription_secrets import (
    MacOSKeychainSessionStore,
    SessionCredentials,
    WeChatAuthorizationError,
    WeChatSubscriptionError,
)

WECHAT_MP_BASE_URL = "https://mp.weixin.qq.com"
WECHAT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
WECHAT_CHECK_DELAY_RANGE = (15.0, 30.0)
WECHAT_REMOTE_CONNECT_TIMEOUT_SECONDS = 10
WECHAT_REMOTE_READ_TIMEOUT_SECONDS = 10
WECHAT_REMOTE_TOTAL_TIMEOUT_SECONDS = 35
WECHAT_SESSION_VALIDATION_TTL_SECONDS = 60 * 60
WECHAT_ACCOUNT_REQUEST_WINDOW_HOURS = 24
WECHAT_ACCOUNT_REQUEST_LIMIT = 50
WECHAT_RATE_LIMIT_COOLDOWN_HOURS = 24
WECHAT_MIN_AUTOMATIC_INTERVAL_MINUTES = 6 * 60
_UNSET = object()

SUBSCRIPTION_SELECT = """
    SELECT s.*, a.display_name AS account_name, a.status AS account_status,
        a.rate_limited_until AS account_rate_limited_until,
        a.rate_limit_reason AS account_rate_limit_reason,
        (
            SELECT GROUP_CONCAT(membership.group_id, ',')
            FROM wechat_subscription_group_memberships membership
            WHERE membership.subscription_id = s.id
        ) AS group_ids_csv,
        (
            SELECT status FROM wechat_sync_runs run
            WHERE run.subscription_id = s.id
            ORDER BY run.started_at DESC
            LIMIT 1
        ) AS last_run_status,
        (
            SELECT found_count FROM wechat_sync_runs run
            WHERE run.subscription_id = s.id
            ORDER BY run.started_at DESC
            LIMIT 1
        ) AS last_run_found_count,
        (
            SELECT imported_count FROM wechat_sync_runs run
            WHERE run.subscription_id = s.id
            ORDER BY run.started_at DESC
            LIMIT 1
        ) AS last_run_imported_count,
        (
            SELECT finished_at FROM wechat_sync_runs run
            WHERE run.subscription_id = s.id
            ORDER BY run.started_at DESC
            LIMIT 1
        ) AS last_run_finished_at
    FROM wechat_subscriptions s
    JOIN wechat_accounts a ON a.id = s.account_id
"""


class WeChatRemoteError(WeChatSubscriptionError):
    category = "remote"


class WeChatRateLimitError(WeChatRemoteError):
    category = "rate_limit"

    def __init__(self, message: str, *, retry_at: str | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at


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


@dataclass(frozen=True)
class QrLoginStatus:
    login_id: str
    status: str
    message: str
    qr_image_data_url: str | None = None
    credentials: SessionCredentials | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_after(minutes: int) -> str:
    return (_utc_now() + timedelta(minutes=max(1, minutes))).isoformat()


def _retry_delay_minutes(category: str, failure_count: int) -> int:
    """Back off transient collection failures without delaying a manual recovery."""
    if category == "authorization":
        return 6 * 60
    if category == "rate_limit":
        return WECHAT_RATE_LIMIT_COOLDOWN_HOURS * 60
    exponent = min(max(failure_count - 1, 0), 4)
    return min(6 * 60, 15 * (2 ** exponent))


def _decode_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _parse_iso_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_rate_limit_response(ret: int, message: str) -> bool:
    normalized = message.lower()
    return ret == 200013 or "freq control" in normalized or "frequency" in normalized or "频" in message


def _is_authorization_response(ret: int, message: str) -> bool:
    normalized = message.lower()
    return ret in {200003, 200006, 200008} or any(
        marker in normalized
        for marker in ("login", "invalid session", "invalid token", "unauthorized", "credential")
    ) or any(marker in message for marker in ("登录", "授权", "会话失效"))


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def _extract_token(*values: str) -> str:
    for value in values:
        match = re.search(r"(?:[?&]|^)token=(\d+)", value or "")
        if match:
            return match.group(1)
    return ""


def canonical_article_id(source_url: str) -> str:
    normalized = html.unescape(source_url or "").strip()
    query = parse_qs(urlparse(normalized).query)
    values = [query.get(key, [""])[0] for key in ("__biz", "mid", "idx", "sn")]
    if values[0] and values[1]:
        return "wechat:" + ":".join(values)
    return "wechat-url:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _published_at(value: Any) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    china_standard_time = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(timestamp, china_standard_time).strftime("%Y-%m-%d %H:%M")


class WeChatAdminClient:
    """Small adapter around the authenticated WeChat public-account web session."""

    def __init__(self, request_get: Callable[..., Any] = requests.get) -> None:
        self._request_get = request_get

    def _headers(self, credentials: SessionCredentials) -> dict[str, str]:
        return {"Cookie": credentials.cookie, "User-Agent": WECHAT_USER_AGENT}

    @staticmethod
    def _read_response_body(response: Any) -> bytes:
        """Read a remote response with a hard total deadline.

        ``requests`` resets its read timeout whenever a peer sends another
        small packet.  A stalled WeChat endpoint can therefore keep a sync
        marked as running indefinitely.  Streaming the body lets us retain a
        normal socket timeout while also enforcing a real wall-clock limit.
        """
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
        # response object even exists.  This daemon worker makes that phase
        # bounded as well; a timed-out socket can no longer hold the sync run
        # or its shared WeChat lane forever.
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


@dataclass
class _PendingQrLogin:
    session: requests.Session
    qr_image_data_url: str


def _normalize_article_title(value: Any) -> str:
    """Keep malformed admin payloads from storing an article excerpt as its title."""
    decoded = html.unescape(str(value or ""))
    first_line = next((line.strip() for line in decoded.splitlines() if line.strip()), "")
    title = re.sub(r"\s+", " ", first_line).strip()
    if len(title) > 120:
        title = f"{title[:119].rstrip()}…"
    return title or "未命名公众号文章"


class WeChatQrAuthService:
    """Authorize through the QR endpoints used by the current public-platform login page."""

    def __init__(self, session_factory: Callable[[], requests.Session] = requests.Session) -> None:
        self._session_factory = session_factory
        self._pending: dict[str, _PendingQrLogin] = {}
        self._lock = Lock()

    def start(self) -> QrLoginStatus:
        session = self._session_factory()
        session.headers.update({"User-Agent": WECHAT_USER_AGENT, "Referer": f"{WECHAT_MP_BASE_URL}/"})
        try:
            page = session.get(f"{WECHAT_MP_BASE_URL}/", timeout=20)
            page.raise_for_status()
        except requests.RequestException as exc:
            raise WeChatRemoteError("无法打开微信公众平台登录页") from exc
        session_id = f"{int(_utc_now().timestamp() * 1000)}{new_id()[:6]}"
        try:
            start_response = session.post(
                f"{WECHAT_MP_BASE_URL}/cgi-bin/bizlogin",
                params={"action": "startlogin"},
                data={
                    "userlang": "zh_CN",
                    "redirect_url": "",
                    "login_type": 3,
                    "sessionid": session_id,
                },
                timeout=20,
            )
            start_response.raise_for_status()
            start_payload = start_response.json()
            base_response = start_payload.get("base_resp") if isinstance(start_payload, dict) else None
            if not isinstance(base_response, dict) or int(base_response.get("ret", -1)) != 0:
                raise WeChatRemoteError("微信公众平台暂时无法创建扫码登录会话，请稍后重试")
            image = session.get(
                f"{WECHAT_MP_BASE_URL}/cgi-bin/scanloginqrcode",
                params={"action": "getqrcode", "random": session_id, "login_appid": ""},
                timeout=20,
            )
            image.raise_for_status()
        except requests.RequestException as exc:
            raise WeChatRemoteError("获取微信公众平台二维码失败，请检查网络后重试") from exc
        except (TypeError, ValueError) as exc:
            raise WeChatRemoteError("微信公众平台创建扫码登录会话失败，请稍后重试") from exc
        if not image.content:
            raise WeChatRemoteError("微信公众平台返回了空二维码，请重新发起扫码授权")
        login_id = new_id()
        data_url = "data:image/png;base64," + base64.b64encode(image.content).decode("ascii")
        with self._lock:
            self._pending[login_id] = _PendingQrLogin(session, data_url)
        return QrLoginStatus(login_id, "pending", "请使用微信扫描二维码并在手机确认", data_url)

    def poll(self, login_id: str) -> QrLoginStatus:
        with self._lock:
            pending = self._pending.get(login_id)
        if not pending:
            raise WeChatAuthorizationError("二维码登录会话已过期，请重新发起授权")
        try:
            response = pending.session.get(
                f"{WECHAT_MP_BASE_URL}/cgi-bin/scanloginqrcode",
                params={"action": "ask"},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise WeChatRemoteError("查询微信扫码状态失败") from exc
        except ValueError as exc:
            raise WeChatRemoteError("微信扫码状态返回异常") from exc
        if not isinstance(payload, dict):
            raise WeChatRemoteError("微信扫码状态返回异常")
        base_response = payload.get("base_resp")
        try:
            if isinstance(base_response, dict) and int(base_response.get("ret", 0) or 0) != 0:
                raise WeChatRemoteError("微信公众平台无法读取扫码状态，请重新发起授权")
            status_code = int(payload.get("status", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise WeChatRemoteError("微信扫码状态返回异常") from exc
        if status_code in {4, 6}:
            return QrLoginStatus(login_id, "scanned", "已扫码，请在手机确认", pending.qr_image_data_url)
        if status_code in {2, 3}:
            with self._lock:
                self._pending.pop(login_id, None)
            return QrLoginStatus(login_id, "expired", "二维码已失效，请重新点击扫码连接")
        if status_code == 5:
            with self._lock:
                self._pending.pop(login_id, None)
            return QrLoginStatus(login_id, "failed", "微信登录未完成，请重新点击扫码连接")
        if status_code != 1:
            return QrLoginStatus(login_id, "pending", "等待扫码", pending.qr_image_data_url)

        try:
            login_response = pending.session.post(
                f"{WECHAT_MP_BASE_URL}/cgi-bin/bizlogin",
                params={"action": "login"},
                data={
                    "userlang": "zh_CN",
                    "redirect_url": "",
                    "cookie_forbidden": 0,
                    "cookie_cleaned": 0,
                    "plugin_used": 0,
                    "login_type": 3,
                },
                timeout=20,
            )
            login_response.raise_for_status()
            login_payload = login_response.json()
        except requests.RequestException as exc:
            raise WeChatRemoteError("完成微信扫码登录失败，请重新发起授权") from exc
        except (TypeError, ValueError) as exc:
            raise WeChatRemoteError("微信扫码登录返回异常，请重新发起授权") from exc
        if not isinstance(login_payload, dict):
            raise WeChatRemoteError("微信扫码登录返回异常，请重新发起授权")
        cookies = pending.session.cookies.get_dict()
        token = _extract_token(str(login_payload.get("redirect_url") or ""))
        with self._lock:
            self._pending.pop(login_id, None)
        if not token or not cookies:
            raise WeChatAuthorizationError("扫码已确认，但未取得可用登录态；请使用手动授权")
        return QrLoginStatus(
            login_id,
            "confirmed",
            "微信授权成功",
            credentials=SessionCredentials(token=token, cookie=_cookie_header(cookies)),
        )


class WeChatSubscriptionService:
    def __init__(
        self,
        *,
        session_store: Any | None = None,
        admin_client: WeChatAdminClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_store = session_store or MacOSKeychainSessionStore()
        self._admin_client = admin_client or WeChatAdminClient()
        self._monotonic = monotonic
        self._validated_until: dict[str, float] = {}
        self._syncing: set[str] = set()
        self._sync_lock = Lock()
        # All background and manual collectors share one authenticated WeChat
        # session lane. This prevents the scheduler, first-sync workers and a
        # bulk update from producing concurrent platform requests.
        self._remote_sync_lock = Lock()

    def connect_account(self, *, display_name: str, token: str, cookie: str) -> dict[str, Any]:
        credentials = SessionCredentials(token=token.strip(), cookie=cookie.strip())
        if not credentials.token or not credentials.cookie:
            raise WeChatAuthorizationError("需要同时提供微信公众平台 token 与 Cookie")
        if not self._admin_client.validate(credentials):
            raise WeChatAuthorizationError("微信公众平台登录态不可用，请重新授权")
        initialize_database()
        account_id = new_id()
        keychain_ref = f"wechat-subscription:{account_id}"
        self._session_store.save(keychain_ref, credentials)
        now = utc_now_iso()
        try:
            with connect() as connection:
                connection.execute(
                    """
                    INSERT INTO wechat_accounts (
                        id, display_name, keychain_ref, status, last_validated_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (account_id, display_name.strip() or "微信公众平台账号", keychain_ref, now, now, now),
                )
                connection.commit()
        except Exception:
            self._session_store.delete(keychain_ref)
            raise
        self._validated_until[account_id] = self._monotonic() + WECHAT_SESSION_VALIDATION_TTL_SECONDS
        return self.get_account(account_id)

    def complete_qr_login(self, status: QrLoginStatus, display_name: str = "") -> dict[str, Any]:
        if status.status != "confirmed" or not status.credentials:
            raise WeChatAuthorizationError("微信扫码授权尚未完成")
        return self.connect_account(
            display_name=display_name or "微信公众平台账号",
            token=status.credentials.token,
            cookie=status.credentials.cookie,
        )

    def reauthorize_account(self, account_id: str, *, token: str, cookie: str) -> dict[str, Any]:
        """Replace an existing account's local login state without touching subscriptions."""
        credentials = SessionCredentials(token=token.strip(), cookie=cookie.strip())
        if not credentials.token or not credentials.cookie:
            raise WeChatAuthorizationError("需要同时提供微信公众平台 token 与 Cookie")
        if not self._admin_client.validate(credentials):
            raise WeChatAuthorizationError("微信公众平台登录态不可用，请重新授权")
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT keychain_ref FROM wechat_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if not row:
                raise LookupError("微信授权账号不存在")
            keychain_ref = str(row["keychain_ref"])
        self._session_store.save(keychain_ref, credentials)
        self._mark_account_valid(account_id)
        self._validated_until[account_id] = self._monotonic() + WECHAT_SESSION_VALIDATION_TTL_SECONDS
        return self.get_account(account_id)

    def complete_qr_reauthorization(self, account_id: str, status: QrLoginStatus) -> dict[str, Any]:
        if status.status != "confirmed" or not status.credentials:
            raise WeChatAuthorizationError("微信扫码授权尚未完成")
        return self.reauthorize_account(
            account_id,
            token=status.credentials.token,
            cookie=status.credentials.cookie,
        )

    def list_accounts(self) -> list[dict[str, Any]]:
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT a.id, a.display_name, a.status, a.last_validated_at, a.reauth_required_at,
                       a.rate_limited_until, a.rate_limit_reason, a.last_rate_limited_at,
                       a.created_at, a.updated_at, COUNT(s.id) AS subscription_count
                FROM wechat_accounts a
                LEFT JOIN wechat_subscriptions s ON s.account_id = a.id
                GROUP BY a.id
                ORDER BY a.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_account(self, account_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """
                SELECT id, display_name, status, last_validated_at, reauth_required_at,
                       rate_limited_until, rate_limit_reason, last_rate_limited_at,
                       created_at, updated_at
                FROM wechat_accounts WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
        if not row:
            raise LookupError("微信授权账号不存在")
        return dict(row)

    def delete_account(self, account_id: str) -> None:
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT keychain_ref FROM wechat_accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise LookupError("微信授权账号不存在")
            subscription_count = int(connection.execute(
                "SELECT COUNT(*) FROM wechat_subscriptions WHERE account_id = ?",
                (account_id,),
            ).fetchone()[0])
            if subscription_count:
                raise ValueError(
                    f"该授权账号仍关联 {subscription_count} 个公众号订阅，请先重新授权或迁移订阅后再移除"
                )
            keychain_ref = str(row["keychain_ref"])
            connection.execute("DELETE FROM wechat_accounts WHERE id = ?", (account_id,))
            connection.commit()
        self._session_store.delete(keychain_ref)

    def transfer_subscriptions(self, source_account_id: str, target_account_id: str) -> dict[str, Any]:
        """Move subscriptions, their groups and history mappings to another valid authorization."""
        if source_account_id == target_account_id:
            raise ValueError("请选择另一个授权账号接管订阅")
        initialize_database()
        now = utc_now_iso()
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                "SELECT display_name FROM wechat_accounts WHERE id = ?",
                (source_account_id,),
            ).fetchone()
            target = connection.execute(
                "SELECT display_name, status FROM wechat_accounts WHERE id = ?",
                (target_account_id,),
            ).fetchone()
            if not source or not target:
                raise LookupError("微信授权账号不存在")
            if str(target["status"]) != "active":
                raise ValueError("接管订阅的授权账号需要处于有效状态")
            duplicates = connection.execute(
                """
                SELECT source.mp_name
                FROM wechat_subscriptions AS source
                JOIN wechat_subscriptions AS target
                  ON target.account_id = ? AND target.fakeid = source.fakeid
                WHERE source.account_id = ?
                ORDER BY source.mp_name
                """,
                (target_account_id, source_account_id),
            ).fetchall()
            if duplicates:
                names = "、".join(str(row["mp_name"]) for row in duplicates[:3])
                suffix = "等" if len(duplicates) > 3 else ""
                raise ValueError(f"目标账号已订阅 {names}{suffix}，请先取消重复订阅后再迁移")
            moved_count = connection.execute(
                """
                UPDATE wechat_subscriptions
                SET account_id = ?, last_error = NULL, updated_at = ?
                WHERE account_id = ?
                """,
                (target_account_id, now, source_account_id),
            ).rowcount
            connection.commit()
        return {
            "source_account_id": source_account_id,
            "target_account_id": target_account_id,
            "moved_count": int(moved_count),
        }

    def search_accounts(self, account_id: str, query: str, limit: int = 10) -> list[WeChatAccountCandidate]:
        if not query.strip():
            return []
        with self._remote_sync_lock:
            self._raise_if_account_rate_limited(account_id)
            credentials = self._credentials_for_account(account_id)
            self._ensure_account_session(account_id, credentials)
            try:
                self._consume_account_request_budget(account_id)
                results = self._admin_client.search_accounts(credentials, query, limit=limit)
            except WeChatRateLimitError as exc:
                self._mark_account_rate_limited(account_id, exc)
                raise
            except WeChatAuthorizationError:
                self._mark_account_reauth(account_id)
                raise
            self._clear_account_rate_limit(account_id)
        return results

    def create_subscription(
        self,
        *,
        account_id: str,
        fakeid: str,
        mp_name: str,
        biz: str = "",
        avatar_url: str = "",
        description: str = "",
        sync_interval_minutes: int | None = None,
        group_id: str | None = None,
        auto_process: bool = False,
        notify_on_new: bool = False,
    ) -> dict[str, Any]:
        self.get_account(account_id)
        clean_fakeid = fakeid.strip()
        if not clean_fakeid:
            raise ValueError("公众号标识不能为空")
        interval = sync_interval_minutes or settings.wechat_subscription_default_interval_minutes
        interval = max(WECHAT_MIN_AUTOMATIC_INTERVAL_MINUTES, min(int(interval), 24 * 60))
        now = utc_now_iso()
        next_sync_at = (_utc_now() + timedelta(minutes=interval)).isoformat()
        subscription_id = new_id()
        try:
            with connect() as connection:
                connection.execute(
                    """
                    INSERT INTO wechat_subscriptions (
                        id, account_id, fakeid, biz, mp_name, avatar_url, mp_description, enabled, auto_process, notify_on_new,
                        sync_interval_minutes, next_sync_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        subscription_id,
                        account_id,
                        clean_fakeid,
                        biz.strip() or None,
                        mp_name.strip() or clean_fakeid,
                        avatar_url.strip() or None,
                        description.strip(),
                        int(auto_process),
                        int(notify_on_new),
                        interval,
                        next_sync_at,
                        now,
                        now,
                    ),
                )
                # The library should reflect a new subscription immediately,
                # even when its first remote check has not found an article yet.
                ensure_wechat_subscription_folder(
                    connection,
                    mp_name.strip() or clean_fakeid,
                    subscription_id=subscription_id,
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("该微信公众号已经订阅") from exc
        return self.get_subscription(subscription_id)

    def list_subscriptions(self, account_id: str | None = None) -> list[dict[str, Any]]:
        initialize_database()
        with connect() as connection:
            query = SUBSCRIPTION_SELECT
            parameters: tuple[Any, ...] = ()
            if account_id:
                query += " WHERE s.account_id = ?"
                parameters = (account_id,)
            query += " ORDER BY s.created_at DESC"
            rows = connection.execute(query, parameters).fetchall()
        return [_subscription_row(row) for row in rows]

    def get_subscription(self, subscription_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                SUBSCRIPTION_SELECT + " WHERE s.id = ?",
                (subscription_id,),
            ).fetchone()
        if not row:
            raise LookupError("公众号订阅不存在")
        return _subscription_row(row)

    def update_subscription(
        self,
        subscription_id: str,
        *,
        enabled: bool | None = None,
        auto_process: bool | None = None,
        notify_on_new: bool | None = None,
        sync_interval_minutes: int | None = None,
        group_id: str | None | object = _UNSET,
        group_ids: list[str] | object = _UNSET,
    ) -> dict[str, Any]:
        current = self.get_subscription(subscription_id)
        was_enabled = bool(current["enabled"])
        next_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        next_auto_process = bool(current["auto_process"]) if auto_process is None else bool(auto_process)
        next_notify_on_new = bool(current.get("notify_on_new")) if notify_on_new is None else bool(notify_on_new)
        interval = current["sync_interval_minutes"] if sync_interval_minutes is None else sync_interval_minutes
        interval = max(WECHAT_MIN_AUTOMATIC_INTERVAL_MINUTES, min(int(interval), 24 * 60))
        next_sync_at = current["next_sync_at"]
        if next_enabled and not was_enabled:
            next_sync_at = utc_now_iso()
        elif next_enabled and sync_interval_minutes is not None:
            next_sync_at = _iso_after(interval)
        elif next_enabled and not next_sync_at:
            next_sync_at = utc_now_iso()
        with connect() as connection:
            requested_group_ids = group_ids
            if requested_group_ids is _UNSET and group_id is not _UNSET:
                requested_group_ids = [group_id] if group_id else []
            normalized_group_ids: list[str] | None = None
            if requested_group_ids is not _UNSET:
                normalized_group_ids = list(dict.fromkeys(str(value).strip() for value in requested_group_ids if str(value).strip()))
                if len(normalized_group_ids) > 3:
                    raise ValueError("一个公众号最多加入 3 个分组")
                if normalized_group_ids:
                    placeholders = ",".join("?" for _ in normalized_group_ids)
                    count = connection.execute(
                        f"SELECT COUNT(*) FROM wechat_subscription_groups WHERE id IN ({placeholders})",
                        tuple(normalized_group_ids),
                    ).fetchone()[0]
                    if count != len(normalized_group_ids):
                        raise ValueError("公众号分组不存在")
            connection.execute(
                """
                UPDATE wechat_subscriptions
                SET enabled = ?, auto_process = ?, notify_on_new = ?, sync_interval_minutes = ?, group_id = ?, next_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(next_enabled), int(next_auto_process), int(next_notify_on_new), interval, (normalized_group_ids or [None])[0] if normalized_group_ids is not None else current.get("group_id"), next_sync_at, utc_now_iso(), subscription_id),
            )
            if normalized_group_ids is not None:
                connection.execute("DELETE FROM wechat_subscription_group_memberships WHERE subscription_id = ?", (subscription_id,))
                now = utc_now_iso()
                connection.executemany(
                    "INSERT INTO wechat_subscription_group_memberships (subscription_id, group_id, created_at) VALUES (?, ?, ?)",
                    [(subscription_id, value, now) for value in normalized_group_ids],
                )
            connection.commit()
        return self.get_subscription(subscription_id)

    def refresh_subscription_profile(self, subscription_id: str) -> dict[str, Any]:
        """Refresh one source's public profile without bulk-searching subscriptions."""
        subscription = self.get_subscription(subscription_id)
        candidates = self.search_accounts(
            str(subscription["account_id"]),
            str(subscription["mp_name"]),
            limit=20,
        )
        candidate = next(
            (item for item in candidates if item.fakeid == subscription["fakeid"]),
            None,
        )
        if not candidate:
            raise WeChatSubscriptionError("未找到该公众号的最新资料，请稍后重试")
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_subscriptions
                SET mp_name = ?, biz = ?, avatar_url = ?, mp_description = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    candidate.name.strip() or subscription["mp_name"],
                    candidate.biz.strip() or subscription.get("biz"),
                    candidate.avatar_url.strip() or subscription.get("avatar_url"),
                    candidate.description.strip(),
                    utc_now_iso(),
                    subscription_id,
                ),
            )
            connection.commit()
        return self.get_subscription(subscription_id)

    def delete_subscription(self, subscription_id: str) -> None:
        initialize_database()
        with connect() as connection:
            cursor = connection.execute("DELETE FROM wechat_subscriptions WHERE id = ?", (subscription_id,))
            connection.commit()
        if cursor.rowcount == 0:
            raise LookupError("公众号订阅不存在")

    def list_sync_runs(self, subscription_id: str, limit: int = 30) -> list[dict[str, Any]]:
        self.get_subscription(subscription_id)
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM wechat_sync_runs
                WHERE subscription_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (subscription_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def sync_subscription(
        self,
        subscription_id: str,
        *,
        max_items: int | None = None,
        mode: str = "latest",
        published_after: date | None = None,
        published_before: date | None = None,
        force: bool = False,
        on_progress: Callable[[dict[str, int]], None] | None = None,
    ) -> dict[str, Any]:
        self.get_subscription(subscription_id)
        with self._sync_lock:
            if subscription_id in self._syncing:
                raise WeChatSubscriptionError("该公众号正在同步，请稍后刷新")
            self._syncing.add(subscription_id)
        run_id = self._create_sync_run(subscription_id)
        found_count = 0
        eligible_count = 0
        imported_count = 0
        queued_for_analysis = 0
        try:
            subscription = self.get_subscription(subscription_id)
            if not subscription["enabled"] and not force:
                raise WeChatSubscriptionError("该公众号订阅已暂停")
            effective_max_items = max_items
            articles, requested_limit, known_article_ids = self._fetch_articles_for_sync(
                subscription,
                subscription_id=subscription_id,
                mode=mode,
                max_items=effective_max_items,
            )
            # The first subscription check deliberately imports only the ten
            # newest *articles*.  A single WeChat list card may contain a
            # multi-article publication, so limiting it to one list page alone
            # is not sufficient to uphold that user-facing limit.
            is_initial_latest_check = mode == "latest" and not known_article_ids
            if is_initial_latest_check:
                articles = articles[:10]
            found_count = len(articles)
            history_boundary_found = bool(known_article_ids.intersection(article.remote_article_id for article in articles))
            articles = self._filter_articles_by_date(articles, published_after, published_before)
            eligible_count = len(articles)
            limit = None if mode in {"date_range", "all", "catch_up", "latest"} else effective_max_items
            selected_articles = articles if limit is None else articles[: max(0, limit)]
            self._notify_sync_progress(
                on_progress,
                found_count=found_count,
                eligible_count=eligible_count,
                imported_count=imported_count,
            )
            for article in selected_articles:
                if self._article_is_known(subscription_id, article.remote_article_id):
                    continue
                created = self._capture_article(subscription, article)
                if created:
                    imported_count += 1
                    self._update_sync_run_progress(run_id, found_count, imported_count)
                    self._notify_sync_progress(
                        on_progress,
                        found_count=found_count,
                        eligible_count=eligible_count,
                        imported_count=imported_count,
                    )
                    if subscription["auto_process"]:
                        queued_for_analysis += 1
            self._finish_sync_run(run_id, "succeeded", found_count, imported_count)
            self._mark_sync_success(subscription_id, int(subscription["sync_interval_minutes"]))
            return {
                "run_id": run_id,
                "status": "succeeded",
                "found_count": found_count,
                "eligible_count": eligible_count,
                "imported_count": imported_count,
                "queued_for_analysis": queued_for_analysis,
                "mode": mode,
                "history_boundary_found": history_boundary_found,
                "coverage_complete": (
                    (mode not in {"latest", "catch_up"})
                    or not known_article_ids
                    or history_boundary_found
                    or found_count < requested_limit
                ),
            }
        except WeChatSubscriptionError as exc:
            self._finish_sync_run(run_id, "failed", found_count, imported_count, exc.category, str(exc))
            self._mark_sync_failure(subscription_id, str(exc), exc.category)
            raise
        except Exception as exc:
            self._finish_sync_run(run_id, "failed", found_count, imported_count, "unexpected", str(exc))
            self._mark_sync_failure(subscription_id, "公众号同步失败，请稍后重试", "unexpected")
            raise WeChatSubscriptionError("公众号同步失败，请稍后重试") from exc
        finally:
            with self._sync_lock:
                self._syncing.discard(subscription_id)

    @staticmethod
    def _notify_sync_progress(
        callback: Callable[[dict[str, int]], None] | None,
        **progress: int,
    ) -> None:
        """Progress reporting is UI-only and must never interrupt a capture."""
        if callback is None:
            return
        try:
            callback(progress)
        except Exception:
            pass

    def expire_running_sync(self, subscription_id: str, message: str) -> None:
        """Expose an unresponsive in-process sync as a recoverable failure."""
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM wechat_sync_runs
                WHERE subscription_id = ? AND status = 'running'
                ORDER BY started_at DESC LIMIT 1
                """,
                (subscription_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """
                UPDATE wechat_sync_runs
                SET status = 'failed', finished_at = ?, error_category = 'timeout', error_message = ?
                WHERE id = ? AND status = 'running'
                """,
                (utc_now_iso(), message, row["id"]),
            )
            connection.commit()
        self._mark_sync_failure(subscription_id, message, "remote")

    def _fetch_articles_for_sync(
        self,
        subscription: dict[str, Any],
        *,
        subscription_id: str,
        mode: str,
        max_items: int | None,
    ) -> tuple[list[WeChatArticleCandidate], int, set[str]]:
        """Fetch through the single shared WeChat request lane."""
        requested_limit = max_items if max_items is not None else 10
        page_size = 10
        known_article_ids = self._known_article_ids(subscription_id) if mode in {"latest", "catch_up"} else set()
        # A newly subscribed account has no local boundary.  It must therefore
        # use the requested first-check window (normally ten articles), not
        # walk up to one hundred remote pages looking for a boundary that does
        # not exist.  Later incremental checks still read back to the first
        # known article so a missed publishing interval can be recovered.
        if mode == "latest":
            # Automatic checks stay on the newest page. If the local boundary
            # is not present, the result is marked incomplete and the explicit
            # catch-up flow can recover history without silently multiplying
            # background requests.
            max_pages = 1
        elif mode in {"all", "date_range", "catch_up"}:
            max_pages = 100
        else:
            max_pages = min(100, max(1, (max(1, requested_limit) + page_size - 1) // page_size))
        list_options: dict[str, Any] = {"max_pages": max_pages, "page_size": page_size}
        if mode in {"latest", "catch_up"}:
            list_options.update(
                stop_when=(lambda article: article.remote_article_id in known_article_ids) if known_article_ids else None,
                page_delay_range=(0.7, 1.4),
            )

        account_id = str(subscription["account_id"])
        with self._remote_sync_lock:
            self._raise_if_account_rate_limited(account_id)
            credentials = self._credentials_for_account(account_id)
            self._ensure_account_session(account_id, credentials)
            try:
                articles = self._admin_client.list_articles(
                    credentials,
                    str(subscription["fakeid"]),
                    before_request=lambda: self._consume_account_request_budget(account_id),
                    **list_options,
                )
            except WeChatRateLimitError as exc:
                self._mark_account_rate_limited(account_id, exc)
                raise
            except WeChatAuthorizationError:
                # The preliminary validation can still pass shortly before the
                # actual list request. Keep the account status truthful in that
                # case so the UI offers reauthorization straight away.
                self._mark_account_reauth(account_id)
                raise
            self._clear_account_rate_limit(account_id)
        return articles, requested_limit, known_article_ids

    def recover_interrupted_initial_syncs(self) -> list[str]:
        """Mark abandoned first checks and return subscriptions safe to resume.

        First-check workers are process-local.  If the desktop app exits while
        one is in flight, its database run must not remain ``running`` forever.
        Only subscriptions that have never completed a successful check are
        returned, so a restart never re-imports ordinary incremental work.
        """
        initialize_database()
        now = utc_now_iso()
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT run.subscription_id
                FROM wechat_sync_runs AS run
                JOIN wechat_subscriptions AS subscription ON subscription.id = run.subscription_id
                WHERE run.status = 'running'
                  AND subscription.last_sync_at IS NULL
                  AND subscription.enabled = 1
                """
            ).fetchall()
            if not rows:
                return []
            subscription_ids = [str(row["subscription_id"]) for row in rows]
            placeholders = ", ".join("?" for _ in subscription_ids)
            recovery_message = "应用在首次检查中退出，已在本次启动后重新检查"
            connection.execute(
                """
                UPDATE wechat_sync_runs
                SET status = 'failed', finished_at = ?,
                    error_category = 'interrupted',
                    error_message = '应用在首次检查中退出，已在本次启动后重新检查'
                WHERE status = 'running'
                  AND subscription_id IN (
                      SELECT id FROM wechat_subscriptions
                      WHERE last_sync_at IS NULL AND enabled = 1
                  )
                """,
                (now,),
            )
            connection.execute(
                f"""
                UPDATE wechat_subscriptions
                SET last_error = ?, last_error_category = 'interrupted',
                    next_sync_at = ?, updated_at = ?
                WHERE id IN ({placeholders})
                """,
                (recovery_message, _iso_after(15), now, *subscription_ids),
            )
            connection.commit()
        return subscription_ids

    @staticmethod
    def _filter_articles_by_date(
        articles: list[WeChatArticleCandidate],
        published_after: date | None,
        published_before: date | None,
    ) -> list[WeChatArticleCandidate]:
        if not published_after and not published_before:
            return articles
        filtered: list[WeChatArticleCandidate] = []
        for article in articles:
            if not article.published_at:
                continue
            try:
                published = datetime.fromisoformat(article.published_at).date()
            except ValueError:
                continue
            if published_after and published < published_after:
                continue
            if published_before and published > published_before:
                continue
            filtered.append(article)
        return filtered

    def sync_due_subscriptions(self) -> list[dict[str, Any]]:
        initialize_database()
        now = utc_now_iso()
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT subscription.id, subscription.account_id
                FROM wechat_subscriptions AS subscription
                JOIN wechat_accounts AS account ON account.id = subscription.account_id
                WHERE subscription.enabled = 1
                  AND (subscription.next_sync_at IS NULL OR subscription.next_sync_at <= ?)
                  AND (
                    account.rate_limited_until IS NULL
                    OR account.rate_limited_until <= ?
                  )
                ORDER BY subscription.next_sync_at ASC, subscription.created_at ASC
                """,
                (now, now),
            ).fetchall()
        # Due checks use the same durable task manager as manual checks. The
        # scheduler may wake again while a remote call is active; the manager
        # coalesces the identical queued/running source task.
        from services.task_manager import task_manager

        queued: list[dict[str, Any]] = []
        queued_accounts: set[str] = set()
        for row in rows:
            account_id = str(row["account_id"])
            # Probe at most one due subscription per account on each scheduler
            # pass. The remaining sources stay due and are picked up gradually
            # instead of becoming one remote burst.
            if account_id in queued_accounts:
                continue
            queued_accounts.add(account_id)
            subscription = self.get_subscription(str(row["id"]))
            task = task_manager.create_source_sync(
                {
                    "kind": "wechat_subscription",
                    "subscription_id": subscription["id"],
                    "mode": "latest",
                    "max_items": settings.wechat_subscription_default_initial_limit,
                },
                source_title=f"自动检查：{subscription['mp_name']}",
                execution_mode="background",
            )
            queued.append({"subscription_id": subscription["id"], "task_id": task.task_id, "status": task.status})
        return queued

    def _credentials_for_account(self, account_id: str) -> SessionCredentials:
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT keychain_ref FROM wechat_accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            raise LookupError("微信授权账号不存在")
        try:
            return self._session_store.load(str(row["keychain_ref"]))
        except WeChatAuthorizationError:
            self._mark_account_reauth(account_id)
            raise

    def _ensure_account_session(
        self,
        account_id: str,
        credentials: SessionCredentials,
        *,
        force: bool = False,
    ) -> None:
        if not force and self._validated_until.get(account_id, 0.0) > self._monotonic():
            return
        if not self._admin_client.validate(credentials):
            self._validated_until.pop(account_id, None)
            self._mark_account_reauth(account_id)
            raise WeChatAuthorizationError("微信公众平台登录态已失效，请重新授权")
        self._validated_until[account_id] = self._monotonic() + WECHAT_SESSION_VALIDATION_TTL_SECONDS
        self._mark_account_valid(account_id)

    def _raise_if_account_rate_limited(self, account_id: str) -> None:
        with connect() as connection:
            row = connection.execute(
                "SELECT rate_limited_until, rate_limit_reason FROM wechat_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if not row:
            raise LookupError("微信授权账号不存在")
        retry_at = _parse_iso_datetime(row["rate_limited_until"])
        if retry_at and retry_at > _utc_now():
            raise WeChatRateLimitError(
                str(row["rate_limit_reason"] or "微信公众平台正在频控冷却，暂不继续请求"),
                retry_at=retry_at.isoformat(),
            )

    def _consume_account_request_budget(self, account_id: str) -> None:
        now = _utc_now()
        window_duration = timedelta(hours=WECHAT_ACCOUNT_REQUEST_WINDOW_HOURS)
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_window_started_at, request_count
                FROM wechat_accounts WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
            if not row:
                raise LookupError("微信授权账号不存在")
            window_started_at = _parse_iso_datetime(row["request_window_started_at"])
            request_count = int(row["request_count"] or 0)
            if window_started_at is None or now - window_started_at >= window_duration:
                window_started_at = now
                request_count = 0
            if request_count >= WECHAT_ACCOUNT_REQUEST_LIMIT:
                retry_at = window_started_at + window_duration
                raise WeChatRateLimitError(
                    "微信公众号自动检查已达到本机安全调用预算，稍后自动恢复",
                    retry_at=retry_at.isoformat(),
                )
            connection.execute(
                """
                UPDATE wechat_accounts
                SET request_window_started_at = ?, request_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (window_started_at.isoformat(), request_count + 1, now.isoformat(), account_id),
            )
            connection.commit()

    def _mark_account_rate_limited(self, account_id: str, error: WeChatRateLimitError) -> None:
        now = _utc_now()
        retry_at = _parse_iso_datetime(error.retry_at) or (
            now + timedelta(hours=WECHAT_RATE_LIMIT_COOLDOWN_HOURS)
        )
        message = str(error) or "微信公众平台触发访问频控，已暂停自动检查"
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'active', reauth_required_at = NULL,
                    rate_limited_until = ?, rate_limit_reason = ?,
                    last_rate_limited_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (retry_at.isoformat(), message, now.isoformat(), now.isoformat(), account_id),
            )
            connection.commit()

    def _clear_account_rate_limit(self, account_id: str) -> None:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'active', reauth_required_at = NULL,
                    rate_limited_until = NULL, rate_limit_reason = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, account_id),
            )
            connection.commit()

    def _mark_account_valid(self, account_id: str) -> None:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'active', last_validated_at = ?, reauth_required_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, now, account_id),
            )
            connection.commit()

    def _mark_account_reauth(self, account_id: str) -> None:
        self._validated_until.pop(account_id, None)
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'requires_reauth', reauth_required_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, account_id),
            )
            connection.commit()

    def _create_sync_run(self, subscription_id: str) -> str:
        run_id = new_id()
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO wechat_sync_runs (id, subscription_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (run_id, subscription_id, utc_now_iso()),
            )
            connection.commit()
        return run_id

    def _finish_sync_run(
        self,
        run_id: str,
        status: str,
        found_count: int,
        imported_count: int,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_sync_runs
                SET status = ?, finished_at = ?, found_count = ?, imported_count = ?,
                    error_category = ?, error_message = ?
                WHERE id = ?
                """,
                (status, utc_now_iso(), found_count, imported_count, error_category, error_message, run_id),
            )
            connection.commit()

    def _update_sync_run_progress(self, run_id: str, found_count: int, imported_count: int) -> None:
        """Keep the running row useful to a UI that reconnects mid-sync."""
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_sync_runs
                SET found_count = ?, imported_count = ?
                WHERE id = ? AND status = 'running'
                """,
                (found_count, imported_count, run_id),
            )
            connection.commit()

    def _mark_sync_success(self, subscription_id: str, interval_minutes: int) -> None:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_subscriptions
                SET last_sync_at = ?, next_sync_at = ?, last_error = NULL, last_error_category = NULL,
                    consecutive_failure_count = 0, updated_at = ?
                WHERE id = ?
                """,
                (now, _iso_after(interval_minutes), now, subscription_id),
            )
            connection.commit()

    def _mark_sync_failure(self, subscription_id: str, message: str, category: str) -> None:
        now = utc_now_iso()
        with connect() as connection:
            row = connection.execute(
                "SELECT consecutive_failure_count FROM wechat_subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            if row is None:
                return
            failure_count = int(row["consecutive_failure_count"] or 0) + 1
            retry_delay = _retry_delay_minutes(category, failure_count)
            connection.execute(
                """
                UPDATE wechat_subscriptions
                SET last_error = ?, last_error_category = ?, consecutive_failure_count = ?,
                    next_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (message, category, failure_count, _iso_after(retry_delay), now, subscription_id),
            )
            connection.commit()

    def _article_is_known(self, subscription_id: str, remote_article_id: str) -> bool:
        with connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM wechat_subscription_items
                WHERE subscription_id = ? AND remote_article_id = ?
                """,
                (subscription_id, remote_article_id),
            ).fetchone()
        return row is not None

    def _known_article_ids(self, subscription_id: str) -> set[str]:
        with connect() as connection:
            rows = connection.execute(
                "SELECT remote_article_id FROM wechat_subscription_items WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchall()
        return {str(row["remote_article_id"]) for row in rows}

    def _capture_article(self, subscription: dict[str, Any], article: WeChatArticleCandidate) -> bool:
        capture = capture_link_to_inbox(article.source_url, manual_collection=False)
        if capture.error or not capture.item:
            raise WeChatSubscriptionError(capture.error or "公众号文章写入内容库失败")
        item = capture.item
        now = utc_now_iso()
        try:
            with connect() as connection:
                publisher_folder_id = ensure_wechat_subscription_folder(
                    connection,
                    str(subscription["mp_name"] or ""),
                    subscription_id=str(subscription["id"]),
                )
                connection.execute(
                    """
                    UPDATE content_items
                    SET title = CASE WHEN title = '' OR title = source_url THEN ? ELSE title END,
                        cover_url = COALESCE(cover_url, ?),
                        source_name = CASE
                            WHEN COALESCE(TRIM(source_name), '') = '' THEN ?
                            ELSE source_name
                        END,
                        status = CASE WHEN ? = 0 AND status = 'inbox' THEN 'to_read' ELSE status END,
                        library_folder_id = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        article.title,
                        article.cover_url or None,
                        str(subscription["mp_name"] or "").strip() or None,
                        int(bool(subscription["auto_process"])),
                        publisher_folder_id,
                        now,
                        item.id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO wechat_subscription_items (
                        id, subscription_id, remote_article_id, source_url, content_item_id,
                        title, published_at, discovered_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_id(),
                        subscription["id"],
                        article.remote_article_id,
                        article.source_url,
                        item.id,
                        article.title,
                        article.published_at,
                        now,
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError:
            return False
        if subscription["auto_process"] and item.status == "inbox":
            process_inbox_item(item.id, use_cache=True, processing_mode="full")
        else:
            enqueue_article_source_preparation(item.id)
        return True


class WeChatSubscriptionScheduler:
    def __init__(self, service: WeChatSubscriptionService) -> None:
        self._service = service
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        if not settings.wechat_subscription_scheduler_enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="wechat-subscription-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        self._sync_due_subscriptions_safely()
        interval = max(15, int(settings.wechat_subscription_scheduler_interval_seconds))
        while not self._stop_event.wait(interval):
            self._sync_due_subscriptions_safely()

    def _sync_due_subscriptions_safely(self) -> None:
        try:
            self._service.sync_due_subscriptions()
        except Exception:
            # Individual failures are written to sync history by the service.
            pass


class WeChatBulkSyncQueue:
    """Serial, paced newest-window checks for every enabled subscription."""

    def __init__(
        self,
        service: WeChatSubscriptionService,
        *,
        delay_range: tuple[float, float] = WECHAT_CHECK_DELAY_RANGE,
        check_limit: int = settings.wechat_subscription_default_initial_limit,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._service = service
        self._delay_range = delay_range
        self._check_limit = max(1, min(int(check_limit), 10))
        self._sleep = sleep
        self._uniform = uniform
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wechat-bulk-sync")
        self._lock = Lock()
        self._state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "job_id": "",
            "status": "idle",
            "total": 0,
            "completed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "imported_count": 0,
            "incomplete_count": 0,
            "current_subscription_id": "",
            "current_name": "",
            "message": "",
        }

    def enqueue(self) -> dict[str, Any]:
        subscriptions = [item for item in self._service.list_subscriptions() if item.get("enabled")]
        with self._lock:
            if self._state.get("status") in {"queued", "running"}:
                return dict(self._state)
            self._state = {
                **self._idle_state(),
                "job_id": new_id(),
                "status": "queued",
                "total": len(subscriptions),
                "message": "等待开始",
            }
            snapshot = dict(self._state)
        if subscriptions:
            self._executor.submit(self._run, subscriptions)
        else:
            with self._lock:
                self._state.update(status="succeeded", message="没有已启用的公众号需要更新")
                snapshot = dict(self._state)
        return snapshot

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)

    def _run(self, subscriptions: list[dict[str, Any]]) -> None:
        self._update(status="running", message="正在逐个检查公众号")
        stopped = False
        for index, subscription in enumerate(subscriptions):
            if index:
                lower, upper = self._delay_range
                self._sleep(self._uniform(max(0.0, lower), max(lower, upper)))
            self._update(
                current_subscription_id=str(subscription["id"]),
                current_name=str(subscription.get("mp_name") or "公众号"),
                message="正在检查最新文章",
            )
            try:
                result = self._service.sync_subscription(
                    str(subscription["id"]),
                    mode="latest",
                    max_items=self._check_limit,
                    force=False,
                )
                state = self.status()
                self._update(
                    completed=state["completed"] + 1,
                    succeeded=state["succeeded"] + 1,
                    imported_count=state["imported_count"] + int(result.get("imported_count") or 0),
                    incomplete_count=state["incomplete_count"] + (0 if result.get("coverage_complete", True) else 1),
                    current_subscription_id="",
                    current_name="",
                    message="等待检查下一个公众号",
                )
            except (WeChatAuthorizationError, WeChatRemoteError) as exc:
                state = self.status()
                self._update(
                    completed=state["completed"] + 1,
                    failed=state["failed"] + 1,
                    skipped=len(subscriptions) - index - 1,
                    status="stopped",
                    message=f"已停止：{exc}",
                )
                stopped = True
                break
            except WeChatSubscriptionError:
                state = self.status()
                self._update(
                    completed=state["completed"] + 1,
                    failed=state["failed"] + 1,
                    current_subscription_id="",
                    current_name="",
                    message="等待检查下一个公众号",
                )
        if not stopped:
            state = self.status()
            final_status = "succeeded" if not state["failed"] else "completed_with_errors"
            self._update(status=final_status, current_subscription_id="", current_name="", message="全部检查完成")


def _subscription_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["enabled"] = bool(data.get("enabled"))
    data["auto_process"] = bool(data.get("auto_process"))
    data["notify_on_new"] = bool(data.get("notify_on_new"))
    data.pop("sync_limit", None)
    data["group_ids"] = [value for value in str(data.pop("group_ids_csv") or "").split(",") if value]
    data["group_id"] = data["group_ids"][0] if data["group_ids"] else None
    return data


wechat_subscription_service = WeChatSubscriptionService()
wechat_qr_auth_service = WeChatQrAuthService()
wechat_initial_sync_queue = WeChatInitialSyncQueue(wechat_subscription_service, max_workers=2)
wechat_bulk_sync_queue = WeChatBulkSyncQueue(wechat_subscription_service)
wechat_subscription_scheduler = WeChatSubscriptionScheduler(wechat_subscription_service)
