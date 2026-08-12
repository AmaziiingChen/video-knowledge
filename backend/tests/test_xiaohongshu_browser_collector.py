from __future__ import annotations

import json

import pytest
from services import xiaohongshu_browser_collector as collector


def test_cookie_header_parser_preserves_equals_and_rejects_line_breaks():
    assert collector.playwright_cookies_from_header("a=one=two; b=three") == [
        {"name": "a", "value": "one=two", "domain": ".xiaohongshu.com", "path": "/", "secure": True},
        {"name": "b", "value": "three", "domain": ".xiaohongshu.com", "path": "/", "secure": True},
    ]
    with pytest.raises(collector.XiaohongshuBrowserError, match="登录凭据"):
        collector.playwright_cookies_from_header("bad=one\r\ntwo")


def test_profile_parser_requires_a_non_guest_user_id():
    assert collector.parse_user_me_payload({"data": {"user_id": "user-1", "nickname": "小红"}}).state == "valid"
    assert collector.parse_user_me_payload({"data": {}}).state == "invalid"
    assert collector.parse_user_me_payload({"data": {"user_id": "guest", "guest": True}}).state == "invalid"


@pytest.mark.parametrize(
    "data",
    [
        {"item": {"note_card": {"id": "note-1", "title": "标题"}}},
        {"items": [{"noteCard": {"note_id": "note-1", "title": "标题"}}]},
        {"items": [{"noteCard": {"noteId": "note-1", "title": "标题", "interactInfo": []}}]},
    ],
)
def test_note_parser_accepts_data_item_and_ids_nested_in_the_card(data):
    note = collector.parse_note_info_payload({"data": data}, expected_note_id="note-1")
    assert note.note_id == "note-1"
    assert note.title == "标题"


def test_note_parser_rejects_a_response_for_another_note():
    with pytest.raises(collector.XiaohongshuBrowserError, match="当前链接不一致"):
        collector.parse_note_info_payload(
            {"data": {"item": {"note_card": {"id": "note-other", "title": "其他"}}}},
            expected_note_id="note-1",
        )


def test_note_parser_limits_remote_image_work():
    images = [{"url": f"https://images.example/{index}.jpg"} for index in range(100)]
    note = collector.parse_note_info_payload(
        {"data": {"item": {"note_card": {"id": "note-1", "image_list": images}}}},
        expected_note_id="note-1",
    )
    assert len(note.image_urls) == collector._MAX_NOTE_IMAGES


class _FakeRequest:
    def __init__(self, resource_type="fetch"):
        self.resource_type = resource_type


class _FakeResponse:
    def __init__(self, body: bytes, *, headers=None, url=None, status=200, resource_type="fetch"):
        self.url = url or "https://www.xiaohongshu.com/api/sns/h5/v1/note_info"
        self.status = status
        self.headers = headers if headers is not None else {"content-type": "application/json"}
        self.request = _FakeRequest(resource_type)
        self._body = body

    def body(self):
        return self._body


class _FakePage:
    def __init__(self, responses):
        self.responses = responses
        self.handler = None

    def on(self, event, handler):
        assert event == "response"
        self.handler = handler

    def goto(self, *_args, **_kwargs):
        for response in self.responses:
            self.handler(response)

    def wait_for_timeout(self, _timeout):
        return None


class _FakeContext:
    def __init__(self, responses):
        self.page = _FakePage(responses)
        self.closed = False
        self.cookies = None

    def add_cookies(self, cookies):
        self.cookies = cookies

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, responses):
        self.context = _FakeContext(responses)
        self.closed = False

    def new_context(self, **_kwargs):
        return self.context

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, **_kwargs):
        return self.browser


class _FakePlaywrightManager:
    def __init__(self, responses):
        self.browser = _FakeBrowser(responses)
        self.chromium = _FakeChromium(self.browser)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _observe(monkeypatch, responses, *, timeout_ms=2):
    manager = _FakePlaywrightManager(responses)
    monkeypatch.setattr(collector, "browser_executable", lambda: "/fake/chromium")
    result = collector._observe_page_response(
        "https://www.xiaohongshu.com/explore/note-1",
        raw_cookie="a=b",
        expected_path="/api/sns/h5/v1/note_info",
        timeout_ms=timeout_ms,
        playwright_factory=lambda: manager,
    )
    return result, manager


def test_observer_accepts_only_allowlisted_page_json_and_closes_browser(monkeypatch):
    ignored = _FakeResponse(
        b'{"ignored":true}',
        url="https://evil.example/api/sns/h5/v1/note_info",
    )
    payload = {"data": {"item": {"note_card": {"id": "note-1"}}}}
    result, manager = _observe(monkeypatch, [ignored, _FakeResponse(json.dumps(payload).encode())])
    assert result == payload
    assert manager.browser.context.closed is True
    assert manager.browser.closed is True


@pytest.mark.parametrize("content_length", [None, "12"])
def test_observer_rejects_oversize_actual_body_even_without_or_with_forged_length(monkeypatch, content_length):
    headers = {"content-type": "application/json"}
    if content_length is not None:
        headers["content-length"] = content_length
    response = _FakeResponse(b"{" + b" " * collector._MAX_RESPONSE_BYTES + b"}", headers=headers)
    with pytest.raises(collector.XiaohongshuBrowserError, match="未返回可读取数据"):
        _observe(monkeypatch, [response])


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(b'{}', url="https://www.xiaohongshu.com/api/sns/web/v2/user/me"),
        _FakeResponse(b'{}', resource_type="document"),
        _FakeResponse(b'{}', status=500),
        _FakeResponse(b'{}', headers={"content-type": "text/html"}),
    ],
    ids=["wrong-path", "wrong-resource", "non-2xx", "non-json"],
)
def test_observer_rejects_non_allowlisted_response_shapes(monkeypatch, response):
    with pytest.raises(collector.XiaohongshuBrowserError, match="未返回可读取数据"):
        _observe(monkeypatch, [response])


def test_observer_lock_wait_is_bounded(monkeypatch):
    class BusyLock:
        def acquire(self, *, timeout):
            assert timeout == collector._LOCK_TIMEOUT_SECONDS
            return False

    monkeypatch.setattr(collector, "browser_executable", lambda: "/fake/chromium")
    monkeypatch.setattr(collector, "_BROWSER_LOCK", BusyLock())
    with pytest.raises(collector.XiaohongshuBrowserError, match="正忙"):
        collector._observe_page_response(
            "https://www.xiaohongshu.com/explore/note-1",
            raw_cookie="a=b",
            expected_path="/api/sns/h5/v1/note_info",
            playwright_factory=lambda: None,
        )


def test_context_close_failure_still_closes_browser_and_releases_lock(monkeypatch):
    payload = {"data": {"item": {"note_card": {"id": "note-1"}}}}
    manager = _FakePlaywrightManager([_FakeResponse(json.dumps(payload).encode())])
    monkeypatch.setattr(collector, "browser_executable", lambda: "/fake/chromium")
    original_close = manager.browser.context.close

    def fail_close():
        original_close()
        raise RuntimeError("context path /private")

    monkeypatch.setattr(manager.browser.context, "close", fail_close)
    with pytest.raises(collector.XiaohongshuBrowserError, match="页面读取失败"):
        collector._observe_page_response(
            "https://www.xiaohongshu.com/explore/note-1",
            raw_cookie="a=b",
            expected_path="/api/sns/h5/v1/note_info",
            playwright_factory=lambda: manager,
        )
    assert manager.browser.closed is True
    assert collector._BROWSER_LOCK.acquire(blocking=False) is True
    collector._BROWSER_LOCK.release()


def test_client_never_reflects_browser_exception_details(tmp_path, monkeypatch):
    from config import settings
    from services import xiaohongshu_client

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("services.runtime_components.browser_executable", lambda: "/fake/chromium")
    (tmp_path / "xiaohongshu_cookie.txt").write_text("session=private-cookie", encoding="utf-8")

    def fail_probe(_cookie):
        raise collector.XiaohongshuBrowserError("xsec_token=secret /Users/private")

    monkeypatch.setattr(collector, "probe_xiaohongshu_session", fail_probe)
    status = xiaohongshu_client.xiaohongshu_cookie_status(probe=True)
    assert status["state"] == "unknown"
    assert "secret" not in status["detail"]
    assert "private" not in status["detail"]

    def fail_note(*_args, **_kwargs):
        raise collector.XiaohongshuBrowserError("session=private-cookie xsec_token=secret")

    monkeypatch.setattr(collector, "fetch_xiaohongshu_note", fail_note)
    with pytest.raises(xiaohongshu_client.XiaohongshuClientError) as error:
        xiaohongshu_client.fetch_note("https://www.xiaohongshu.com/explore/note-1")
    assert "secret" not in str(error.value)
    assert "private-cookie" not in str(error.value)


def test_client_maps_clean_room_note_and_passes_only_local_cookie_and_expected_id(tmp_path, monkeypatch):
    from config import settings
    from services import xiaohongshu_client

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("services.runtime_components.browser_executable", lambda: "/fake/chromium")
    (tmp_path / "xiaohongshu_cookie.txt").write_text("session=local-only", encoding="utf-8")
    observed = {}

    def fetch(url, *, raw_cookie, expected_note_id):
        observed.update(url=url, raw_cookie=raw_cookie, expected_note_id=expected_note_id)
        return collector.CollectedXiaohongshuNote(
            note_id="note-1",
            title="图文标题",
            author="作者",
            author_id="author-1",
            avatar_url="https://images.example/avatar.jpg",
            description="正文",
            image_urls=("https://images.example/1.jpg",),
            published_at_ms=1_700_000_000_000,
            tags=("标签",),
            stats={"liked": 3, "collected": 2, "comment": 1, "shared": 0},
            ip_location="上海",
        )

    monkeypatch.setattr(collector, "fetch_xiaohongshu_note", fetch)
    note = xiaohongshu_client.fetch_note(
        "https://www.xiaohongshu.com/explore/note-1?xsec_token=page-token"
    )

    assert observed["raw_cookie"] == "session=local-only"
    assert observed["expected_note_id"] == "note-1"
    assert observed["url"].startswith("https://www.xiaohongshu.com/explore/note-1")
    assert note.title == "图文标题"
    assert note.author_url.endswith("/author-1")
    assert note.description == "正文"
    assert note.comment_sample == ()
    assert note.comments_complete is False
    assert note.published_at
