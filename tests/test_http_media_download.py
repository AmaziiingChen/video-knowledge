import sys
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.http_media_download import download_browser_context_media, download_http_media


def test_downloads_media_and_reports_progress(tmp_path: Path):
    progress: list[tuple[int, int | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("range") is None
        return httpx.Response(200, headers={"content-length": "6"}, content=b"abcdef")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_http_media(
            "https://media.example/video.mp4",
            tmp_path / "video.part",
            client=client,
            progress_callback=lambda downloaded, total: progress.append((downloaded, total)),
        )

    assert result.success
    assert result.downloaded_bytes == 6
    assert (tmp_path / "video.part").read_bytes() == b"abcdef"
    assert progress[-1] == (6, 6)


def test_resumes_when_server_accepts_range(tmp_path: Path):
    target = tmp_path / "video.part"
    target.write_bytes(b"abc")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=3-"
        return httpx.Response(206, headers={"content-range": "bytes 3-5/6"}, content=b"def")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_http_media("https://media.example/video.mp4", target, client=client)

    assert result.success
    assert result.resumed_from_bytes == 3
    assert target.read_bytes() == b"abcdef"


def test_restarts_if_server_ignores_range(tmp_path: Path):
    target = tmp_path / "video.part"
    target.write_bytes(b"stale")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=5-"
        return httpx.Response(200, headers={"content-length": "3"}, content=b"new")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = download_http_media("https://media.example/video.mp4", target, client=client)

    assert result.success
    assert result.resumed_from_bytes == 0
    assert target.read_bytes() == b"new"


def test_browser_context_transfer_keeps_media_in_bounded_range_requests(tmp_path: Path):
    class BrowserResponse:
        status = 206
        status_text = "Partial Content"

        def __init__(self, payload: bytes, content_range: str):
            self._payload = payload
            self.headers = {"content-range": content_range}

        def body(self):
            return self._payload

    class BrowserRequestContext:
        def __init__(self):
            self.ranges: list[str] = []

        def get(self, _url, *, headers, **_kwargs):
            current_range = headers["Range"]
            self.ranges.append(current_range)
            if current_range == "bytes=0-2":
                return BrowserResponse(b"abc", "bytes 0-2/6")
            return BrowserResponse(b"def", "bytes 3-5/6")

    context = BrowserRequestContext()
    result = download_browser_context_media(
        context,
        "https://cdn.example/video.mp4",
        tmp_path / "video.part",
        chunk_size=3,
    )

    assert result.success
    assert context.ranges == ["bytes=0-2", "bytes=3-5"]
    assert (tmp_path / "video.part").read_bytes() == b"abcdef"
