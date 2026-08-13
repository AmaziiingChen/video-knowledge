from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass


WECHAT_KEYCHAIN_TIMEOUT_SECONDS = 12


class WeChatSubscriptionError(RuntimeError):
    category = "wechat_subscription"


class WeChatAuthorizationError(WeChatSubscriptionError):
    category = "authorization"


@dataclass(frozen=True)
class SessionCredentials:
    token: str
    cookie: str


class MacOSKeychainSessionStore:
    """Keep WeChat session secrets out of SQLite and application logs."""

    service_name = "Video Knowledge WeChat Subscriptions"

    def _security_command(self) -> str:
        command = shutil.which("security")
        if not command:
            raise WeChatSubscriptionError("当前系统未提供 macOS Keychain，无法保存微信登录态")
        return command

    def save(self, keychain_ref: str, credentials: SessionCredentials) -> None:
        payload = json.dumps({"token": credentials.token, "cookie": credentials.cookie}, ensure_ascii=False)
        try:
            result = subprocess.run(
                [self._security_command(), "add-generic-password", "-U", "-a", keychain_ref, "-s", self.service_name, "-w", payload],
                capture_output=True, text=True, check=False, timeout=WECHAT_KEYCHAIN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise WeChatSubscriptionError("写入微信登录态超时，请检查钥匙串访问权限") from exc
        if result.returncode != 0:
            raise WeChatSubscriptionError("无法写入 macOS Keychain，请检查钥匙串访问权限")

    def load(self, keychain_ref: str) -> SessionCredentials:
        try:
            result = subprocess.run(
                [self._security_command(), "find-generic-password", "-a", keychain_ref, "-s", self.service_name, "-w"],
                capture_output=True, text=True, check=False, timeout=WECHAT_KEYCHAIN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise WeChatAuthorizationError("读取微信登录态超时，请检查钥匙串访问权限") from exc
        if result.returncode != 0:
            raise WeChatAuthorizationError("未找到微信登录态，请重新授权")
        try:
            payload = json.loads(result.stdout)
            credentials = SessionCredentials(token=str(payload.get("token") or "").strip(), cookie=str(payload.get("cookie") or "").strip())
        except (json.JSONDecodeError, TypeError) as exc:
            raise WeChatAuthorizationError("微信登录态损坏，请重新授权") from exc
        if not credentials.token or not credentials.cookie:
            raise WeChatAuthorizationError("微信登录态不完整，请重新授权")
        return credentials

    def delete(self, keychain_ref: str) -> None:
        try:
            result = subprocess.run(
                [self._security_command(), "delete-generic-password", "-a", keychain_ref, "-s", self.service_name],
                capture_output=True, text=True, check=False, timeout=WECHAT_KEYCHAIN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise WeChatSubscriptionError("删除微信登录态超时，请检查钥匙串访问权限") from exc
        if result.returncode not in {0, 44}:
            raise WeChatSubscriptionError("无法从 macOS Keychain 删除微信登录态")
