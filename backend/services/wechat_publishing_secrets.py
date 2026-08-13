from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

KEYCHAIN_SERVICE = "KnowledgeHub WeChat Publishing"


class WeChatPublishingError(RuntimeError):
    """A safe, user-facing official-account publishing error."""


@dataclass(frozen=True)
class PublishingCredentials:
    app_id: str
    app_secret: str


@dataclass(frozen=True)
class QwenCoverCredentials:
    api_key: str


class KeychainPublishingSecretStore:
    """Store publisher credentials in Keychain, never in SQLite or UI responses."""

    def _security_command(self) -> str:
        command = shutil.which("security")
        if not command:
            raise WeChatPublishingError("当前系统未提供 macOS Keychain，无法保存公众号 AppSecret")
        return command

    def save(self, keychain_ref: str, credentials: PublishingCredentials) -> None:
        self._save_json(keychain_ref, {"app_id": credentials.app_id, "app_secret": credentials.app_secret})

    def save_qwen_cover(self, keychain_ref: str, credentials: QwenCoverCredentials) -> None:
        self._save_json(keychain_ref, {"api_key": credentials.api_key})

    def _save_json(self, keychain_ref: str, payload: dict[str, str]) -> None:
        try:
            result = subprocess.run(
                [
                    self._security_command(),
                    "add-generic-password",
                    "-U",
                    "-a",
                    keychain_ref,
                    "-s",
                    KEYCHAIN_SERVICE,
                    "-w",
                    json.dumps(payload),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise WeChatPublishingError("写入公众号 AppSecret 超时，请检查钥匙串访问权限") from exc
        if result.returncode != 0:
            raise WeChatPublishingError("无法写入公众号 AppSecret，请检查钥匙串访问权限")

    def load(self, keychain_ref: str) -> PublishingCredentials:
        payload = self._load_json(keychain_ref)
        credentials = PublishingCredentials(
            app_id=str(payload.get("app_id") or "").strip(),
            app_secret=str(payload.get("app_secret") or "").strip(),
        )
        if not credentials.app_id or not credentials.app_secret:
            raise WeChatPublishingError("公众号 AppID 或 AppSecret 不完整，请重新配置")
        return credentials

    def load_qwen_cover(self, keychain_ref: str) -> QwenCoverCredentials:
        payload = self._load_json(keychain_ref, missing_message="未找到千问封面 API Key，请在设置中重新配置")
        credentials = QwenCoverCredentials(api_key=str(payload.get("api_key") or "").strip())
        if not credentials.api_key:
            raise WeChatPublishingError("千问封面 API Key 不完整，请重新配置")
        return credentials

    def _load_json(
        self,
        keychain_ref: str,
        *,
        missing_message: str = "未找到公众号 AppSecret，请在设置中重新配置",
    ) -> dict[str, Any]:
        try:
            result = subprocess.run(
                [
                    self._security_command(),
                    "find-generic-password",
                    "-a",
                    keychain_ref,
                    "-s",
                    KEYCHAIN_SERVICE,
                    "-w",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise WeChatPublishingError("读取公众号 AppSecret 超时，请检查钥匙串访问权限") from exc
        if result.returncode != 0:
            raise WeChatPublishingError(missing_message)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise WeChatPublishingError("公众号 AppSecret 已损坏，请重新配置") from exc
        return payload if isinstance(payload, dict) else {}
