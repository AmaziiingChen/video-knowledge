from __future__ import annotations

import json
import subprocess
from pathlib import Path

from config import settings
from services.download_contracts import CancelCheck, ProgressCallback, report_phase
from services.ffmpeg_runner import FfmpegProgress, probe_media_duration, run_ffmpeg
from services.media_tools import resolve_tool


def ensure_browser_playable_mp4(
    video_path: Path,
    logs: list[str],
    *,
    cancel_check: CancelCheck | None = None,
) -> Path:
    codec = probe_video_codec(video_path)
    if codec in {"h264", "avc1"}:
        return video_path

    temp_path = video_path.with_name(f"{video_path.stem}_h264_tmp.mp4")
    temp_path.unlink(missing_ok=True)
    logs.append(f"[兼容] 当前视频编码为 {codec or '未知'}，转换为 H.264 以支持内嵌播放器...")
    cmd = [
        resolve_tool("ffmpeg") or "ffmpeg",
        "-y", "-i", str(video_path),
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-vf", "scale=-2:min(1080\\,ih)",
        "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(temp_path),
    ]
    try:
        result = run_ffmpeg(
            cmd,
            output_path=temp_path,
            duration_seconds=probe_media_duration(video_path),
            cancel_check=cancel_check,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[兼容] 转码异常，保留原视频: {exc}")
        return video_path

    if result.cancelled:
        temp_path.unlink(missing_ok=True)
        logs.append("[兼容] 转码已取消，保留原视频")
        return video_path
    if result.stalled:
        temp_path.unlink(missing_ok=True)
        logs.append("[兼容] 转码连续 5 分钟没有进度，保留原视频")
        return video_path
    if not result.success or not temp_path.exists() or temp_path.stat().st_size <= 10000:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[兼容] 转码失败，保留原视频: {result.stderr[-200:]}")
        return video_path

    temp_path.replace(video_path)
    logs.append("[兼容] 已生成 H.264 播放版本")
    return video_path


def probe_video_codec(video_path: Path) -> str | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name", "-of", "default=nw=1:nk=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip().lower() or None


def is_valid_video_file(video_path: Path) -> bool:
    if not probe_video_codec(video_path):
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=format_name,duration",
                "-of", "json", str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
        format_name = str(payload.get("format", {}).get("format_name") or "")
        duration = float(payload.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return duration > 0 and not format_name.startswith("jpeg_pipe")


def compress_video_for_storage(
    video_path: Path,
    logs: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> Path:
    if not settings.compress_downloaded_video:
        return video_path
    if not video_path.exists() or video_path.stat().st_size <= 10000:
        return video_path

    original_size = video_path.stat().st_size
    temp_path = video_path.with_name(f"{video_path.stem}_compact_tmp.mp4")
    final_path = video_path.with_name(f"{video_path.stem}_compact.mp4")
    temp_path.unlink(missing_ok=True)
    cmd = [
        resolve_tool("ffmpeg") or "ffmpeg",
        "-y", "-i", str(video_path),
        "-map", "0:v:0", "-map", "0:a?",
        "-vf", (
            f"scale=-2:min({settings.storage_video_max_height}\\,ih),"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        ),
        "-c:v", "libx264", "-preset", settings.storage_video_preset,
        "-crf", str(settings.storage_video_crf), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
        str(temp_path),
    ]

    logs.append(f"[压缩] 降低视频画质到约 {settings.storage_video_max_height}p，音频保留原码流...")

    def report_compression_progress(progress: FfmpegProgress) -> None:
        detail = "正在压缩视频缓存"
        if progress.percent is not None:
            detail += f"（{progress.percent:.0f}%）"
        report_phase(progress_callback, "caching", detail)

    try:
        result = run_ffmpeg(
            cmd,
            output_path=temp_path,
            duration_seconds=probe_media_duration(video_path),
            progress_callback=report_compression_progress,
            cancel_check=cancel_check,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[压缩] ffmpeg 异常，保留原视频: {exc}")
        return video_path
    if result.cancelled:
        temp_path.unlink(missing_ok=True)
        logs.append("[压缩] 已取消，保留原视频")
        return video_path
    if result.stalled:
        temp_path.unlink(missing_ok=True)
        logs.append("[压缩] ffmpeg 连续 5 分钟没有进度，保留原视频")
        return video_path
    if not result.success or not temp_path.exists() or temp_path.stat().st_size <= 10000:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[压缩] 失败，保留原视频: {result.stderr[-200:]}")
        return video_path

    compressed_size = temp_path.stat().st_size
    if compressed_size >= original_size:
        temp_path.unlink(missing_ok=True)
        logs.append("[压缩] 原视频已足够小，保留原文件")
        return video_path

    final_path.unlink(missing_ok=True)
    temp_path.replace(final_path)
    if final_path != video_path:
        video_path.unlink(missing_ok=True)
    saved_mb = (original_size - compressed_size) / 1024 / 1024
    logs.append(f"[压缩] 完成，节省约 {saved_mb:.1f}MB")
    return final_path
