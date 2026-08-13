"""macOS Keychain storage for text-model API keys."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import MutableMapping
from typing import Protocol

KEYCHAIN_SERVICE = "KnowledgeHub Text Models"


class TextModelSecretError(RuntimeError):
    pass


class TextModelSecretStore(Protocol):
    def save(self, secret_ref: str, api_key: str) -> None: ...
    def load(self, secret_ref: str) -> str: ...
    def delete(self, secret_ref: str) -> None: ...


class MacOSKeychainTextModelSecretStore:
    def _security_command(self) -> str:
        command = shutil.which("security")
        if not command:
            raise TextModelSecretError("当前系统未提供 macOS Keychain，无法保存文本模型 API Key")
        return command

    def save(self, secret_ref: str, api_key: str) -> None:
        key = str(api_key or "").strip()
        if not key:
            self.delete(secret_ref)
            return
        try:
            result = subprocess.run(
                [
                    self._security_command(),
                    "add-generic-password",
                    "-U",
                    "-a",
                    secret_ref,
                    "-s",
                    KEYCHAIN_SERVICE,
                    "-w",
                    key,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise TextModelSecretError("写入文本模型 API Key 超时，请检查钥匙串访问权限") from exc
        if result.returncode != 0:
            raise TextModelSecretError("无法写入文本模型 API Key，请检查钥匙串访问权限")

    def load(self, secret_ref: str) -> str:
        try:
            result = subprocess.run(
                [
                    self._security_command(),
                    "find-generic-password",
                    "-a",
                    secret_ref,
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
            raise TextModelSecretError("读取文本模型 API Key 超时，请检查钥匙串访问权限") from exc
        if result.returncode == 0:
            return result.stdout.strip()
        # security(1) returns 44 when the item does not exist. Permission,
        # interaction and Keychain failures must remain distinguishable from
        # an absent key, otherwise a subsequent save can overwrite it.
        if result.returncode == 44:
            return ""
        raise TextModelSecretError("无法读取文本模型 API Key，请检查钥匙串访问权限")

    def delete(self, secret_ref: str) -> None:
        try:
            result = subprocess.run(
                [
                    self._security_command(),
                    "delete-generic-password",
                    "-a",
                    secret_ref,
                    "-s",
                    KEYCHAIN_SERVICE,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired as exc:
            raise TextModelSecretError("删除文本模型 API Key 超时，请检查钥匙串访问权限") from exc
        # security(1) returns 44 when the item is already absent.
        if result.returncode not in {0, 44}:
            raise TextModelSecretError("无法删除文本模型 API Key，请检查钥匙串访问权限")


class InMemoryTextModelSecretStore:
    def __init__(self, values: MutableMapping[str, str] | None = None) -> None:
        self.values = values if values is not None else {}

    def save(self, secret_ref: str, api_key: str) -> None:
        key = str(api_key or "").strip()
        if key:
            self.values[secret_ref] = key
        else:
            self.values.pop(secret_ref, None)

    def load(self, secret_ref: str) -> str:
        return str(self.values.get(secret_ref) or "")

    def delete(self, secret_ref: str) -> None:
        self.values.pop(secret_ref, None)


_secret_store: TextModelSecretStore = MacOSKeychainTextModelSecretStore()


def get_text_model_secret_store() -> TextModelSecretStore:
    return _secret_store


def set_text_model_secret_store(store: TextModelSecretStore) -> TextModelSecretStore:
    global _secret_store
    previous = _secret_store
    _secret_store = store
    return previous
