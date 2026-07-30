from contextlib import nullcontext
import subprocess
import sys
import time

from services.downloader import (
    DownloadResult,
    _activity_timeout_error,
    _download_bilibili,
    _download_bilibili_with_cookie_args,
)


def test_active_download_is_not_killed_after_ten_minutes():
    error = _activity_timeout_error(
        now=601,
        last_activity_at=590,
        stall_seconds=300,
        operation="yt-dlp",
    )

    assert error is None


def test_download_is_stopped_only_after_the_activity_window_expires():
    error = _activity_timeout_error(
        now=601,
        last_activity_at=300,
        stall_seconds=300,
        operation="yt-dlp",
    )

    assert error == "yt-dlp 连续 5 分钟没有新的进度或输出"


def test_activity_timeout_message_keeps_non_minute_windows_readable():
    error = _activity_timeout_error(
        now=421,
        last_activity_at=0,
        stall_seconds=420,
        operation="浏览器下载",
    )

    assert error == "浏览器下载连续 7 分钟没有新的进度或输出"


def test_bilibili_yt_dlp_path_receives_the_task_cancel_callback(monkeypatch, tmp_path):
    cancel_check = lambda: False
    captured = {}

    monkeypatch.setattr(
        "services.downloader.bilibili_yt_dlp_cookie_args",
        lambda: nullcontext([]),
    )

    def download_with_ytdlp(_url, _output_dir, _progress_callback, _cookie_args, callback):
        captured["cancel_check"] = callback
        return DownloadResult(success=True)

    monkeypatch.setattr(
        "services.downloader._download_bilibili_with_cookie_args",
        download_with_ytdlp,
    )

    result = _download_bilibili(
        "https://www.bilibili.com/video/BV1test",
        tmp_path,
        cancel_check=cancel_check,
    )

    assert result.success is True
    assert captured["cancel_check"] is cancel_check


def test_cancelled_yt_dlp_download_does_not_start_a_fallback_request(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.downloader.bilibili_yt_dlp_cookie_args",
        lambda: nullcontext([]),
    )
    monkeypatch.setattr(
        "services.downloader._download_bilibili_with_cookie_args",
        lambda *_args, **_kwargs: DownloadResult(success=False, error="下载已取消"),
    )
    monkeypatch.setattr(
        "services.downloader._download_bilibili_progressive",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("不应启动兜底下载")),
    )

    result = _download_bilibili(
        "https://www.bilibili.com/video/BV1test",
        tmp_path,
        cancel_check=lambda: True,
    )

    assert result.error == "下载已取消"


def test_yt_dlp_process_can_run_past_the_stall_window_while_output_advances(monkeypatch, tmp_path):
    real_popen = subprocess.Popen
    target = tmp_path / "validation.mp4"
    target.write_bytes(b"video")

    def launch_progress_process(*_args, **_kwargs):
        return real_popen(
            [
                sys.executable,
                "-u",
                "-c",
                "import time\nfor i in range(7):\n print(f'[download] {i * 10}% at 1MiB/s', flush=True)\n time.sleep(0.08)",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    monkeypatch.setattr("services.downloader.subprocess.Popen", launch_progress_process)
    monkeypatch.setattr("services.downloader.YTDLP_ACTIVITY_TIMEOUT_SECONDS", 0.25)

    result = _download_bilibili_with_cookie_args(
        "https://www.bilibili.com/video/BV1test",
        tmp_path,
        None,
        [],
    )

    assert result.success is True
    assert len(result.logs) == 7


def test_yt_dlp_process_can_run_silently_while_its_output_file_advances(monkeypatch, tmp_path):
    real_popen = subprocess.Popen
    target = tmp_path / "silent-progress.mp4"

    def launch_silent_writer(*_args, **_kwargs):
        script = (
            "import pathlib, time\n"
            f"target = pathlib.Path({str(target)!r})\n"
            "for _ in range(7):\n"
            " target.open('ab').write(b'video')\n"
            " time.sleep(0.08)\n"
        )
        return real_popen(
            [sys.executable, "-u", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    monkeypatch.setattr("services.downloader.subprocess.Popen", launch_silent_writer)
    monkeypatch.setattr("services.downloader.YTDLP_ACTIVITY_TIMEOUT_SECONDS", 0.25)

    result = _download_bilibili_with_cookie_args(
        "https://www.bilibili.com/video/BV1test",
        tmp_path,
        None,
        [],
    )

    assert result.success is True
    assert target.stat().st_size == 35


def test_yt_dlp_process_is_stopped_after_real_inactivity(monkeypatch, tmp_path):
    real_popen = subprocess.Popen

    def launch_stalled_process(*_args, **_kwargs):
        return real_popen(
            [sys.executable, "-u", "-c", "import time; time.sleep(5)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    monkeypatch.setattr("services.downloader.subprocess.Popen", launch_stalled_process)
    monkeypatch.setattr("services.downloader.YTDLP_ACTIVITY_TIMEOUT_SECONDS", 0.1)
    started = time.monotonic()

    result = _download_bilibili_with_cookie_args(
        "https://www.bilibili.com/video/BV1test",
        tmp_path,
        None,
        [],
    )

    assert result.success is False
    assert "没有新的进度或输出" in result.error
    assert time.monotonic() - started < 2
