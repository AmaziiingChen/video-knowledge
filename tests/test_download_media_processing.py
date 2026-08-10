from __future__ import annotations

from types import SimpleNamespace

from services import download_media_processing


def test_probe_video_codec_normalizes_ffprobe_output(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    monkeypatch.setattr(
        download_media_processing.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=" H264\n"),
    )

    assert download_media_processing.probe_video_codec(video_path) == "h264"


def test_video_validation_requires_a_codec_positive_duration_and_media_container(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    monkeypatch.setattr(download_media_processing, "probe_video_codec", lambda _path: "h264")
    payloads = iter([
        '{"format":{"format_name":"mov,mp4","duration":"12.5"}}',
        '{"format":{"format_name":"jpeg_pipe","duration":"12.5"}}',
        '{"format":{"format_name":"mov,mp4","duration":"0"}}',
    ])
    monkeypatch.setattr(
        download_media_processing.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=next(payloads)),
    )

    assert download_media_processing.is_valid_video_file(video_path) is True
    assert download_media_processing.is_valid_video_file(video_path) is False
    assert download_media_processing.is_valid_video_file(video_path) is False


def test_browser_playable_conversion_skips_existing_h264_without_touching_ffmpeg(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"media")
    monkeypatch.setattr(download_media_processing, "probe_video_codec", lambda _path: "h264")
    monkeypatch.setattr(
        download_media_processing,
        "run_ffmpeg",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("ffmpeg must not run")),
    )

    logs = []
    assert download_media_processing.ensure_browser_playable_mp4(video_path, logs) == video_path
    assert logs == []


def test_failed_browser_conversion_removes_partial_output_and_preserves_source(monkeypatch, tmp_path):
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"source")
    temp_path = tmp_path / "video_h264_tmp.mp4"
    monkeypatch.setattr(download_media_processing, "probe_video_codec", lambda _path: "hevc")
    monkeypatch.setattr(download_media_processing, "probe_media_duration", lambda _path: 20.0)

    def fail_conversion(_cmd, *, output_path, **_kwargs):
        output_path.write_bytes(b"partial")
        return SimpleNamespace(success=False, cancelled=False, stalled=False, stderr="codec failure")

    monkeypatch.setattr(download_media_processing, "run_ffmpeg", fail_conversion)
    logs = []

    assert download_media_processing.ensure_browser_playable_mp4(video_path, logs) == video_path
    assert video_path.read_bytes() == b"source"
    assert not temp_path.exists()
    assert "codec failure" in logs[-1]
