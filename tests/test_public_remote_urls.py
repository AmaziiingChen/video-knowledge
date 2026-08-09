from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services import article_fetcher, paddle_ocr, public_url


def _dns_answer(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


class _Response:
    def __init__(self, *, content: bytes = b"", text: str = "", headers: dict[str, str] | None = None):
        self.content = content
        self.text = text
        self.headers = headers or {}
        self.is_redirect = "location" in {key.lower() for key in self.headers}
        self.closed = False

    def raise_for_status(self):
        return None

    def close(self):
        self.closed = True


class _PinnedSession:
    def __init__(self, target, respond):
        self.target = target
        self._respond = respond
        self.closed = False

    def get(self, url, **_kwargs):
        return self._respond(url)

    def close(self):
        self.closed = True


def test_public_url_rejects_any_private_dns_answer(monkeypatch):
    monkeypatch.setattr(public_url.socket, "getaddrinfo", lambda *_args, **_kwargs: _dns_answer("93.184.216.34") + _dns_answer("127.0.0.1"))

    with pytest.raises(ValueError, match="不可访问"):
        public_url.ensure_public_http_url(
            "https://mixed.example/article",
            invalid_message="链接无效",
            blocked_message="链接不可访问",
        )


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://[::1]/admin",
    "http://169.254.169.254/latest/meta-data",
    "http://224.0.0.1/stream",
    "http://0.0.0.0/",
])
def test_public_url_rejects_non_public_ip_literals(url):
    with pytest.raises(ValueError, match="不可访问"):
        public_url.ensure_public_http_url(
            url,
            invalid_message="链接无效",
            blocked_message="链接不可访问",
        )


def test_public_url_accepts_public_ipv4_and_ipv6_dns_answers(monkeypatch):
    monkeypatch.setattr(
        public_url.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _dns_answer("93.184.216.34") + _dns_answer("2606:2800:220:1:248:1893:25c8:1946"),
    )

    assert public_url.ensure_public_http_url(
        "https://public.example/article",
        invalid_message="链接无效",
        blocked_message="链接不可访问",
    ) == "https://public.example/article"


def test_rss_redirect_target_is_resolved_and_blocked_before_request(monkeypatch):
    requested: list[str] = []
    targets = []

    def resolve(host, *_args, **_kwargs):
        return _dns_answer("93.184.216.34" if host == "public.example" else "127.0.0.1")

    def open_session(target, **_kwargs):
        targets.append(target)

        def respond(url):
            requested.append(url)
            return _Response(headers={"location": "http://private.example/admin"})

        return _PinnedSession(target, respond)

    monkeypatch.setattr(public_url.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(public_url, "_new_pinned_curl_session", open_session)

    with pytest.raises(ValueError, match="RSS 原文链接不可访问"):
        article_fetcher._fetch_rss_article_html("https://public.example/start")

    assert requested == ["https://public.example/start"]
    assert targets[0].addresses == ("93.184.216.34",)


def test_request_pins_validated_dns_answer_without_a_second_lookup(monkeypatch):
    calls = 0
    targets = []

    def resolve(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _dns_answer("93.184.216.34")
        return _dns_answer("127.0.0.1")

    def open_session(target, **_kwargs):
        targets.append(target)
        return _PinnedSession(target, lambda _url: _Response(text="ok"))

    monkeypatch.setattr(public_url.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(public_url, "_new_pinned_curl_session", open_session)

    response, final_url = public_url.get_public_http_response(
        "https://rebind.example/document",
        invalid_message="链接无效",
        blocked_message="链接不可访问",
        redirect_invalid_message="重定向无效",
        redirect_limit_message="重定向过多",
        max_redirects=5,
    )

    assert final_url == "https://rebind.example/document"
    assert response.text == "ok"
    response.close()
    assert calls == 1
    assert targets[0].addresses == ("93.184.216.34",)


def test_curl_resolve_rule_keeps_public_ipv6_addresses_pinned():
    target = public_url._PublicHttpTarget(
        url="https://public.example/document",
        host="public.example",
        port=443,
        addresses=("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )

    assert public_url._curl_resolve_rule(target) == (
        "public.example:443:93.184.216.34,[2606:2800:220:1:248:1893:25c8:1946]"
    )


def test_paddle_image_redirect_target_is_resolved_and_blocked_before_request(monkeypatch):
    requested: list[str] = []

    def resolve(host, *_args, **_kwargs):
        return _dns_answer("93.184.216.34" if host == "public.example" else "::1")

    def open_session(target, **_kwargs):
        def respond(url):
            requested.append(url)
            return _Response(headers={"location": "https://private.example/image.png"})

        return _PinnedSession(target, respond)

    monkeypatch.setattr(public_url.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(public_url, "_new_pinned_curl_session", open_session)

    with pytest.raises(ValueError, match="图片地址不可访问"):
        paddle_ocr._download_image("https://public.example/image.png", article_url="https://mp.weixin.qq.com/s/example")

    assert requested == ["https://public.example/image.png"]


def test_paddle_result_download_preserves_public_redirect_behavior(monkeypatch):
    requested: list[str] = []

    def open_session(target, **_kwargs):
        def respond(url):
            requested.append(url)
            if url.endswith("/result"):
                return _Response(headers={"location": "/result-final"})
            return _Response(text="# 已识别内容")

        return _PinnedSession(target, respond)

    monkeypatch.setattr(public_url.socket, "getaddrinfo", lambda *_args, **_kwargs: _dns_answer("93.184.216.34"))
    monkeypatch.setattr(public_url, "_new_pinned_curl_session", open_session)

    assert paddle_ocr._download_markdown("https://result.example/result") == "# 已识别内容"
    assert requested == ["https://result.example/result", "https://result.example/result-final"]
