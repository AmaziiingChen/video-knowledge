import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.downloader import _browser_media_headers


def test_browser_media_headers_preserve_request_shape_without_cookie():
    headers = _browser_media_headers(
        {
            "user-agent": "browser",
            "referer": "https://www.douyin.com/",
            "cookie": "session=private",
            "host": "cdn.example",
            "content-length": "123",
        }
    )

    assert headers["user-agent"] == "browser"
    assert headers["referer"] == "https://www.douyin.com/"
    assert headers["accept-encoding"] == "identity"
    assert "cookie" not in headers
    assert "host" not in headers
