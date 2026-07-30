import subprocess
import sys
import time

from services import ffmpeg_runner


def _use_python_process(monkeypatch):
    monkeypatch.setattr(ffmpeg_runner, "with_ffmpeg_progress", lambda command: list(command))
    monkeypatch.setattr(ffmpeg_runner, "FFMPEG_POLL_INTERVAL_SECONDS", 0.02)


def test_active_ffmpeg_output_is_not_limited_by_total_runtime(monkeypatch, tmp_path):
    _use_python_process(monkeypatch)
    output = tmp_path / "output.part"
    script = (
        "import pathlib, time\n"
        f"output = pathlib.Path({str(output)!r})\n"
        "for index in range(7):\n"
        " output.open('ab').write(b'video')\n"
        " print(f'out_time_us={index * 1000000}', flush=True)\n"
        " print('speed=1.0x', flush=True)\n"
        " print('progress=continue', flush=True)\n"
        " time.sleep(0.06)\n"
        "print('progress=end', flush=True)\n"
    )
    updates = []

    result = ffmpeg_runner.run_ffmpeg(
        [sys.executable, "-u", "-c", script],
        output_path=output,
        duration_seconds=6,
        progress_callback=updates.append,
        activity_timeout_seconds=0.12,
    )

    assert result.success is True
    assert result.stalled is False
    assert output.stat().st_size == 35
    assert updates[-1].percent == 100


def test_silent_ffmpeg_is_stopped_after_activity_window(monkeypatch, tmp_path):
    _use_python_process(monkeypatch)
    started = time.monotonic()

    result = ffmpeg_runner.run_ffmpeg(
        [sys.executable, "-u", "-c", "import time; time.sleep(5)"],
        output_path=tmp_path / "output.part",
        activity_timeout_seconds=0.1,
    )

    assert result.success is False
    assert result.stalled is True
    assert time.monotonic() - started < 2


def test_ffmpeg_runner_stops_promptly_when_task_is_cancelled(monkeypatch, tmp_path):
    _use_python_process(monkeypatch)

    result = ffmpeg_runner.run_ffmpeg(
        [sys.executable, "-u", "-c", "import time; time.sleep(5)"],
        output_path=tmp_path / "output.part",
        cancel_check=lambda: True,
    )

    assert result.success is False
    assert result.cancelled is True


def test_ffmpeg_runner_preserves_non_progress_error_output(monkeypatch, tmp_path):
    _use_python_process(monkeypatch)

    result = ffmpeg_runner.run_ffmpeg(
        [sys.executable, "-u", "-c", "print('invalid stream', flush=True); raise SystemExit(1)"],
        output_path=tmp_path / "output.part",
    )

    assert result.success is False
    assert result.returncode == 1
    assert "invalid stream" in result.stderr
