from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from services.wechat_publishing_secrets import (
    KEYCHAIN_SERVICE,
    KeychainPublishingSecretStore,
    PublishingCredentials,
    WeChatPublishingError,
)


def test_wechat_publishing_retains_legacy_secret_type_imports():
    from services import wechat_publishing

    assert wechat_publishing.KeychainPublishingSecretStore is KeychainPublishingSecretStore
    assert wechat_publishing.PublishingCredentials is PublishingCredentials
    assert wechat_publishing.WeChatPublishingError is WeChatPublishingError


def test_keychain_store_writes_json_payload_to_expected_service(monkeypatch):
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr("services.wechat_publishing_secrets.shutil.which", lambda _name: "/usr/bin/security")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("services.wechat_publishing_secrets.subprocess.run", fake_run)

    KeychainPublishingSecretStore().save("account-ref", PublishingCredentials("wx-id", "secret-value"))

    assert calls == [
        (
            [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-a",
                "account-ref",
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
                json.dumps({"app_id": "wx-id", "app_secret": "secret-value"}),
            ],
            {"capture_output": True, "text": True, "check": False, "timeout": 5},
        )
    ]


def test_keychain_store_rejects_malformed_or_missing_credentials(monkeypatch):
    monkeypatch.setattr("services.wechat_publishing_secrets.shutil.which", lambda _name: "/usr/bin/security")
    responses = iter(
        [
            SimpleNamespace(returncode=0, stdout="not-json"),
            SimpleNamespace(returncode=1, stdout=""),
        ]
    )
    monkeypatch.setattr("services.wechat_publishing_secrets.subprocess.run", lambda *_args, **_kwargs: next(responses))
    store = KeychainPublishingSecretStore()

    with pytest.raises(WeChatPublishingError, match="已损坏"):
        store.load("account-ref")
    with pytest.raises(WeChatPublishingError, match="未找到千问封面 API Key"):
        store.load_qwen_cover("cover-ref")


def test_keychain_store_reports_when_macos_security_command_is_unavailable(monkeypatch):
    monkeypatch.setattr("services.wechat_publishing_secrets.shutil.which", lambda _name: None)

    with pytest.raises(WeChatPublishingError, match="macOS Keychain"):
        KeychainPublishingSecretStore().load("account-ref")
