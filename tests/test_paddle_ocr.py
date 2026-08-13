from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from services import article_fetcher, paddle_ocr, public_url, wechat_reports
from services.article_preview import build_local_article_html
from services.content_source_text import ContentSourceText
from services.paddle_ocr import OcrImageResult


class _Response:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.text)


class _ThrottledResponse:
    status_code = 429
    headers = {"Retry-After": "0"}

    def raise_for_status(self):
        raise AssertionError("限流响应不应在仍可重试时抛出")


def test_image_ocr_concurrency_keeps_input_order(monkeypatch):
    monkeypatch.setattr(settings, "paddle_ocr_access_token", "test-token")
    calls: list[str] = []

    def recognize_one(url: str, *, article_url: str, image_cache_dir=None):
        calls.append(url)
        return OcrImageResult(url=url, text=f"文字 {url[-1]}", status="succeeded")

    with patch("services.paddle_ocr._recognize_one", side_effect=recognize_one):
        results = paddle_ocr.recognize_wechat_images(
            ["https://img.example/1", "https://img.example/2", "https://img.example/3"],
            article_url="https://mp.weixin.qq.com/s/example",
        )

    assert [result.url for result in results] == [
        "https://img.example/1",
        "https://img.example/2",
        "https://img.example/3",
    ]
    assert sorted(calls) == [
        "https://img.example/1",
        "https://img.example/2",
        "https://img.example/3",
    ]


def test_ocr_request_retries_explicit_rate_limits(monkeypatch):
    responses = iter([_ThrottledResponse(), _Response('{"data": {"jobId": "job-1"}}')])
    monkeypatch.setattr(paddle_ocr.requests, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(paddle_ocr.time, "sleep", lambda *_: None)
    monkeypatch.setattr(settings, "paddle_ocr_access_token", "test-token")

    assert paddle_ocr._submit_job(b"image", filename="notice.png", content_type="image/png") == ("job-1", 1)


def test_ocr_request_uses_quality_focused_vl_payload(monkeypatch):
    captured: dict[str, object] = {}

    def post(*args, **kwargs):
        captured.update(kwargs)
        return _Response('{"data": {"jobId": "job-1"}}')

    monkeypatch.setattr(paddle_ocr.requests, "post", post)
    monkeypatch.setattr(settings, "paddle_ocr_access_token", "test-token")

    assert paddle_ocr._submit_job(b"image", filename="notice.png", content_type="image/png") == ("job-1", 0)
    payload = json.loads(captured["data"]["optionalPayload"])
    assert payload == {
        "useDocOrientationClassify": True,
        "useDocUnwarping": False,
        "useLayoutDetection": True,
        "useChartRecognition": True,
        "prettifyMarkdown": True,
        "temperature": 0,
        "visualize": False,
    }


def test_normal_image_submits_to_paddle_without_device_ocr_gate(monkeypatch):
    monkeypatch.setattr(paddle_ocr, "_submit_job", lambda *args, **kwargs: ("job-1", 0))
    monkeypatch.setattr(paddle_ocr, "_wait_for_result", lambda *args, **kwargs: ("https://example.com/result", "markdown", 0))
    monkeypatch.setattr(paddle_ocr, "_download_markdown", lambda *args, **kwargs: "识别结果")
    monkeypatch.setattr(paddle_ocr, "record_ocr_call", lambda **kwargs: None)
    monkeypatch.setattr(paddle_ocr, "_read_ocr_result_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(paddle_ocr, "_write_ocr_result_cache", lambda *args, **kwargs: None)

    result = paddle_ocr._recognize_image_bytes(
        b"diagnostic image",
        url="file:///tmp/diagnostic.png",
        filename="diagnostic.png",
        content_type="image/png",
        cached_path="/tmp/diagnostic.png",
        content_item_id=None,
        force_cloud=False,
    )

    assert result.status == "succeeded"
    assert result.cloud_submitted is True


def test_pdf_document_ocr_reuses_async_submission_and_result_cache(monkeypatch):
    monkeypatch.setattr(settings, "paddle_ocr_access_token", "test-token")
    submitted: dict[str, object] = {}

    def submit(payload, *, filename, content_type):
        submitted.update({"payload": payload, "filename": filename, "content_type": content_type})
        return "job-pdf", 0

    monkeypatch.setattr(paddle_ocr, "_submit_job", submit)
    monkeypatch.setattr(paddle_ocr, "_wait_for_result", lambda *args, **kwargs: ("https://example.com/result", "markdown", 0))
    monkeypatch.setattr(paddle_ocr, "_download_markdown", lambda *_: "# 扫描件公告\n\n采购内容")
    monkeypatch.setattr(paddle_ocr, "record_ocr_call", lambda **kwargs: None)
    monkeypatch.setattr(paddle_ocr, "_read_ocr_result_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(paddle_ocr, "_write_ocr_result_cache", lambda *_args, **_kwargs: None)

    result = paddle_ocr.recognize_document_bytes(
        b"%PDF-1.7 scanned procurement notice",
        url="https://provider.yuncaitong.cn/publish/notice.pdf",
        filename="notice.pdf",
        content_type="application/pdf",
        content_item_id="item-pdf",
    )

    assert result.status == "succeeded"
    assert result.text == "# 扫描件公告\n\n采购内容"
    assert submitted == {
        "payload": b"%PDF-1.7 scanned procurement notice",
        "filename": "notice.pdf",
        "content_type": "application/pdf",
    }


def test_pending_ocr_job_is_reused_without_a_second_submission(monkeypatch, tmp_path):
    old_data_dir = settings.data_dir
    settings.data_dir = tmp_path
    try:
        submitted = []
        poll_attempts = []
        monkeypatch.setattr(settings, "paddle_ocr_access_token", "test-token")
        monkeypatch.setattr(paddle_ocr, "_read_ocr_result_cache", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(paddle_ocr, "_write_ocr_result_cache", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(paddle_ocr, "record_ocr_call", lambda **_kwargs: None)
        monkeypatch.setattr(paddle_ocr, "_schedule_ocr_resume", lambda _digest: None)

        def submit(*_args, **_kwargs):
            submitted.append("submitted")
            return "job-slow", 0

        def poll(*_args, **_kwargs):
            poll_attempts.append("poll")
            if len(poll_attempts) == 1:
                raise paddle_ocr.OcrJobPending()
            return "https://example.com/result", "markdown", 0

        monkeypatch.setattr(paddle_ocr, "_submit_job", submit)
        monkeypatch.setattr(paddle_ocr, "_wait_for_result", poll)
        monkeypatch.setattr(paddle_ocr, "_download_markdown", lambda *_args: "识别结果")

        first = paddle_ocr._recognize_ocr_bytes(
            b"same image",
            url="https://example.com/image.png",
            filename="image.png",
            content_type="image/png",
            cached_path="",
            content_item_id=None,
        )
        second = paddle_ocr._recognize_ocr_bytes(
            b"same image",
            url="https://example.com/image.png",
            filename="image.png",
            content_type="image/png",
            cached_path="",
            content_item_id=None,
        )

        assert first.status == "pending"
        assert second.status == "succeeded"
        assert submitted == ["submitted"]
    finally:
        settings.data_dir = old_data_dir


def test_pdf_json_lines_result_keeps_all_page_batches(monkeypatch):
    class JsonLinesResponse:
        text = '\n'.join([
            json.dumps({"result": {"layoutParsingResults": [{"markdown": {"text": "第一页正文"}}]}}, ensure_ascii=False),
            json.dumps({"result": {"layoutParsingResults": [{"markdown": {"text": "第二页表格"}}]}}, ensure_ascii=False),
        ])

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Extra data")

        def close(self):
            return None

    class StubSession:
        def get(self, *_args, **_kwargs):
            return JsonLinesResponse()

        def close(self):
            return None

    monkeypatch.setattr(public_url, "_new_pinned_curl_session", lambda *_args, **_kwargs: StubSession())
    monkeypatch.setattr(
        public_url.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )

    text = paddle_ocr._download_json_result("https://result.example.com/notice.json")

    assert text == "第一页正文\n\n第二页表格"


def test_wechat_article_inserts_ocr_text_after_its_image(monkeypatch):
    page = """
    <html><h1 class='rich_media_title'>图片文章</h1>
    <div id='js_content'><p>第一段</p><img data-src='https://img.example/table.png' data-w='800' data-ratio='0.5'/><p>第二段</p></div></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: True)
    monkeypatch.setattr(
        article_fetcher,
        "recognize_wechat_images",
        lambda urls, *, article_url, image_cache_dir=None: [
            OcrImageResult(
                url=urls[0],
                text="| 日期 | 通知 |\n| --- | --- |\n| 7月20日 | 报到 |",
                status="succeeded",
                cached_path="/tmp/article_images/table.png",
            )
        ],
    )

    article = article_fetcher.fetch_wechat_article("https://mp.weixin.qq.com/s/example")

    assert "第一段" in article.body_text
    assert "[图片文字 1]" in article.body_text
    assert "| 7月20日 | 报到 |" in article.body_text
    assert article.body_text.index("第一段") < article.body_text.index("[图片文字 1]") < article.body_text.index("第二段")
    assert article.image_ocr["recognized_count"] == 1
    assert article.image_ocr["cached_image_count"] == 1
    assert 'data-local-media-path="/tmp/article_images/table.png"' in article.body_html


def test_wechat_snapshot_can_be_captured_before_image_ocr(monkeypatch):
    page = """
    <html><h1 class='rich_media_title'>图片文章</h1>
    <div id='js_content'><p>正文先可读</p><img data-src='https://img.example/poster.png' data-w='800'/></div></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: True)
    recognize = patch("services.article_fetcher.recognize_wechat_images")

    with recognize as recognize_mock:
        article = article_fetcher.fetch_wechat_article(
            "https://mp.weixin.qq.com/s/example",
            include_image_ocr=False,
        )

    recognize_mock.assert_not_called()
    assert article.body_text == "正文先可读"
    assert article.image_ocr["pending"] is True
    assert article.image_ocr["attempted"] is False


def test_cached_article_ocr_enriches_existing_snapshot_without_refetch(monkeypatch):
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: True)
    monkeypatch.setattr(
        article_fetcher,
        "recognize_wechat_images",
        lambda urls, **_kwargs: [OcrImageResult(url=urls[0], text="海报日期", status="succeeded")],
    )

    body_text, body_html, images, image_ocr = article_fetcher.enrich_cached_article_image_ocr(
        "<div id='js_content'><p>正文</p><img data-src='https://img.example/poster.png' data-w='800'/></div>",
        article_url="https://mp.weixin.qq.com/s/example",
    )

    assert images == ["https://img.example/poster.png"]
    assert "[图片文字 1]" in body_text
    assert "海报日期" in body_html
    assert image_ocr["recognized_count"] == 1


def test_wechat_picture_page_is_captured_for_ocr(monkeypatch):
    page = """
    <html><script>
      window.ct = '1776235598';
      window.msg_title = window.title = '校园赛事海报' || '';
      window.picture_page_info_list = [
        { cdn_url: 'https://img.example/poster-1.jpg', content_noencode: '报名截止\\x0a请扫码参加' },
        { cdn_url: 'https://img.example/poster-2.jpg' }
      ];
      window.cgiDataNew = { nick_name: '校园公众号' };
    </script></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: False)

    article = article_fetcher.fetch_wechat_article("https://mp.weixin.qq.com/s/picture-page")

    assert article.title == "校园赛事海报"
    assert article.author == "校园公众号"
    assert article.published_at == "2026-04-15 14:46"
    assert article.images == ["https://img.example/poster-1.jpg", "https://img.example/poster-2.jpg"]
    assert "报名截止" in article.body_text
    assert "data-wechat-picture-page" in article.body_html


def test_wechat_picture_page_can_insert_ocr_annotations(monkeypatch):
    page = """
    <html><script>
      window.msg_title = window.title = '图文通知' || '';
      window.picture_page_info_list = [
        { cdn_url: 'https://img.example/poster-1.jpg' }
      ];
    </script></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: True)
    monkeypatch.setattr(
        article_fetcher,
        "recognize_wechat_images",
        lambda urls, **_kwargs: [OcrImageResult(url=urls[0], text="活动时间：周五", status="succeeded")],
    )

    article = article_fetcher.fetch_wechat_article("https://mp.weixin.qq.com/s/picture-page-ocr")

    assert "[图片文字 1]" in article.body_text
    assert "活动时间：周五" in article.body_html
    assert article.image_ocr["recognized_count"] == 1


def test_wechat_text_share_page_is_captured(monkeypatch):
    page = """
    <html><script>
      window.msg_title = window.title = '文字通知' || '';
      window.cgiDataNew = { nick_name: '校园公众号' };
      window.text_page_info = { content: '第一段通知\\x0a第二段通知' };
    </script></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: False)

    article = article_fetcher.fetch_wechat_article("https://mp.weixin.qq.com/s/text-page")

    assert article.title == "文字通知"
    assert article.author == "校园公众号"
    assert article.body_text == "第一段通知\n第二段通知"
    assert "data-wechat-text-page" in article.body_html
    assert article.image_ocr["image_count"] == 0


def test_wechat_text_share_body_is_not_used_as_title(monkeypatch):
    page = """
    <html><script>
      window.msg_title = window.title = '第一段通知\\x0a第二段通知' || '';
      window.text_page_info = { content: '第一段通知\\x0a第二段通知' };
    </script></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: False)

    article = article_fetcher.fetch_wechat_article("https://mp.weixin.qq.com/s/text-page-body-title")

    assert article.title == "未命名公众号文章"
    assert article.body_text == "第一段通知\n第二段通知"


def test_wechat_image_only_article_is_cached_before_background_ocr(monkeypatch):
    page = """
    <html><body>
      <h1 class="rich_media_title">纯图公告</h1>
      <div class="rich_media_content" id="js_content">
        <img data-src="https://img.example/poster.png" data-w="800" />
      </div>
    </body></html>
    """
    monkeypatch.setattr(article_fetcher, "fetch_wechat_page", lambda *args, **kwargs: _Response(page))
    monkeypatch.setattr(article_fetcher, "is_paddle_ocr_configured", lambda: True)

    article = article_fetcher.fetch_wechat_article(
        "https://mp.weixin.qq.com/s/image-only",
        include_image_ocr=False,
    )

    assert article.images == ["https://img.example/poster.png"]
    assert article.image_ocr["pending"] is True
    assert article.body_text == "图文内容，共 1 张图片。图片文字正在后台解析。"
    assert "data-wechat-image-only-placeholder" in article.body_html


def test_article_preview_uses_local_media_for_cached_ocr_images():
    html = build_local_article_html(
        '''
        <section style="display: flex; width: 42%; margin: 0 auto; position: fixed; background-image: url(javascript:alert(1))">
          <p>正文</p>
          <img data-local-media-path="/tmp/article_images/table.png"
               data-src="https://cdn.example/table.png" data-w="640" data-ratio="0.5"
               style="display: block; width: 100%; max-width: 100%" onerror="alert(1)"/>
        </section>
        <script>alert(1)</script>
        ''',
        media_base_url="http://127.0.0.1:8000/api/media",
    )

    assert html.startswith("<!doctype html>")
    assert "http://127.0.0.1:8000/api/media?path=%2Ftmp%2Farticle_images%2Ftable.png" in html
    assert 'width="640"' in html
    assert 'height="320"' in html
    assert "<section>" in html
    assert "<section style=" not in html
    assert "display: flex" not in html
    assert "width: 42%" not in html
    assert "position: fixed" not in html
    assert "javascript:" not in html
    assert "onerror" not in html
    assert "<script" not in html
    assert "data-local-media-path" not in html


def test_report_material_uses_full_cached_article_text(monkeypatch):
    full_text = "正文开始\n[图片文字 1]\n表格中的关键信息\n[/图片文字 1]\n正文结束"
    monkeypatch.setattr(
        wechat_reports,
        "load_content_source_text",
        lambda content_item_id: ContentSourceText(content_item_id, "文章", "https://mp.weixin.qq.com/s/example", full_text, "article"),
    )

    material = wechat_reports._source_material(
        {
            "content_item_id": "content-1",
            "mp_name": "测试公众号",
            "title": "文章",
            "published_at": "2026-07-15T00:00:00+08:00",
            "source_url": "https://mp.weixin.qq.com/s/example",
        }
    )

    assert "原文正文（含图片文字识别结果）" in material
    assert full_text in material


def test_ocr_settings_api_never_returns_access_token(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "paddle_ocr_access_token", "")

    with TestClient(app) as client:
        saved = client.put(
            "/api/paddle-ocr-settings",
            json={
                "access_token": "test-private-token",
                "base_url": "https://ocr.example.test/api/v2/jobs",
                "model": "PP-OCRv6",
            },
        )
        current = client.get("/api/paddle-ocr-settings")

    assert saved.status_code == 200
    assert saved.json()["configured"] is True
    assert saved.json()["base_url"] == "https://ocr.example.test/api/v2/jobs"
    assert saved.json()["model"] == "PP-OCRv6"
    assert current.status_code == 200
    assert "access_token" not in current.json()
    assert "test-private-token" not in current.text
