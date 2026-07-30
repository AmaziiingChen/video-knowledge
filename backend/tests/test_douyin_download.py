from pathlib import Path

import httpx

from services import downloader
from services.downloader import DownloadResult
from services.http_media_download import (
    HttpMediaDownloadResult,
    download_browser_context_media,
    download_http_media,
)


def _detail_payload() -> dict:
    return {
        "item_list": [
            {
                "aweme_id": "123",
                "video": {
                    "bit_rate": [
                        {"bit_rate": 600_000, "gear_name": "540p", "play_addr": {"url_list": ["https://cdn.example/low"]}},
                        {"bit_rate": 1_600_000, "gear_name": "720p", "play_addr": {"url_list": ["https://cdn.example/standard"]}},
                        {"bit_rate": 3_200_000, "gear_name": "1080p", "play_addr": {"url_list": ["https://cdn.example/high"]}},
                    ]
                },
            }
        ]
    }


def test_douyin_quality_selection_uses_explicit_policy():
    payload = _detail_payload()

    assert downloader._select_douyin_video_variant(payload, "123", "low")[0].endswith("/low")
    assert downloader._select_douyin_video_variant(payload, "123", "standard")[0].endswith("/standard")
    assert downloader._select_douyin_video_variant(payload, "123", "high")[0].endswith("/high")


def test_short_link_expansion_extracts_canonical_video_id(monkeypatch):
    client_options = {}

    class FakeClient:
        def __init__(self, **kwargs):
            client_options.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return type("Response", (), {"url": "https://www.douyin.com/video/123"})()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    assert downloader._extract_douyin_video_id("https://v.douyin.com/example/") == "123"
    assert client_options["trust_env"] is False


def test_short_link_uses_browser_provider_when_direct_expansion_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(downloader, "_extract_douyin_video_id", lambda _url: None)
    monkeypatch.setattr(downloader, "_extract_douyin_video_id_via_browser", lambda _url: "123")
    monkeypatch.setattr(
        downloader,
        "_download_douyin_via_public_metadata",
        lambda *_args: DownloadResult(success=False, error="直连元数据未提供可用视频地址"),
    )
    monkeypatch.setattr(
        downloader,
        "_download_douyin_via_browser",
        lambda _video_id, _output_dir, logs, *_args: DownloadResult(success=True, logs=logs),
    )

    result = downloader._download_douyin("https://v.douyin.com/example/", tmp_path)

    assert result.success
    assert any("切换项目内浏览器" in message for message in result.logs)


def test_signed_media_expiry_is_retryable():
    assert downloader._needs_douyin_media_refresh(401)
    assert downloader._needs_douyin_media_refresh(403)
    assert not downloader._needs_douyin_media_refresh(500)


def test_media_transfer_error_keeps_http_status_for_cookie_diagnosis():
    transfer = HttpMediaDownloadResult(
        success=False,
        path=Path("/tmp/video.part"),
        downloaded_bytes=0,
        total_bytes=None,
        status_code=403,
        error="Forbidden",
    )

    assert downloader._media_transfer_error(transfer) == "HTTP 403: Forbidden"


def test_cancelled_direct_attempt_does_not_start_browser(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(downloader, "_extract_douyin_video_id", lambda _: "123")
    monkeypatch.setattr(
        downloader,
        "_download_douyin_via_public_metadata",
        lambda *_: DownloadResult(success=False, error="下载已取消"),
    )
    browser_started = False

    def browser(*_args, **_kwargs):
        nonlocal browser_started
        browser_started = True
        return DownloadResult(success=True)

    monkeypatch.setattr(downloader, "_download_douyin_via_browser", browser)

    result = downloader._download_douyin("https://v.douyin.com/example", tmp_path)

    assert not result.success
    assert result.error == "下载已取消"
    assert not browser_started


def test_direct_failure_falls_back_to_browser(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(downloader, "_extract_douyin_video_id", lambda _: "123")
    monkeypatch.setattr(
        downloader,
        "_download_douyin_via_public_metadata",
        lambda *_: DownloadResult(success=False, error="直连元数据未提供可用视频地址"),
    )
    def browser(_video_id, _output_dir, logs, *_args):
        return DownloadResult(success=True, video_info={"title": "浏览器兜底"}, logs=logs)

    monkeypatch.setattr(downloader, "_download_douyin_via_browser", browser)

    result = downloader._download_douyin("https://v.douyin.com/example", tmp_path)

    assert result.success
    assert result.video_info == {"id": "123", "title": "浏览器兜底", "platform": "douyin"}
    assert any("切换项目内浏览器" in message for message in result.logs)


def test_douyin_provider_milestones_are_reported_while_running(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(downloader, "_extract_douyin_video_id", lambda _: "123")
    monkeypatch.setattr(
        downloader,
        "_download_douyin_via_public_metadata",
        lambda *_args: DownloadResult(success=False, error="直连元数据未提供可用视频地址"),
    )

    def browser(_video_id, _output_dir, logs, _progress, _cancel, log_callback):
        log_callback("[浏览器] 页面首帧已打开，等待播放器发起媒体请求...")
        logs.append("[浏览器] 页面首帧已打开，等待播放器发起媒体请求...")
        return DownloadResult(success=False, logs=logs, error="浏览器未捕获媒体")

    monkeypatch.setattr(downloader, "_download_douyin_via_browser", browser)
    milestones: list[str] = []

    result = downloader._download_douyin(
        "https://v.douyin.com/example",
        tmp_path,
        log_callback=milestones.append,
    )

    assert not result.success
    assert any("短链展开" in message for message in milestones)
    assert any("切换项目内浏览器" in message for message in milestones)
    assert any("页面首帧已打开" in message for message in milestones)


def test_browser_watchdog_allows_two_stream_transfer_and_merge():
    assert downloader.DOUYIN_BROWSER_WATCHDOG_SECONDS >= 360


def test_playback_trigger_never_waits_for_the_page_play_promise():
    scripts: list[str] = []

    class Page:
        def evaluate(self, script):
            scripts.append(script)

    downloader._trigger_douyin_playback(Page())

    assert len(scripts) == 1
    assert "video.play()" in scripts[0]
    assert "playAttempt.catch" in scripts[0]
    assert "await" not in scripts[0]


def test_http_media_cancellation_preserves_partial_file(tmp_path: Path):
    destination = tmp_path / "video.part"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, headers={"content-length": "6"}, content=b"abcdef")
    )
    with httpx.Client(transport=transport) as client:
        result = download_http_media(
            "https://cdn.example/video",
            destination,
            client=client,
            cancel_check=lambda: True,
        )

    assert not result.success
    assert result.error == "下载已取消"
    assert destination.exists()
    assert destination.read_bytes() == b""


def test_browser_context_media_cancellation_preserves_partial_file(tmp_path: Path):
    destination = tmp_path / "video.part"
    destination.write_bytes(b"partial")

    class RequestContext:
        def get(self, *_args, **_kwargs):
            raise AssertionError("cancelled downloads must not start another browser request")

    result = download_browser_context_media(
        RequestContext(),
        "https://cdn.example/video",
        destination,
        cancel_check=lambda: True,
    )

    assert not result.success
    assert result.error == "下载已取消"
    assert destination.exists()
    assert destination.read_bytes() == b"partial"


def test_http_media_resumes_existing_partial_file(tmp_path: Path):
    destination = tmp_path / "video.part"
    destination.write_bytes(b"abc")

    def response_for(request: httpx.Request):
        assert request.headers["Range"] == "bytes=3-"
        return httpx.Response(206, headers={"content-range": "bytes 3-5/6"}, content=b"def")

    with httpx.Client(transport=httpx.MockTransport(response_for)) as client:
        result = download_http_media("https://cdn.example/video", destination, client=client)

    assert result.success
    assert result.resumed_from_bytes == 3
    assert destination.read_bytes() == b"abcdef"


def test_direct_provider_accepts_progressive_video_without_separate_audio(monkeypatch, tmp_path: Path):
    client_options = {}

    class FakeClient:
        def __init__(self, **kwargs):
            client_options.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return type("Response", (), {"status_code": 200, "json": lambda _self: _detail_payload()})()

    target = tmp_path / "123.direct.part"
    target.write_bytes(b"progressive-media")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(downloader, "_load_douyin_video_quality", lambda: "standard")
    monkeypatch.setattr(
        downloader,
        "download_http_media",
        lambda *_args, **_kwargs: HttpMediaDownloadResult(True, target, len(target.read_bytes()), len(target.read_bytes())),
    )
    monkeypatch.setattr(downloader, "_is_valid_video_file", lambda _path: True)
    monkeypatch.setattr(downloader, "_compress_video_for_storage", lambda path, _logs, **_kwargs: path)

    result = downloader._download_douyin_via_public_metadata("123", tmp_path, [], None, None)

    assert result.success
    assert result.video_path == tmp_path / "123.mp4"
    assert client_options["trust_env"] is False
