from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DownloadResult:
    success: bool
    video_path: Path | None = None
    video_info: dict = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    error: str = ""


@dataclass(frozen=True)
class DownloadProgress:
    """A truthful, transport-level update for the media download UI.

    ``percent`` exists only when the provider has a real denominator. It is
    deliberately absent for parsing, DASH merging, validation and compression:
    those operations have no reliable completion ratio.
    """

    phase: str
    detail: str
    received_bytes: int | None = None
    total_bytes: int | None = None
    bytes_per_second: float | None = None
    percent: float | None = None


ProgressCallback = Callable[[DownloadProgress], None]
CancelCheck = Callable[[], bool]
DownloadLogCallback = Callable[[str], None]


def report_progress(progress_callback: ProgressCallback | None, progress: DownloadProgress) -> None:
    if progress_callback:
        progress_callback(progress)


def append_download_log(
    logs: list[str],
    message: str,
    log_callback: DownloadLogCallback | None = None,
) -> None:
    """Persist a provider log and immediately expose it to an active task."""
    logs.append(message)
    if log_callback:
        try:
            log_callback(message)
        except Exception:
            # A UI/database progress notification must not interrupt a media
            # transfer that can still be completed and recovered locally.
            pass


def report_phase(
    progress_callback: ProgressCallback | None,
    phase: str,
    detail: str,
) -> None:
    report_progress(progress_callback, DownloadProgress(phase=phase, detail=detail))


def report_transfer(
    progress_callback: ProgressCallback | None,
    received_bytes: int,
    total_bytes: int | None,
    *,
    started_at: float,
    detail: str,
) -> None:
    percent = (received_bytes / total_bytes) * 100 if total_bytes else None
    elapsed = max(time.monotonic() - started_at, 0.001)
    report_progress(
        progress_callback,
        DownloadProgress(
            phase="transfer",
            detail=detail,
            received_bytes=received_bytes,
            total_bytes=total_bytes,
            bytes_per_second=received_bytes / elapsed,
            percent=max(0.0, min(100.0, percent)) if percent is not None else None,
        ),
    )


def report_transfer_percent(
    progress_callback: ProgressCallback | None,
    percent: float,
    detail: str,
    *,
    bytes_per_second: float | None = None,
) -> None:
    """Project a stream percentage and optional instantaneous transfer rate."""
    report_progress(
        progress_callback,
        DownloadProgress(
            phase="transfer",
            detail=detail,
            bytes_per_second=bytes_per_second,
            percent=max(0.0, min(100.0, percent)),
        ),
    )


def media_transfer_error(transfer) -> str:
    """Keep a CDN HTTP status visible to retry and cookie-health policy."""
    detail = str(getattr(transfer, "error", "") or "媒体传输失败")
    status_code = getattr(transfer, "status_code", None)
    return f"HTTP {status_code}: {detail}" if status_code else detail


def yt_dlp_bytes_per_second(line: str) -> float | None:
    match = re.search(r"\bat\s+~?\s*([\d.]+)\s*([KMGT]?i?B)/s\b", line, re.IGNORECASE)
    if not match:
        return None
    try:
        amount = float(match.group(1))
    except ValueError:
        return None
    unit = match.group(2).lower()
    multipliers = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "kib": 1024,
        "mib": 1024**2,
        "gib": 1024**3,
        "tib": 1024**4,
    }
    return amount * multipliers[unit] if unit in multipliers else None


def activity_timeout_error(
    *,
    now: float,
    last_activity_at: float,
    stall_seconds: float,
    operation: str,
) -> str | None:
    if now - last_activity_at <= stall_seconds:
        return None
    if stall_seconds >= 60 and stall_seconds % 60 == 0:
        window = f"{int(stall_seconds // 60)} 分钟"
    else:
        window = f"{int(stall_seconds)} 秒"
    separator = " " if operation and operation[-1].isascii() else ""
    return f"{operation}{separator}连续 {window}没有新的进度或输出"
