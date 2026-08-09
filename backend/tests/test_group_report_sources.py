from __future__ import annotations

from types import SimpleNamespace

from services import group_report_sources as sources


def test_source_material_prefers_managed_text_with_ocr():
    material = sources.source_material(
        {
            "content_item_id": "item-1",
            "mp_name": "测试来源",
            "title": "测试文章",
            "published_at": "2026-08-10",
            "source_url": "https://example.test/article",
        },
        load_text=lambda _content_item_id: SimpleNamespace(text="正文\n[图片文字 1] 海报内容"),
    )

    assert "## 测试来源｜测试文章" in material
    assert "原文正文（含图片文字识别结果）" in material
    assert "[图片文字 1] 海报内容" in material


def test_markdown_fallback_keeps_only_the_original_body_and_sort_is_stable():
    markdown = "# 摘要\n<details><summary>原文正文</summary>\n真实正文\n</details>\n"

    assert sources.original_body_from_markdown(markdown) == "真实正文"
    assert sources.group_source_sort_key(
        {"published_at": "2026-08-10", "source_name": "来源", "content_item_id": "b"}
    ) < sources.group_source_sort_key(
        {"published_at": "2026-08-10", "source_name": "来源", "content_item_id": "c"}
    )
