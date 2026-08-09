from contextlib import nullcontext
from types import SimpleNamespace
from urllib.parse import quote

from config import settings
from routers import content_preview as content_router
from services.cache import cache_dir_for_url, write_cache_meta
from services.xiaohongshu_cache import xiaohongshu_cache_dir


def test_xiaohongshu_preview_uses_stable_note_cache_for_gallery(tmp_path, monkeypatch):
    """A refreshed xsec URL must not make the reader lose its local gallery."""
    source_url = (
        "https://www.xiaohongshu.com/explore/6a666e2b000000001c0108b4"
        "?xsec_token=current-token&xsec_source=pc_feed"
    )
    item = SimpleNamespace(
        id="xhs-item",
        source_provider="xiaohongshu",
        content_type="article",
        source_url=source_url,
        title="笔记标题",
        source_name="作者",
        published_at="2026-08-01 09:00",
    )

    # This emulates a pre-note-id cache left behind by an older share URL. It
    # contains enough text to render, but no image gallery.
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    write_cache_meta(
        cache_dir_for_url(source_url),
        {"article_info": {"title": "旧正文", "body_html": "<p>旧 OCR 正文</p>"}},
    )
    image_path = tmp_path / "data" / "cache" / "xhs-01.webp"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(b"preview")
    write_cache_meta(
        xiaohongshu_cache_dir(source_url),
        {
            "article_info": {
                "title": "笔记标题",
                "author": "作者",
                "description": "作者写的内容 #知识管理",
                "xhs_gallery": [{"index": 1, "cached_path": str(image_path), "ocr_text": "图片 OCR"}],
            }
        },
    )

    class Repository:
        def __init__(self, _connection):
            pass

        def get_content_item(self, item_id):
            assert item_id == item.id
            return item

    monkeypatch.setattr(content_router, "initialize_database", lambda: None)
    monkeypatch.setattr(content_router, "connect", lambda: nullcontext(object()))
    monkeypatch.setattr(content_router, "ContentRepository", Repository)

    response = content_router.get_article_preview(
        item.id,
        SimpleNamespace(base_url="http://127.0.0.1:8000/"),
    )

    assert response.title == "笔记标题"
    assert response.gallery == [{
        "index": 1,
        "url": f"http://127.0.0.1:8000/api/media?path={quote(str(image_path), safe='')}",
        "ocr_status": "",
        "ocr_text": "图片 OCR",
    }]
    assert "作者写的内容" in response.html
