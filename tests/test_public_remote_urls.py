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

    def resolve(host, *_args, **_kwargs):
        return _dns_answer("93.184.216.34" if host == "public.example" else "127.0.0.1")

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, **_kwargs):
            requested.append(url)
            return _Response(headers={"location": "http://private.example/admin"})

    monkeypatch.setattr(public_url.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(article_fetcher.httpx, "Client", Client)

    with pytest.raises(ValueError, match="RSS 原文链接不可访问"):
        article_fetcher._fetch_rss_article_html("https://public.example/start")

    assert requested == ["https://public.example/start"]


def test_paddle_image_redirect_target_is_resolved_and_blocked_before_request(monkeypatch):
    requested: list[str] = []

    def resolve(host, *_args, **_kwargs):
        return _dns_answer("93.184.216.34" if host == "public.example" else "::1")

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, **_kwargs):
            requested.append(url)
            return _Response(headers={"location": "https://private.example/image.png"})

    monkeypatch.setattr(public_url.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(paddle_ocr, "direct_requests_session", Session)

    with pytest.raises(ValueError, match="图片地址不可访问"):
        paddle_ocr._download_image("https://public.example/image.png", article_url="https://mp.weixin.qq.com/s/example")

    assert requested == ["https://public.example/image.png"]


def test_paddle_result_download_preserves_public_redirect_behavior(monkeypatch):
    requested: list[str] = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, **_kwargs):
            requested.append(url)
            if url.endswith("/result"):
                return _Response(headers={"location": "/result-final"})
            return _Response(text="# 已识别内容")

    monkeypatch.setattr(public_url.socket, "getaddrinfo", lambda *_args, **_kwargs: _dns_answer("93.184.216.34"))
    monkeypatch.setattr(paddle_ocr, "direct_requests_session", Session)

    assert paddle_ocr._download_markdown("https://result.example/result") == "# 已识别内容"
    assert requested == ["https://result.example/result", "https://result.example/result-final"]
