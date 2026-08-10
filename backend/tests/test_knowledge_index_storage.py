from __future__ import annotations

from types import SimpleNamespace

from services import knowledge_v2
from services.knowledge_index_storage import CHUNKER_VERSION, searchable, source_hash


def _document(**changes: object) -> dict[str, object]:
    return {
        "content_item_id": "content-1",
        "title": "混合检索",
        "source_provider": "wechat",
        "source_name": "技术资料",
        "source_url": "https://example.com/article",
        "markdown": "# 原理\n\nRRF 融合结构化检索。",
    } | changes


def test_source_hash_uses_indexed_identity_and_cleaned_markdown():
    original = _document()

    assert source_hash(original) == source_hash(dict(original))
    assert source_hash(_document(markdown=original["markdown"] + "\n\n## AI 摘要\n\n不进入索引。")) == source_hash(original)
    assert source_hash(_document(title="不同标题")) != source_hash(original)
    assert source_hash(_document(markdown="# 原理\n\n不同正文。")) != source_hash(original)


def test_searchable_keeps_source_metadata_and_uses_bounded_fts_tokens():
    tokens = searchable(
        _document(),
        SimpleNamespace(heading_path="原理", text='RRF "drop" * 召回融合'),
    ).split()

    assert "rrf" in tokens
    assert "混合" in tokens
    assert "技术" in tokens
    assert '"' not in tokens
    assert "*" not in tokens


def test_knowledge_v2_reexports_chunker_version_from_index_storage():
    assert knowledge_v2.CHUNKER_VERSION == CHUNKER_VERSION
