"""Bounded media download execution with prompt durable progress logs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import BoundedSemaphore
from typing import Protocol

from services.download_contracts import DownloadProgress, DownloadResult
from services.downloader import download_video
from services.pipeline_progress_rules import level_from_message


class DownloadSlot(Protocol):
    def acquire(self, *, timeout: float) -> bool: ...

    def release(self) -> None: ...


# A desktop can keep one network transfer moving while the previous file is
# transcribed. Competing providers make both less reliable and saturate the
# local network, so every pipeline path shares this one slot.
MEDIA_DOWNLOAD_SLOT = BoundedSemaphore(1)


def download_media_with_live_logs(
    url: str,
    platform: str,
    output_dir: Path,
    *,
    add_log: Callable[[str, str, str, float | None], None],
    set_download_transfer: Callable[[DownloadProgress], None],
    check_cancel: Callable[[], None],
    provider_cancel_check: Callable[[], bool] | None,
    downloader: Callable[..., DownloadResult] = download_video,
    download_slot: DownloadSlot = MEDIA_DOWNLOAD_SLOT,
) -> DownloadResult:
    """Forward provider milestones once while retaining its complete log."""
    published_counts: dict[str, int] = {}
    waiting_for_download_slot = False

    while not download_slot.acquire(timeout=0.12):
        check_cancel()
        if not waiting_for_download_slot:
            waiting_for_download_slot = True
            add_log("download", "等待上一条视频下载完成…", "info", None)

    def publish_download_log(message: str) -> None:
        published_counts[message] = published_counts.get(message, 0) + 1
        add_log("download", message, level_from_message(message), None)

    try:
        result = downloader(
            url,
            platform,
            output_dir,
            progress_callback=set_download_transfer,
            cancel_check=provider_cancel_check,
            log_callback=publish_download_log,
        )
    finally:
        download_slot.release()
    for line in result.logs:
        remaining = published_counts.get(line, 0)
        if remaining:
            published_counts[line] = remaining - 1
            continue
        add_log("download", line, level_from_message(line), None)
    return result
