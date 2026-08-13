"""Ephemeral QR authorization state machine for WeChat public-account access."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

import requests

from services.repository import new_id
from services.wechat_subscription_client import WECHAT_MP_BASE_URL, WECHAT_USER_AGENT
from services.wechat_subscription_errors import WeChatRemoteError
from services.wechat_subscription_secrets import SessionCredentials, WeChatAuthorizationError


@dataclass(frozen=True)
class QrLoginStatus:
    login_id: str
    status: str
    message: str
    qr_image_data_url: str | None = None
    credentials: SessionCredentials | None = None


@dataclass
class _PendingQrLogin:
    session: requests.Session
    qr_image_data_url: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def _extract_token(*values: str) -> str:
    for value in values:
        match = re.search(r"(?:[?&]|^)token=(\d+)", value or "")
        if match:
            return match.group(1)
    return ""


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
