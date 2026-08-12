from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.database import connect, initialize_database, utc_now_iso
from services.prompt_templates import PromptTemplateRepository
import services.knowledge_v2 as knowledge_v2
from services.knowledge_v2 import CHILD_MAX_TOKENS, RetrievedChunk, _citation_excerpt, _evidence_payload, answer_from_evidence, evidence_preview, list_source_set_documents, list_source_sets, rebuild_documents, retrieve, rewrite_query, scope_readiness, source_documents, stream_answer_from_evidence, structural_chunks, validate_source_document_ids
from services.repository import ContentRepository
from routers.knowledge import V2QueryRequest


def _add_source(tmp_path: Path, *, source_name: str, title: str, markdown: str) -> str:
    with connect() as db:
        item = ContentRepository(db).create_content_item(
            source_provider="wechat",
            canonical_source_id=f"wechat-{title}",
            content_type="article",
            title=title,
            source_name=source_name,
            source_url="https://example.com/article",
        )
        path = tmp_path / f"{item.id}.md"
        path.write_text(markdown, encoding="utf-8")
        db.execute(
            "INSERT INTO content_documents (content_item_id,markdown_path,content_hash,updated_at) VALUES (?,?,?,?)",
            (item.id, str(path), "fixture", utc_now_iso()),
        )
        db.commit()
    return item.id


def test_structural_chunks_keep_heading_lists_and_tables_whole():
    prose = "。".join(["这是用来验证结构化切块的短句" for _ in range(80)]) + "。"
    markdown = f"""# 总标题

## 关键结论

{prose}

## 清单

- 第一项
  - 第一项的补充说明
- 第二项

## 对照表

| 指标 | 值 |
| --- | --- |
| A | 1 |
| B | 2 |
"""
    parents, children = structural_chunks(markdown)

    assert parents
    assert children
    assert any("## 清单\n\n- 第一项" in child.text for child in children)
    assert any("| 指标 | 值 |\n| --- | --- |\n| A | 1 |\n| B | 2 |" in child.text for child in children)
    assert all(child.token_count <= CHILD_MAX_TOKENS or "这是用来验证" in child.text for child in children)
    assert {child.parent_ordinal for child in children} <= {parent.ordinal for parent in parents}


def test_v2_rebuild_indexes_only_selected_source_and_skips_unchanged(tmp_path):
    initialize_database()
    selected_id = _add_source(
        tmp_path,
        source_name="LaTeX工作室",
        title="结构化检索",
        markdown="# 结构化检索\n\n## 原理\n\n父子块让召回更精细，同时保留长上下文。",
    )
    _add_source(
        tmp_path,
        source_name="不应进入试点",
        title="旁路文章",
        markdown="# 旁路\n\n这篇文章不属于当前的知识集试点。",
    )

    docs = source_documents(source_specs=[("wechat", "LaTeX工作室")])
    first = rebuild_documents(docs)
    second = rebuild_documents(docs)
    source_sets = list_source_sets()

    assert first["document_count"] == 1
    assert first["rebuilt_document_count"] == 1
    assert first["parent_chunk_count"] >= 1
    assert first["child_chunk_count"] >= 1
    assert second["rebuilt_document_count"] == 0
    selected_set = next(item for item in source_sets if item["name"] == "LaTeX工作室")
    assert selected_set["status"] == "migrating"
    assert not selected_set["selectable"]

    with connect() as db:
        rows = db.execute(
            "SELECT chunk_kind,content_item_id,parent_chunk_id FROM knowledge_v2_chunks ORDER BY chunk_kind,ordinal"
        ).fetchall()
        search_rows = db.execute("SELECT chunk_id FROM knowledge_v2_search").fetchall()
    assert {row["content_item_id"] for row in rows} == {selected_id}
    assert any(row["chunk_kind"] == "parent" for row in rows)
    assert all(row["parent_chunk_id"] for row in rows if row["chunk_kind"] == "child")
    assert len(search_rows) == sum(row["chunk_kind"] == "child" for row in rows)


def test_v2_source_set_listing_counts_documents_without_chunk_join_duplication(tmp_path):
    initialize_database()
    _add_source(
        tmp_path,
        source_name="LaTeX工作室",
        title="第一篇",
        markdown="# 第一篇\n\n第一篇有可切分的正文。",
    )
    _add_source(
        tmp_path,
        source_name="LaTeX工作室",
        title="第二篇",
        markdown="# 第二篇\n\n第二篇也有可切分的正文。",
    )

    rebuild_documents(source_documents(source_specs=[("wechat", "LaTeX工作室")]))
    source_set = next(item for item in list_source_sets() if item["name"] == "LaTeX工作室")

    assert source_set["document_count"] == 2
    assert source_set["ready_document_count"] == 2
    assert source_set["child_chunk_count"] >= 2
    assert source_set["embedded_child_count"] == 0
    assert not source_set["selectable"]


def test_v2_retrieval_filters_scope_before_hybrid_ranking(tmp_path, monkeypatch):
    initialize_database()
    selected_id = _add_source(
        tmp_path,
        source_name="LaTeX工作室",
        title="混合检索",
        markdown="# 混合检索\n\n## 原理\n\n向量召回和关键词召回通过 RRF 融合。",
    )
    _add_source(
        tmp_path,
        source_name="旁路来源",
        title="错误候选",
        markdown="# 旁路\n\n这一篇不应出现在 LaTeX 工作室的问答答案中。",
    )
    monkeypatch.setattr(knowledge_v2.settings, "campus_embedding_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "_embed", lambda texts: [[1.0] + [0.0] * 1023 for _ in texts])

    documents = source_documents(source_specs=[("wechat", "LaTeX工作室")])
    rebuild_documents(documents, embed=True)
    readiness = scope_readiness(source_specs=[("wechat", "LaTeX工作室")])
    results = retrieve("关键词召回怎么融合？", source_specs=[("wechat", "LaTeX工作室")])
    preview = evidence_preview(results[0].chunk_id)

    assert readiness.ready
    assert results
    assert {result.content_item_id for result in results} == {selected_id}
    assert "RRF" in results[0].parent_text
    assert preview["content_item_id"] == selected_id
    assert preview["parent_chunk_id"] == results[0].parent_chunk_id


def test_v2_retrieval_filters_selected_or_excluded_documents(tmp_path, monkeypatch):
    initialize_database()
    selected_id = _add_source(
        tmp_path,
        source_name="LaTeX工作室",
        title="选择范围文章",
        markdown="# 选择范围\n\nRRF 只应从被选择的文章中召回。",
    )
    excluded_id = _add_source(
        tmp_path,
        source_name="LaTeX工作室",
        title="排除范围文章",
        markdown="# 排除范围\n\n向量检索也必须尊重文章排除范围。",
    )
    monkeypatch.setattr(knowledge_v2.settings, "campus_embedding_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "_embed", lambda texts: [[1.0] + [0.0] * 1023 for _ in texts])
    rebuild_documents(source_documents(source_specs=[("wechat", "LaTeX工作室")]), embed=True)

    listed = list_source_set_documents("wechat", "LaTeX工作室")
    assert {item["id"] for item in listed["items"]} == {selected_id, excluded_id}
    assert {item["content_type"] for item in listed["items"]} == {"article"}
    assert validate_source_document_ids("wechat", "LaTeX工作室", [selected_id]) == [selected_id]

    included = retrieve(
        "RRF 怎么召回？",
        source_specs=[("wechat", "LaTeX工作室")],
        content_item_ids=[selected_id],
    )
    excluded = retrieve(
        "RRF 怎么召回？",
        source_specs=[("wechat", "LaTeX工作室")],
        excluded_content_item_ids=[selected_id],
    )

    assert {item.content_item_id for item in included} == {selected_id}
    assert {item.content_item_id for item in excluded} == {excluded_id}


def test_v2_answer_rejects_out_of_scope_evidence_ids(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def chat(self, *_args, **_kwargs):
            from services.llm_provider import LLMResponse

            return LLMResponse(
                content='{"answer":"这不应通过", "evidence_ids":["E999"], "insufficient_evidence":false}',
                provider=self.name,
                model=self.model,
            )

    result = RetrievedChunk(
        chunk_id="child-1",
        parent_chunk_id="parent-1",
        content_item_id="content-1",
        title="证据文章",
        source_provider="wechat",
        source_name="LaTeX工作室",
        source_url="https://example.com/source",
        published_at="2026-07-29",
        heading_path="原理",
        child_text="RRF 融合两个召回通道。",
        parent_text="RRF 融合两个召回通道，并保留原始上下文。",
        score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: FakeProvider())

    try:
        answer_from_evidence("怎么融合召回？", [result])
    except ValueError as exc:
        assert "范围外" in str(exc)
    else:
        raise AssertionError("范围外证据 ID 必须被拒绝")


def test_v2_answer_stream_exposes_only_answer_text_before_validated_result(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "flash"

        def chat_stream_events(self, *_args, **_kwargs):
            from services.llm_provider import LLMStreamChunk, LLMUsage

            yield LLMStreamChunk(content='{"answer":"RRF ')
            yield LLMStreamChunk(content='融合召回。 [E001]","evidence_ids":["E001"],"insufficient_evidence":false}')
            yield LLMStreamChunk(usage=LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20), finish_reason="stop")

    result = RetrievedChunk(
        chunk_id="child-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="证据文章", source_provider="wechat", source_name="LaTeX工作室",
        source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
        child_text="RRF 融合两个召回通道。", parent_text="RRF 融合两个召回通道。", score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: FakeProvider())

    events = list(stream_answer_from_evidence("怎么融合召回？", [result], task_id="knowledge:stream"))

    assert "".join(payload for event, payload in events if event == "delta") == "RRF 融合召回。 [E001]"
    done = next(payload for event, payload in events if event == "done")
    assert done.answer == "RRF 融合召回。 [E001]"
    assert done.citations[0]["evidence_id"] == "E001"


def test_selected_provider_construction_type_error_never_falls_back_to_default(monkeypatch):
    calls = []

    def fail_selected(model=None):
        calls.append(model)
        if model is None:
            raise AssertionError("must not fall back to the default provider")
        raise TypeError("selected provider construction failed")

    monkeypatch.setattr(knowledge_v2, "default_llm_provider", fail_selected)
    with pytest.raises(TypeError, match="selected provider construction failed"):
        knowledge_v2._knowledge_llm_provider("qwen::qwen3.7-plus:enabled")
    assert calls == ["qwen::qwen3.7-plus:enabled"]


def test_citation_excerpt_skips_image_and_page_chrome_for_matching_passage():
    excerpt = _citation_excerpt(
        "# TeXstudio 新版\n\n[原图 1：https://example.com/cover.png]\n\n"
        "点击关注公众号\n\n近日，新版本修复了不少异常崩溃的问题，建议及时更新。",
        "TeXstudio 新版本主要解决了什么问题？",
        title="TeXstudio 新版本来了，再也不会崩溃退出了",
    )

    assert "异常崩溃" in excerpt
    assert "原图" not in excerpt
    assert "关注公众号" not in excerpt


def test_citation_excerpt_skips_rss_translation_metadata():
    excerpt = _citation_excerpt(
        "See all posts\nPublished on\n2026-04-05\nTranslated on\n2026-04-04\n"
        "编程智能体的核心组件【译】\n原文：Components of A Coding Agent\n作者：Sebastian Raschka\n"
        "编程智能体是一个包含模型、工具、记忆和环境反馈的循环系统。",
        "编程智能体有哪些组成？",
        title="编程智能体的核心组件【译】",
    )

    assert "模型、工具、记忆" in excerpt
    assert "Published on" not in excerpt
    assert "Sebastian Raschka" not in excerpt


def test_citation_excerpt_uses_parent_context_when_child_is_a_footer():
    result = RetrievedChunk(
        chunk_id="child-1",
        parent_chunk_id="parent-1",
        content_item_id="content-1",
        title="智能向善的双重纬度",
        source_provider="wechat",
        source_name="腾讯研究院",
        source_url="https://example.com/source",
        published_at="2026-07-29",
        heading_path="正文",
        child_text="其中“让人放心，把人放大”原概念取自腾讯研究院文章。",
        parent_text="让人放心包含可理解、可介入、可追溯。把人放大包含能力、价值、精神三层规范边界。",
        score=1,
    )

    excerpt = _evidence_payload([result], question="放心与放大分别有哪些含义？")[0]["excerpt"]

    assert "可理解" in str(excerpt)


def test_v2_answer_prompt_requires_complete_list_answers(monkeypatch):
    captured = {}

    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def chat(self, messages, **_kwargs):
            from services.llm_provider import LLMResponse

            captured["system"] = messages[0].content
            return LLMResponse(
                content='{"answer":"第一项：RRF。", "evidence_ids":["E001"], "evidence_quotes":[{"evidence_id":"E001","quote":"RRF 融合两个召回通道。"}], "insufficient_evidence":false}',
                provider=self.name,
                model=self.model,
            )

    result = RetrievedChunk(
        chunk_id="child-1",
        parent_chunk_id="parent-1",
        content_item_id="content-1",
        title="证据文章",
        source_provider="wechat",
        source_name="LaTeX工作室",
        source_url="https://example.com/source",
        published_at="2026-07-29",
        heading_path="原理",
        child_text="RRF 融合两个召回通道。",
        parent_text="RRF 融合两个召回通道，并保留原始上下文。",
        score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: FakeProvider())

    answer = answer_from_evidence("主要有哪些要点？", [result])

    assert "逐条覆盖" in captured["system"]
    assert answer.citations[0]["excerpt"] == "RRF 融合两个召回通道。"


def test_evidence_quote_accepts_only_punctuation_normalization():
    evidence = [{"evidence_id": "E001", "child_text": "RRF 融合两个召回通道。", "parent_text": ""}]

    accepted = knowledge_v2._validated_evidence_quotes(
        [{"evidence_id": "E001", "quote": "RRF融合两个召回通道!"}],
        evidence_ids=["E001"],
        evidence=evidence,
        insufficient=False,
    )

    assert accepted["E001"] == "RRF融合两个召回通道!"


def test_partial_legacy_evidence_quotes_fall_back_to_server_excerpt():
    accepted = knowledge_v2._validated_evidence_quotes(
        [{"evidence_id": "E001", "quote": "第一条证据内容。"}],
        evidence_ids=["E001", "E002"],
        evidence=[
            {"evidence_id": "E001", "child_text": "第一条证据内容。", "parent_text": "", "excerpt": "第一条证据内容。"},
            {"evidence_id": "E002", "child_text": "第二条证据内容。", "parent_text": "", "excerpt": "第二条证据内容。"},
        ],
        insufficient=False,
    )

    assert accepted == {"E001": "第一条证据内容。", "E002": "第二条证据内容。"}


def test_v2_answer_retries_an_empty_flash_response(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def __init__(self):
            self.calls = 0

        def chat(self, *_args, **_kwargs):
            from services.llm_provider import LLMResponse

            self.calls += 1
            content = "" if self.calls == 1 else (
                '{"answer":"RRF 融合两个召回通道。", "evidence_ids":["E001"], '
                '"evidence_quotes":[{"evidence_id":"E001","quote":"RRF 融合两个召回通道。"}], '
                '"insufficient_evidence":false}'
            )
            return LLMResponse(content=content, provider=self.name, model=self.model)

    provider = FakeProvider()
    result = RetrievedChunk(
        chunk_id="child-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="证据文章", source_provider="wechat", source_name="LaTeX工作室",
        source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
        child_text="RRF 融合两个召回通道。", parent_text="RRF 融合两个召回通道。", score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: provider)

    answer = answer_from_evidence("怎么融合召回？", [result])

    assert provider.calls == 2
    assert answer.answer == "RRF 融合两个召回通道。"


def test_v2_answer_limits_context_to_highest_ranked_evidence(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def __init__(self):
            self.messages = []

        def chat(self, messages, **_kwargs):
            from services.llm_provider import LLMResponse

            self.messages = messages
            return LLMResponse(
                content='{"answer":"第一条。", "evidence_ids":["E001"], "evidence_quotes":[{"evidence_id":"E001","quote":"证据 0 支持结论。"}], "insufficient_evidence":false}',
                provider=self.name,
                model=self.model,
            )

    provider = FakeProvider()
    results = [
        RetrievedChunk(
            chunk_id=f"child-{index}", parent_chunk_id=f"parent-{index}", content_item_id=f"content-{index}",
            title=f"证据 {index}", source_provider="wechat", source_name="LaTeX工作室",
            source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
            child_text=f"证据 {index} 支持结论。", parent_text=f"证据 {index} 支持结论。", score=1,
        )
        for index in range(7)
    ]
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: provider)

    answer_from_evidence("怎么融合召回？", results, evidence_limit=6)

    assert "[E006]" in provider.messages[-1].content
    assert "[E007]" not in provider.messages[-1].content


def test_v2_answer_uses_all_ranked_evidence_by_default(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def __init__(self):
            self.messages = []

        def chat(self, messages, **_kwargs):
            from services.llm_provider import LLMResponse

            self.messages = messages
            return LLMResponse(
                content='{"answer":"第七条。 [E007]", "evidence_ids":["E007"], "insufficient_evidence":false}',
                provider=self.name,
                model=self.model,
            )

    provider = FakeProvider()
    results = [
        RetrievedChunk(
            chunk_id=f"child-{index}", parent_chunk_id=f"parent-{index}", content_item_id=f"content-{index}",
            title=f"证据 {index}", source_provider="wechat", source_name="LaTeX工作室",
            source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
            child_text=f"证据 {index} 支持结论。", parent_text=f"证据 {index} 支持结论。", score=1,
        )
        for index in range(7)
    ]
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: provider)

    answer = answer_from_evidence("有哪些结论？", results)

    assert "[E007]" in provider.messages[-1].content
    assert answer.citations[0]["evidence_id"] == "E007"


def test_v2_answer_accepts_server_generated_evidence_excerpt(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def chat(self, *_args, **_kwargs):
            from services.llm_provider import LLMResponse

            return LLMResponse(
                content='{"answer":"RRF 融合召回通道。 [E001]", "evidence_ids":["E001"], "insufficient_evidence":false}',
                provider=self.name,
                model=self.model,
            )

    result = RetrievedChunk(
        chunk_id="child-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="证据文章", source_provider="wechat", source_name="LaTeX工作室",
        source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
        child_text="RRF 融合两个召回通道。", parent_text="RRF 融合两个召回通道，并保留原始上下文。", score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: FakeProvider())

    answer = answer_from_evidence("怎么融合召回？", [result])

    assert answer.citations[0]["excerpt"] == "RRF 融合两个召回通道，并保留原始上下文。"


def test_v2_answer_treats_cited_partial_answer_as_not_globally_insufficient(monkeypatch):
    class FakeProvider:
        name = "fake"
        model = "fake-model"

        def chat(self, *_args, **_kwargs):
            from services.llm_provider import LLMResponse

            return LLMResponse(
                content='{"answer":"已知 RRF 的作用，其他维度缺少证据。 [E001]", "evidence_ids":["E001"], "insufficient_evidence":true}',
                provider=self.name,
                model=self.model,
            )

    result = RetrievedChunk(
        chunk_id="child-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="证据文章", source_provider="wechat", source_name="LaTeX工作室",
        source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
        child_text="RRF 融合两个召回通道。", parent_text="RRF 融合两个召回通道。", score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: FakeProvider())

    answer = answer_from_evidence("有哪些结论？", [result])

    assert not answer.insufficient_evidence
    assert answer.citations[0]["evidence_id"] == "E001"


def test_v2_answer_uses_streaming_for_thinking_provider(monkeypatch):
    class StreamingProvider:
        name = "flash"
        model = "flash-thinking"

        def chat(self, *_args, **_kwargs):
            raise AssertionError("Thinking provider should use streaming")

        def chat_stream_events(self, *_args, **_kwargs):
            from services.llm_provider import LLMStreamChunk

            yield LLMStreamChunk(reasoning_content="checking evidence")
            yield LLMStreamChunk(content='{"answer":"RRF 融合召回通道。 [E001]",')
            yield LLMStreamChunk(content='"evidence_ids":["E001"],"insufficient_evidence":false}', finish_reason="stop")

    result = RetrievedChunk(
        chunk_id="child-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="证据文章", source_provider="wechat", source_name="LaTeX工作室",
        source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
        child_text="RRF 融合两个召回通道。", parent_text="RRF 融合两个召回通道。", score=1,
    )
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: StreamingProvider())

    answer = answer_from_evidence("怎么融合召回？", [result])

    assert answer.answer.startswith("RRF")
    assert answer.citations[0]["evidence_id"] == "E001"


def test_rewrite_query_uses_flash_output_and_falls_back_on_invalid_json(monkeypatch):
    class Provider:
        name = "fake"
        model = "flash"

        def chat(self, *_args, **_kwargs):
            from services.llm_provider import LLMResponse
            return LLMResponse(content='{"search_query":"Agent Harness 架构 记忆 工具 编排"}', provider=self.name, model=self.model)

    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: Provider())
    assert rewrite_query("Agent Harness 怎么搭？") == "Agent Harness 架构 记忆 工具 编排"

    class InvalidProvider(Provider):
        def chat(self, *_args, **_kwargs):
            from services.llm_provider import LLMResponse
            return LLMResponse(content="", provider=self.name, model=self.model)

    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: InvalidProvider())
    assert rewrite_query("Agent Harness 怎么搭？") == "Agent Harness 怎么搭？"


def test_v2_pipeline_prompts_are_seeded_as_editable_templates():
    initialize_database()

    with connect() as db:
        templates = PromptTemplateRepository(db)
        active = {
            task_type: templates.get_active_template(task_type)
            for task_type in (
                "knowledge_query_rewrite",
                "knowledge_answer",
                "knowledge_answer_retry",
            )
        }

    assert {task_type: template.name for task_type, template in active.items() if template} == {
        "knowledge_query_rewrite": "检索查询改写",
        "knowledge_answer": "基于证据回答",
        "knowledge_answer_retry": "回答格式重试",
    }


def test_v2_query_and_answer_use_editable_managed_prompts(monkeypatch):
    captured: list[list[object]] = []

    class Provider:
        name = "fake"
        model = "flash"

        def chat(self, messages, **_kwargs):
            captured.append(messages)
            if len(captured) == 1:
                from services.llm_provider import LLMResponse
                return LLMResponse(content='{"search_query":"RRF 混合检索"}', provider=self.name, model=self.model)
            if len(captured) == 2:
                from services.llm_provider import LLMResponse
                return LLMResponse(
                    content='{"answer":"", "evidence_ids":[], "insufficient_evidence":false}',
                    provider=self.name,
                    model=self.model,
                )
            from services.llm_provider import LLMResponse
            return LLMResponse(
                content='{"answer":"RRF 融合召回通道。 [E001]", "evidence_ids":["E001"], "insufficient_evidence":false}',
                provider=self.name,
                model=self.model,
            )

    result = RetrievedChunk(
        chunk_id="child-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="证据文章", source_provider="wechat", source_name="LaTeX工作室",
        source_url="https://example.com/source", published_at="2026-07-29", heading_path="原理",
        child_text="RRF 融合两个召回通道。", parent_text="RRF 融合两个召回通道。", score=1,
    )
    prompts = {
        "knowledge_query_rewrite": "自定义检索改写",
        "knowledge_answer": "自定义证据回答",
        "knowledge_answer_retry": "自定义格式重试",
    }
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "default_llm_provider", lambda _model=None: Provider())
    monkeypatch.setattr(knowledge_v2, "managed_prompt_text", lambda task_type, fallback: prompts.get(task_type, fallback))

    assert rewrite_query("RRF 怎么融合？") == "RRF 混合检索"
    answer_from_evidence("RRF 怎么融合？", [result])

    assert captured[0][0].content == "自定义检索改写"
    assert captured[1][0].content == "自定义证据回答"
    assert captured[2][-1].content == "自定义格式重试"


def test_v2_query_accepts_exactly_one_knowledge_set():
    request = V2QueryRequest(
        question="这个知识集讲了什么？",
        sources=[{"provider": "wechat", "name": "LaTeX工作室"}],
    )

    assert request.sources[0].name == "LaTeX工作室"
    assert request.excluded_document_ids is None
    with pytest.raises(ValueError):
        V2QueryRequest(
            question="比较两个知识集",
            sources=[
                {"provider": "wechat", "name": "LaTeX工作室"},
                {"provider": "rss", "name": "宝玉的分享"},
            ],
        )
