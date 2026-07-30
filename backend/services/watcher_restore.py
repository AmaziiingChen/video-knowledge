"""Restore user-enabled local listeners after the desktop backend starts."""
from __future__ import annotations

from services.clipboard_settings import load_clipboard_watcher_settings
from services.clipboard_watcher import clipboard_watcher
from services.folder_import_settings import load_folder_import_watcher_settings
from services.folder_import_watcher import folder_import_watcher
from services.telegram_settings import load_telegram_settings
from services.telegram_watcher import telegram_watcher


def restore_enabled_watchers() -> None:
    clipboard = load_clipboard_watcher_settings()
    if clipboard["enabled"]:
        clipboard_watcher.start(
            whisper_model=clipboard["whisper_model"],
            asr_backend=clipboard["asr_backend"],
            asr_model_strategy=clipboard["asr_model_strategy"],
            asr_short_video_model=clipboard["asr_short_video_model"],
            asr_long_video_model=clipboard["asr_long_video_model"],
            asr_beam_size=clipboard["asr_beam_size"],
            asr_vad_filter=clipboard["asr_vad_filter"],
            asr_fallback_enabled=clipboard["asr_fallback_enabled"],
            ai_model=clipboard["ai_model"],
            use_cache=clipboard["use_cache"],
            poll_interval=clipboard["poll_interval"],
            capture_mode=clipboard["capture_mode"],
            skip_current_clipboard=True,
        )

    telegram = load_telegram_settings()
    if telegram.get("watch_enabled") is True:
        telegram_watcher.start()

    folder_import = load_folder_import_watcher_settings()
    if folder_import["enabled"]:
        folder_import_watcher.start(
            folder_path=str(folder_import["folder_path"]),
            poll_interval=float(folder_import["poll_interval"]),
            skip_existing=True,
        )


def stop_watchers() -> None:
    clipboard_watcher.stop()
    telegram_watcher.stop()
    folder_import_watcher.stop()
