from __future__ import annotations

import pytest
from services import xiaohongshu_ingest


class _Response:
    def __init__(self, *, payload=b"image", content_type="image/jpeg", content_length=None):
        self.content = payload
        self.headers = {"content-type": content_type}
        if content_length is not None:
            self.headers["content-length"] = content_length
        self.closed = False

    def raise_for_status(self):
        return None

    def close(self):
        self.closed = True


def test_xhs_image_download_uses_public_redirect_gate_and_closes(monkeypatch):
    response = _Response()
    observed = {}

    def get(url, **kwargs):
        observed.update(url=url, **kwargs)
        return response, "https://cdn.example/final.jpg"

    monkeypatch.setattr(xiaohongshu_ingest, "get_public_http_response", get)
    payload, content_type = xiaohongshu_ingest._download_image("https://images.example/start.jpg")
    assert payload == b"image"
    assert content_type == "image/jpeg"
    assert observed["max_redirects"] == 5
    assert observed["blocked_message"] == "小红书图片链接不可访问"
    assert response.closed is True


def test_xhs_image_download_propagates_private_redirect_rejection_without_payload(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise ValueError("小红书图片链接不可访问")

    monkeypatch.setattr(xiaohongshu_ingest, "get_public_http_response", blocked)
    with pytest.raises(ValueError, match="不可访问"):
        xiaohongshu_ingest._download_image("https://images.example/redirect-to-private")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_Response(payload=b"x", content_length=str(20 * 1024 * 1024 + 1)), "超过 20MB"),
        (_Response(payload=b"<svg/>", content_type="image/svg+xml"), "未返回图片"),
    ],
)
def test_xhs_image_download_rejects_oversize_or_active_formats_and_closes(monkeypatch, response, message):
    monkeypatch.setattr(
        xiaohongshu_ingest,
        "get_public_http_response",
        lambda *_args, **_kwargs: (response, "https://images.example/final"),
    )
    with pytest.raises(ValueError, match=message):
        xiaohongshu_ingest._download_image("https://images.example/start")
    assert response.closed is True


def test_xhs_image_capture_never_persists_remote_exception_details(tmp_path, monkeypatch):
    monkeypatch.setattr(
        xiaohongshu_ingest,
        "_download_image",
        lambda _url: (_ for _ in ()).throw(RuntimeError("xsec_token=secret /Users/private")),
    )
    entry = xiaohongshu_ingest._capture_image(
        "https://images.example/image.jpg?token=secret",
        index=1,
        image_dir=tmp_path,
        content_item_id="item-1",
    )
    assert entry["error"] == "图片读取失败"
    assert "secret" not in entry["error"]
    assert "private" not in entry["error"]
