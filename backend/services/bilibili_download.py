from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from queue import Empty, Queue

from services.bilibili_auth import bilibili_yt_dlp_cookie_args
from services.bilibili_native import resolve_progressive_media
from services.download_contracts import (
    CancelCheck,
    DownloadResult,
    ProgressCallback,
    activity_timeout_error,
    report_phase,
    report_transfer,
    report_transfer_percent,
    yt_dlp_bytes_per_second,
)
from services.download_media_processing import is_valid_video_file
from services.http_media_download import download_http_media
from services.media_tools import resolve_tool
from services.network_policy import direct_network_environment


BILIBILI_1080P_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]"
YTDLP_ACTIVITY_TIMEOUT_SECONDS = 300


def download_bilibili(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DownloadResult:
    try:
        with bilibili_yt_dlp_cookie_args() as cookie_args:
            compatibility_result = download_bilibili_with_cookie_args(
                url, output_dir, progress_callback, cookie_args, cancel_check
            )
    except Exception as exc:
        compatibility_result = DownloadResult(success=False, error=f"yt-dlp 异常: {exc}")
    if compatibility_result.success or compatibility_result.error == "下载已取消":
        return compatibility_result

    native_result = download_bilibili_progressive(url, output_dir, progress_callback, cancel_check)
    if native_result.success:
        native_result.logs = [
            *compatibility_result.logs,
            "[B站] 兼容下载器不可用，已切换项目内直链下载",
            *native_result.logs,
        ]
        return native_result
    return compatibility_result


def download_bilibili_progressive(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None = None,
) -> DownloadResult:
    logs: list[str] = ["[B站] 尝试项目内直链下载..."]
    try:
        media = resolve_progressive_media(url)
        target = output_dir / f"{media.bvid}.native.part"
        transfer_started = time.monotonic()
        report_phase(progress_callback, "transfer", "正在传输视频")
        transfer = download_http_media(
            media.url,
            target,
            headers=media.headers,
            progress_callback=lambda received, total: report_transfer(
                progress_callback,
                received,
                total,
                started_at=transfer_started,
                detail="正在传输视频",
            ),
            cancel_check=cancel_check,
        )
        if not transfer.success:
            return DownloadResult(success=False, logs=logs, error=f"B站直链下载失败: {transfer.error}")
        report_phase(progress_callback, "validating", "正在校验媒体文件")
        if not is_valid_video_file(target):
            return DownloadResult(success=False, logs=logs, error="B站直链媒体校验失败")
        final_path = output_dir / f"{media.bvid}.mp4"
        target.replace(final_path)
        report_phase(progress_callback, "finalizing", "正在整理视频文件")
        logs.append(f"[B站] 项目内直链下载完成: {final_path.name}")
        return DownloadResult(
            success=True,
            video_path=final_path,
            video_info={
                "id": media.bvid,
                "title": media.title,
                "platform": "bilibili",
                "cid": media.cid,
                "page_number": media.page_number,
            },
            logs=logs,
        )
    except Exception as exc:
        return DownloadResult(success=False, logs=logs, error=f"B站直链解析失败: {exc}")


def download_bilibili_with_cookie_args(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None,
    cookie_args: list[str],
    cancel_check: CancelCheck | None = None,
) -> DownloadResult:
    output_template = str(output_dir / "%(id)s.%(ext)s")
    report_phase(progress_callback, "resolving", "正在解析视频地址")
    cmd = [
        resolve_tool("yt-dlp") or "yt-dlp",
        "--newline", "--no-playlist", "-f", BILIBILI_1080P_FORMAT,
        "--merge-output-format", "mp4", "-o", output_template,
        "--write-info-json", *cookie_args, url,
    ]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=direct_network_environment(),
    )
    logs: list[str] = []
    last_activity_at = time.monotonic()
    output_lines: Queue[str] = Queue()

    def output_signature() -> tuple[tuple[str, int, int], ...]:
        signature: list[tuple[str, int, int]] = []
        try:
            candidates = output_dir.iterdir()
            for candidate in candidates:
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                if candidate.is_file():
                    signature.append((candidate.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            return ()
        return tuple(sorted(signature))

    last_output_signature = output_signature()

    def read_output() -> None:
        if not process.stdout:
            return
        for line in process.stdout:
            output_lines.put(line)

    output_reader = threading.Thread(target=read_output, daemon=True)
    output_reader.start()

    def record_output(line: str) -> None:
        nonlocal last_activity_at
        clean = line.strip()
        if clean:
            logs.append(clean)
            last_activity_at = time.monotonic()
        match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", clean)
        if match:
            report_transfer_percent(
                progress_callback,
                float(match.group(1)),
                "正在传输媒体流",
                bytes_per_second=yt_dlp_bytes_per_second(clean),
            )

    while process.poll() is None:
        if cancel_check and cancel_check():
            _stop_process(process)
            output_reader.join(timeout=1)
            return DownloadResult(success=False, logs=logs, error="下载已取消")
        try:
            record_output(output_lines.get(timeout=0.5))
            while True:
                record_output(output_lines.get_nowait())
        except Empty:
            pass
        if process.poll() is not None:
            break
        current_output_signature = output_signature()
        if current_output_signature != last_output_signature:
            last_activity_at = time.monotonic()
            last_output_signature = current_output_signature
        timeout_error = activity_timeout_error(
            now=time.monotonic(),
            last_activity_at=last_activity_at,
            stall_seconds=YTDLP_ACTIVITY_TIMEOUT_SECONDS,
            operation="yt-dlp",
        )
        if timeout_error:
            _stop_process(process)
            output_reader.join(timeout=1)
            return DownloadResult(success=False, logs=logs, error=timeout_error)

    output_reader.join(timeout=1)
    while True:
        try:
            record_output(output_lines.get_nowait())
        except Empty:
            break
    return_code = process.wait()
    if return_code == 0:
        report_phase(progress_callback, "finalizing", "正在合并媒体轨道")
        for candidate in output_dir.iterdir():
            if candidate.suffix in [".mp4", ".mkv", ".webm", ".flv"]:
                return DownloadResult(
                    success=True,
                    video_path=candidate,
                    video_info=_load_info_json(output_dir, candidate.stem),
                    logs=logs,
                )
        return DownloadResult(success=False, logs=logs, error="下载完成但未找到视频文件")
    error_msg = logs[-1] if logs else f"yt-dlp 退出码: {return_code}"
    return DownloadResult(success=False, logs=logs, error=error_msg)


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    except OSError:
        return


def _load_info_json(output_dir: Path, video_id: str) -> dict:
    info_file = output_dir / f"{video_id}.info.json"
    if info_file.exists():
        return json.loads(info_file.read_text())
    return {}
