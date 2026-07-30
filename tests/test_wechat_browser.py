from __future__ import annotations

import sys
from types import ModuleType
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from services import wechat_browser


class StubResponse:
    def __init__(self, text: str = "<html>正文</html>") -> None:
        self.text = text


def test_fetch_wechat_page_uses_requests_when_chrome_transport_is_unavailable(monkeypatch):
    response = StubResponse()
    calls = []

    class StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *args, **kwargs):
            calls.append((args, kwargs))
            return response

    monkeypatch.setattr(wechat_browser, "direct_requests_session", StubSession)
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", None)

    assert wechat_browser.fetch_wechat_page("https://mp.weixin.qq.com/s/example") is response
    assert calls[0][1]["headers"]["Referer"] == "https://mp.weixin.qq.com/"


def test_fetch_wechat_page_prefers_bundled_chrome_transport(monkeypatch):
    response = StubResponse()
    calls = []

    class StubSession:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def get(self, *args, **kwargs):
            calls.append(("get", args, kwargs))
            return response

    curl_cffi = ModuleType("curl_cffi")
    curl_requests = ModuleType("curl_cffi.requests")
    curl_requests.Session = StubSession
    monkeypatch.setitem(sys.modules, "curl_cffi", curl_cffi)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", curl_requests)

    assert wechat_browser.fetch_wechat_page("https://mp.weixin.qq.com/s/example") is response
    assert calls[0] == ("init", {"impersonate": "chrome120", "trust_env": False})
    assert calls[1][2]["allow_redirects"] is True
