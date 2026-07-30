"""Cancelable FFmpeg execution with activity-based stall detection.

FFmpeg reports structured progress on stdout when invoked with ``-progress
pipe:1``.  A wall-clock timeout is inappropriate for large local media: a
healthy transcode can take hours.  This module treats progress output and a
growing temporary output file as activity, while still stopping a genuinely
stalled child process.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Sequence


FFMPEG_ACTIVITY_TIMEOUT_SECONDS = 300
FFMPEG_POLL_INTERVAL_SECONDS = 0.25


@dataclass(frozen=True)
class FfmpegProgress:
    out_time_seconds: float | None = None
    speed: str = ""
    percent: float | None = None


@dataclass(frozen=True)
class FfmpegRunResult:
    success: bool
    cancelled: bool = False
    stalled: bool = False
    returncode: int | None = None
    stderr: str = ""
    elapsed_seconds: float = 0.0
    last_progress: FfmpegProgress | None = None


def with_ffmpeg_progress(command: Sequence[str]) -> list[str]:
    """Add FFmpeg's machine-readable progress stream before normal options."""
    if not command:
        raise ValueError("FFmpeg command is empty")
    return [str(command[0]), "-progress", "pipe:1", "-nostats", *map(str, command[1:])]


def run_ffmpeg(
    command: Sequence[str],
    *,
    output_path: Path,
    duration_seconds: float | None = None,
    progress_callback: Callable[[FfmpegProgress], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    activity_timeout_seconds: float = FFMPEG_ACTIVITY_TIMEOUT_SECONDS,
) -> FfmpegRunResult:
    """Run FFmpeg until completion, cancellation, or real inactivity.

    ``output_path`` must be a temporary target.  The caller owns validation and
    promotion to the final path, so a failed conversion never overwrites user
    media.
    """
    started_at = time.monotonic()
    process = subprocess.Popen(
        with_ffmpeg_progress(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=os.name != "nt",
    )
    output_lines: Queue[str] = Queue()
    last_activity_at = started_at
    last_signature = _file_signature(output_path)
    stderr_lines: list[str] = []
    progress_values: dict[str, str] = {}
    last_progress: FfmpegProgress | None = None

    def reader() -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            output_lines.put(line)

    output_reader = threading.Thread(target=reader, daemon=True)
    output_reader.start()

    def record_line(line: str) -> None:
        nonlocal last_activity_at, last_progress
        clean = line.strip()
        if not clean:
            return
        last_activity_at = time.monotonic()
        key, separator, value = clean.partition("=")
        if separator and key in {"out_time_us", "out_time_ms", "speed", "progress"}:
            progress_values[key] = value
            if key == "progress":
                last_progress = _progress_from_values(progress_values, duration_seconds)
                if progress_callback and last_progress is not None:
                    try:
                        progress_callback(last_progress)
                    except Exception:
                        # A visual update cannot be allowed to interrupt local
                        # media processing.
                        pass
        else:
            stderr_lines.append(clean)
            if len(stderr_lines) > 80:
                del stderr_lines[: len(stderr_lines) - 80]

    while process.poll() is None:
        if cancel_check and cancel_check():
            _stop_process(process)
            output_reader.join(timeout=1)
            return _result(False, cancelled=True, stderr_lines=stderr_lines, started_at=started_at, last_progress=last_progress)

        try:
            record_line(output_lines.get(timeout=FFMPEG_POLL_INTERVAL_SECONDS))
            while True:
                record_line(output_lines.get_nowait())
        except Empty:
            pass

        if process.poll() is not None:
            break
        current_signature = _file_signature(output_path)
        if current_signature != last_signature:
            last_signature = current_signature
            last_activity_at = time.monotonic()
        if time.monotonic() - last_activity_at > activity_timeout_seconds:
            _stop_process(process)
            output_reader.join(timeout=1)
            return _result(False, stalled=True, stderr_lines=stderr_lines, started_at=started_at, last_progress=last_progress)

    output_reader.join(timeout=1)
    while True:
        try:
            record_line(output_lines.get_nowait())
        except Empty:
            break
    returncode = process.wait()
    return _result(
        returncode == 0,
        returncode=returncode,
        stderr_lines=stderr_lines,
        started_at=started_at,
        last_progress=last_progress,
    )


def probe_media_duration(path: Path) -> float | None:
    """Return a local media duration for progress percentages when available."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        duration = float((result.stdout or "").strip())
        return duration if duration > 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def _progress_from_values(values: dict[str, str], duration_seconds: float | None) -> FfmpegProgress:
    raw_time = values.get("out_time_us") or values.get("out_time_ms") or ""
    try:
        # FFmpeg historically labels this microseconds field ``out_time_ms``.
        out_time_seconds = float(raw_time) / 1_000_000 if raw_time else None
    except ValueError:
        out_time_seconds = None
    percent = None
    if out_time_seconds is not None and duration_seconds:
        percent = max(0.0, min(100.0, (out_time_seconds / duration_seconds) * 100))
    return FfmpegProgress(
        out_time_seconds=out_time_seconds,
        speed=str(values.get("speed") or ""),
        percent=percent,
    )


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            return


def _result(
    success: bool,
    *,
    stderr_lines: list[str],
    started_at: float,
    cancelled: bool = False,
    stalled: bool = False,
    returncode: int | None = None,
    last_progress: FfmpegProgress | None = None,
) -> FfmpegRunResult:
    return FfmpegRunResult(
        success=success,
        cancelled=cancelled,
        stalled=stalled,
        returncode=returncode,
        stderr="\n".join(stderr_lines)[-4000:],
        elapsed_seconds=time.monotonic() - started_at,
        last_progress=last_progress,
    )
