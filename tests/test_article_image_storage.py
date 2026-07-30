from __future__ import annotations

import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.article_image_storage import compact_cached_article_images, write_article_image_preview
from services.knowledge_library import _source_markdown_body
from services.repository import ContentItemRecord


def _large_png_bytes() -> bytes:
    image = Image.effect_noise((2200, 1500), 100).convert("RGB")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_write_article_image_preview_limits_dimensions_and_uses_webp(tmp_path):
    preview_path = write_article_image_preview(
        _large_png_bytes(),
        filename_stem="source-image",
        image_cache_dir=tmp_path,
    )

    assert Path(preview_path).suffix == ".webp"
    with Image.open(preview_path) as preview:
        assert max(preview.size) <= 1440
        assert preview.format == "WEBP"


def test_compact_cached_article_images_rewrites_cached_html_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    image_dir = settings.data_dir / "cache" / "entry" / "article_images"
    image_dir.mkdir(parents=True)
    source = image_dir / "source.png"
    source.write_bytes(_large_png_bytes())
    metadata = image_dir.parent / "metadata.json"
    metadata.write_text(json.dumps({"article_info": {"body_html": f'<img data-local-media-path="{source}">'}}, ensure_ascii=False), encoding="utf-8")

    stats = compact_cached_article_images()

    preview = image_dir / "source.webp"
    assert stats["compressed"] == 1
    assert preview.exists()
    assert not source.exists()
    assert str(preview) in json.loads(metadata.read_text(encoding="utf-8"))["article_info"]["body_html"]


def test_markdown_source_body_keeps_image_link_without_copying_attachment(tmp_path):
    item = ContentItemRecord(
        id="item-1", content_type="article", source_provider="wechat", source_url="https://example.com/a",
        canonical_source_id="a", title="图文", cover_url=None, duration_seconds=None, status="done",
        series_id=None, library_folder_id=None, sort_order=0, created_at="", updated_at="",
    )
    local_preview = tmp_path / "preview.webp"
    local_preview.write_bytes(b"preview")

    body = _source_markdown_body(
        item,
        "",
        {"body_html": f'<p><img src="https://img.example/original.jpg" data-local-media-path="{local_preview}"></p>'},
        document_parent=tmp_path,
    )

    assert "[原图 1：https://img.example/original.jpg]" in body
    assert "![原图" not in body
