from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from config import settings


SETTINGS_FILE = "telegram_settings.json"
KEYCHAIN_SERVICE = "KnowledgeHub Telegram"
KEYCHAIN_ACCOUNT = "bot-token"
KEYCHAIN_TIMEOUT_SECONDS = 5
_WATCH_OPTION_KEYS = {
    "whisper_model",
    "asr_backend",
    "asr_model_strategy",
    "asr_short_video_model",
    "asr_long_video_model",
    "asr_beam_size",
    "asr_vad_filter",
    "asr_fallback_enabled",
    "ai_model",
    "use_cache",
}


def telegram_settings_path() -> Path:
    return settings.data_dir / SETTINGS_FILE


def load_telegram_settings() -> dict:
    """Return Telegram settings for backend use, migrating old file secrets once.

    The returned mapping contains ``bot_token`` only for trusted backend code.
    Router response models must expose only ``configured`` and a masked value.
    """
    values = _load_public_settings()
    legacy_token = str(values.pop("bot_token", "") or "").strip()
    token = _load_keychain_token()
    if not token and legacy_token:
        try:
            _save_keychain_token(legacy_token)
        except RuntimeError:
            # Migration must never make a previously working desktop app fail
            # to boot. Keep the old owner-only file until the user can grant
            # Keychain access, while still ensuring no API sends it back out.
            values["bot_token"] = legacy_token
        else:
            token = legacy_token
            _write_public_settings(values)
    if token:
        values["bot_token"] = token
    return values


def save_telegram_settings(data: dict) -> dict:
    """Persist non-secret settings locally and the bot token in macOS Keychain.

    Omitting ``bot_token`` intentionally preserves an existing secret. This
    lets a blank settings form update the whitelist without erasing the token.
    """
    current = _load_public_settings()
    requested_token = data.get("bot_token") if "bot_token" in data else None
    if requested_token is not None:
        token = str(requested_token or "").strip()
        if token:
            _save_keychain_token(token)
        # A blank form is not a secret-deletion request. There is no UI action
        # for deleting the token yet, so preserve the Keychain value.
    current.update(
        {
            "allowed_user_ids": [
                int(user_id)
                for user_id in data.get("allowed_user_ids", current.get("allowed_user_ids", []))
                if isinstance(user_id, int) or str(user_id).isdigit()
            ],
            "reply_enabled": bool(data.get("reply_enabled", current.get("reply_enabled", True))),
        }
    )
    if "watch_enabled" in data:
        current["watch_enabled"] = bool(data["watch_enabled"])
    if "watch_options" in data and isinstance(data["watch_options"], dict):
        current["watch_options"] = {
            key: data["watch_options"].get(key)
            for key in _WATCH_OPTION_KEYS
            if key in data["watch_options"]
        }
    if "last_update_id" in data:
        current["last_update_id"] = _positive_int_or_none(data["last_update_id"])
    current.pop("bot_token", None)
    _write_public_settings(current)
    return load_telegram_settings()


def save_telegram_watcher_checkpoint(last_update_id: int) -> None:
    """Persist only the completed Telegram update cursor.

    Keeping this cursor across backend restarts prevents already accepted
    messages from being sent to the processing queue a second time.
    """
    current = _load_public_settings()
    current["last_update_id"] = _positive_int_or_none(last_update_id)
    _write_public_settings(current)


def _positive_int_or_none(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _load_public_settings() -> dict:
    path = telegram_settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_public_settings(values: dict) -> None:
    path = telegram_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _security_command() -> str:
    command = shutil.which("security")
    if not command:
        raise RuntimeError("当前系统未提供 macOS Keychain，无法保存 Telegram Bot Token")
    return command


def _load_keychain_token() -> str:
    try:
        result = subprocess.run(
            [_security_command(), "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True,
            text=True,
            check=False,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _save_keychain_token(token: str) -> None:
    try:
        result = subprocess.run(
            [_security_command(), "add-generic-password", "-U", "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w", token],
            capture_output=True,
            text=True,
            check=False,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("写入 Telegram Bot Token 超时，请检查钥匙串访问权限") from exc
    if result.returncode != 0:
        raise RuntimeError("无法写入 Telegram Bot Token，请检查钥匙串访问权限")
