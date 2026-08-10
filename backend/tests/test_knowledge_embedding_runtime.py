from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from services import knowledge_embedding_runtime as runtime
from services import knowledge_v2


def test_embedding_text_and_normalize_keep_stable_source_projection():
    row = {"title": "", "heading_path": "", "text": "向量内容"}

    assert runtime.embedding_text(row) == "标题：未命名内容\n章节：正文\n内容：向量内容"
    assert runtime.normalize([3.0, 4.0]) == [0.6, 0.8]
    assert runtime.normalize([0.0, 0.0]) == [0.0, 0.0]


def test_embed_sorts_provider_rows_normalizes_vectors_and_records_usage(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeEmbeddings:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(index=1, embedding=[0.0, 5.0]),
                    SimpleNamespace(index=0, embedding=[3.0, 4.0]),
                ],
                usage=SimpleNamespace(prompt_tokens=7, total_tokens=7),
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.embeddings = FakeEmbeddings()

    audits: list[dict[str, object]] = []
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr(runtime.settings, "campus_embedding_api_key", "test-key")
    monkeypatch.setattr(runtime.settings, "campus_embedding_api_base_url", "https://example.com/v1")
    monkeypatch.setattr(runtime.settings, "campus_embedding_api_model", "test-model")
    monkeypatch.setattr(runtime.settings, "campus_embedding_api_dimensions", 2)
    monkeypatch.setattr(runtime.settings, "llm_request_timeout_seconds", 30.0)
    monkeypatch.setattr(runtime, "record_ai_call", lambda **kwargs: audits.append(kwargs))

    result = runtime.embed(["first", "second"])

    assert calls == [{"model": "test-model", "input": ["first", "second"], "dimensions": 2, "encoding_format": "float"}]
    assert result == [[0.6, 0.8], [0.0, 1.0]]
    assert audits[0]["call_type"] == "knowledge_v2_embedding"
    assert audits[0]["input_chars"] == len("firstsecond")


def test_embed_rejects_provider_row_count_mismatch(monkeypatch):
    class FakeOpenAI:
        def __init__(self, **_kwargs):
            self.embeddings = SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    data=[SimpleNamespace(index=0, embedding=[1.0])],
                    usage=None,
                )
            )

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setattr(runtime, "record_ai_call", lambda **_kwargs: None)

    with pytest.raises(ValueError, match="返回数量"):
        runtime.embed(["first", "second"])


def test_knowledge_v2_keeps_embedding_helper_compatibility_aliases():
    assert knowledge_v2._embed is runtime.embed
    assert knowledge_v2._save_embedding_batch is runtime.save_embedding_batch
