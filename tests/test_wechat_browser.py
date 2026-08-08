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
    monkeypatch.setattr(wechat_browser, "_next_wechat_public_request_at", 0.0)
    monkeypatch.setattr(wechat_browser, "uniform", lambda _lower, _upper: 0.0)

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
    monkeypatch.setattr(wechat_browser, "_next_wechat_public_request_at", 0.0)
    monkeypatch.setattr(wechat_browser, "uniform", lambda _lower, _upper: 0.0)

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
    assert calls[1][2]["proxies"] == {"all": ""}


def test_fetch_wechat_page_applies_one_shared_jittered_interval(monkeypatch):
    response = StubResponse()
    clock = [100.0]
    waits = []
    ranges = []

    class StubSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, *_args, **_kwargs):
            return response

    def wait(seconds):
        waits.append(seconds)
        clock[0] += seconds

    def choose_interval(lower, upper):
        ranges.append((lower, upper))
        return 3.25

    monkeypatch.setattr(wechat_browser, "direct_requests_session", StubSession)
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", None)
    monkeypatch.setattr(wechat_browser, "_next_wechat_public_request_at", 0.0)
    monkeypatch.setattr(wechat_browser, "monotonic", lambda: clock[0])
    monkeypatch.setattr(wechat_browser, "sleep", wait)
    monkeypatch.setattr(wechat_browser, "uniform", choose_interval)

    wechat_browser.fetch_wechat_page("https://mp.weixin.qq.com/s/first")
    wechat_browser.fetch_wechat_page("https://mp.weixin.qq.com/s/second")

    assert waits == [3.25]
    assert ranges == [
        wechat_browser.WECHAT_PUBLIC_REQUEST_INTERVAL_RANGE,
        wechat_browser.WECHAT_PUBLIC_REQUEST_INTERVAL_RANGE,
    ]
