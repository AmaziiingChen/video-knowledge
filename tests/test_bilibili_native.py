import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.bilibili_native import resolve_progressive_media
from services.bilibili_native import BilibiliProgressiveMedia
from services.http_media_download import HttpMediaDownloadResult
from services.downloader import _download_bilibili_progressive


def test_resolves_single_progressive_stream(monkeypatch):
    monkeypatch.setattr("services.bilibili_native.bilibili_playwright_cookies", lambda: [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/view"):
            return httpx.Response(200, json={"code": 0, "data": {"cid": 12, "title": "测试视频"}})
        assert request.url.path.endswith("/playurl")
        assert request.url.params["cid"] == "12"
        return httpx.Response(200, json={"code": 0, "data": {"durl": [{"url": "https://cdn.example/video.mp4"}]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        media = resolve_progressive_media("https://www.bilibili.com/video/BV1xx411c7mD", client=client)

    assert media.bvid == "BV1xx411c7mD"
    assert media.cid == 12
    assert media.url == "https://cdn.example/video.mp4"


def test_rejects_segmented_stream_instead_of_saving_an_incomplete_video(monkeypatch):
    monkeypatch.setattr("services.bilibili_native.bilibili_playwright_cookies", lambda: [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/view"):
            return httpx.Response(200, json={"code": 0, "data": {"cid": 12}})
        return httpx.Response(200, json={"code": 0, "data": {"durl": [{"url": "one"}, {"url": "two"}]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="分段或 DASH"):
            resolve_progressive_media("https://www.bilibili.com/video/BV1xx411c7mD", client=client)


def test_resolves_the_requested_bilibili_part(monkeypatch):
    monkeypatch.setattr("services.bilibili_native.bilibili_playwright_cookies", lambda: [])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/view"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "title": "分 P 视频",
                        "pages": [
                            {"cid": 11, "part": "第一集"},
                            {"cid": 22, "part": "第二集"},
                        ],
                    },
                },
            )
        assert request.url.path.endswith("/playurl")
        assert request.url.params["cid"] == "22"
        return httpx.Response(200, json={"code": 0, "data": {"durl": [{"url": "https://cdn.example/p2.mp4"}]}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        media = resolve_progressive_media("https://www.bilibili.com/video/BV1xx411c7mD?p=2", client=client)

    assert media.cid == 22
    assert media.page_number == 2
    assert media.title == "分 P 视频 · P2 第二集"
    assert media.url == "https://cdn.example/p2.mp4"


def test_native_download_uses_the_shared_transfer_service(tmp_path: Path, monkeypatch):
    source = BilibiliProgressiveMedia("BV1xx411c7mD", 12, "测试视频", "https://cdn.example/video.mp4", {"Referer": "x"})
    target = tmp_path / "BV1xx411c7mD.native.part"

    monkeypatch.setattr("services.bilibili_download.resolve_progressive_media", lambda _url: source)

    def download(_url, path, **_kwargs):
        path.write_bytes(b"video")
        return HttpMediaDownloadResult(True, path, 5, 5)

    monkeypatch.setattr("services.bilibili_download.download_http_media", download)
    monkeypatch.setattr("services.bilibili_download.is_valid_video_file", lambda _path: True)

    result = _download_bilibili_progressive("https://www.bilibili.com/video/BV1xx411c7mD", tmp_path, None)

    assert result.success
    assert result.video_path == tmp_path / "BV1xx411c7mD.mp4"
    assert result.video_path.read_bytes() == b"video"
    assert result.video_info["page_number"] == 1
    assert not target.exists()
