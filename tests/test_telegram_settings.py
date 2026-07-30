from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services import telegram_settings


def test_telegram_token_moves_to_keychain_and_never_remains_in_json(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    keychain: dict[str, str] = {}
    monkeypatch.setattr(telegram_settings, "_load_keychain_token", lambda: keychain.get("token", ""))
    monkeypatch.setattr(telegram_settings, "_save_keychain_token", lambda token: keychain.update(token=token))

    saved = telegram_settings.save_telegram_settings({
        "bot_token": "123456:secret",
        "allowed_user_ids": [1001],
        "reply_enabled": True,
    })

    assert saved["bot_token"] == "123456:secret"
    assert keychain["token"] == "123456:secret"
    persisted = telegram_settings.telegram_settings_path().read_text(encoding="utf-8")
    assert "secret" not in persisted
    assert telegram_settings.load_telegram_settings()["bot_token"] == "123456:secret"


def test_legacy_telegram_file_migrates_when_keychain_is_available(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    path = telegram_settings.telegram_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"bot_token":"legacy-secret","allowed_user_ids":[7]}',
        encoding="utf-8",
    )
    keychain: dict[str, str] = {}
    monkeypatch.setattr(telegram_settings, "_load_keychain_token", lambda: keychain.get("token", ""))
    monkeypatch.setattr(telegram_settings, "_save_keychain_token", lambda token: keychain.update(token=token))

    loaded = telegram_settings.load_telegram_settings()

    assert loaded["bot_token"] == "legacy-secret"
    assert keychain["token"] == "legacy-secret"
    assert "bot_token" not in telegram_settings.telegram_settings_path().read_text(encoding="utf-8")
