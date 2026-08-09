from __future__ import annotations

from services.knowledge_chunking import clean_source_markdown, structural_chunks


def test_chunking_removes_generated_sections_without_losing_source_structure():
    markdown = """---
title: fixture
---

# 原始资料

## 事实

这是一段应当保留的来源正文。

![封面](cover.png)

[图片文字 1] OCR 内容

## AI 摘要

这一段不能进入知识索引。
"""

    cleaned = clean_source_markdown(markdown)
    parents, children = structural_chunks(markdown)

    assert "title: fixture" not in cleaned
    assert "AI 摘要" not in cleaned
    assert "来源正文" in cleaned
    assert "OCR 内容" in cleaned
    assert parents and children
    assert all("AI 摘要" not in chunk.text for chunk in [*parents, *children])
