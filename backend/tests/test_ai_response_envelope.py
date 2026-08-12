from __future__ import annotations

import sqlite3

from services.ai_response_envelope import (
    MAX_SUGGESTION_LENGTH,
    SUGGESTIONS_CLOSE,
    SUGGESTIONS_OPEN,
    SuggestionTrailerParser,
    normalize_suggested_questions,
)
from services.database_migrations import migration_named
from services.llm_provider import LLMResponse, LLMStreamChunk, LLMUsage
from services.summarizer import (
    answer_question_envelope,
    stream_answer_question_events,
    stream_regenerated_content_summary_events,
)


def _parse_in_chunks(raw: str, size: int):
    parser = SuggestionTrailerParser()
    visible = ""
    for start in range(0, len(raw), size):
        visible += parser.feed(raw[start:start + size])
    return visible, parser.finish()


def test_strict_trailer_is_hidden_across_every_marker_split():
    raw = "正文" + SUGGESTIONS_OPEN + '{"questions":["问题一？","问题一？","问题二？"]}' + SUGGESTIONS_CLOSE
    for size in range(1, len(SUGGESTIONS_OPEN) + 2):
        visible, envelope = _parse_in_chunks(raw, size)
        assert visible == "正文"
        assert envelope.answer == "正文"
        assert envelope.suggested_questions == ["问题一？", "问题二？"]


def test_missing_or_malformed_trailer_never_loses_answer_bytes():
    values = [
        "没有尾部的正文",
        "正文" + SUGGESTIONS_OPEN + "{bad json}" + SUGGESTIONS_CLOSE,
        "正文" + SUGGESTIONS_OPEN + '{"questions":["问题"]}',
    ]
    for raw in values:
        visible, envelope = _parse_in_chunks(raw, 3)
        expected = raw.split(SUGGESTIONS_OPEN, 1)[0] if SUGGESTIONS_OPEN in raw else raw
        assert envelope.answer == expected
        assert envelope.answer.startswith(visible)
        assert envelope.suggested_questions == []


def test_literal_trailer_example_inside_code_fence_remains_visible():
    raw = "```text\n示例" + SUGGESTIONS_OPEN + '{"questions":[]}\n```'
    visible, envelope = _parse_in_chunks(raw, 2)
    assert envelope.answer == raw
    assert raw.startswith(visible)


def test_suggestions_reject_controls_dedupe_bound_and_limit():
    assert normalize_suggested_questions([
        " 正常问题？ ", "正常问题？", "含\n换行", "x" * (MAX_SUGGESTION_LENGTH + 1),
        "第二个？", "第三个？", "第四个？",
    ]) == ["正常问题？", "第二个？", "第三个？"]


def test_oversized_trailer_is_bounded_and_keeps_body():
    parser = SuggestionTrailerParser()
    assert parser.feed("正文" + SUGGESTIONS_OPEN + ("x" * 20_000)) == "正文"
    assert len(parser._trailer) <= 8192
    envelope = parser.finish()
    assert envelope.answer == "正文"
    assert envelope.suggested_questions == []


def test_migration_093_adds_empty_metadata_without_changing_legacy_content():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE qa_messages (id TEXT PRIMARY KEY, content TEXT NOT NULL);
        CREATE TABLE knowledge_conversation_messages (id TEXT PRIMARY KEY, content TEXT NOT NULL);
        INSERT INTO qa_messages VALUES ('qa-1', '旧回答');
        INSERT INTO knowledge_conversation_messages VALUES ('knowledge-1', '旧答案');
        """
    )
    migration_named("_migration_093_ai_response_envelopes")(db)
    assert tuple(db.execute("SELECT content,reasoning_content,suggested_questions_json FROM qa_messages").fetchone()) == ("旧回答", "", "[]")
    assert tuple(db.execute("SELECT content,reasoning_content,suggested_questions_json FROM knowledge_conversation_messages").fetchone()) == ("旧答案", "", "[]")


def test_non_stream_answer_returns_pure_body_and_metadata_separately(monkeypatch):
    class Provider:
        name = "test"
        model = "test"

        def chat(self, *_args, **_kwargs):
            return LLMResponse(
                content="纯正文" + SUGGESTIONS_OPEN + '{"questions":["继续？"]}' + SUGGESTIONS_CLOSE,
                reasoning_content="内部思考",
                provider=self.name,
                model=self.model,
            )

    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **_kwargs: None)
    envelope = answer_question_envelope("问题", "摘要", "原文", provider=Provider())
    assert envelope.answer == "纯正文"
    assert envelope.reasoning_content == "内部思考"
    assert envelope.suggested_questions == ["继续？"]


class _EnvelopeStreamingProvider:
    name = "test"
    model = "test-stream"

    def chat_stream_events(self, *_args, **_kwargs):
        yield LLMStreamChunk(reasoning_content="先核对")
        yield LLMStreamChunk(content="纯正文")
        marker = SUGGESTIONS_OPEN + '{"questions":["继续？"]}' + SUGGESTIONS_CLOSE
        yield LLMStreamChunk(content=marker[:11])
        yield LLMStreamChunk(content=marker[11:])
        yield LLMStreamChunk(usage=LLMUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8))


def _assert_stream_envelope(events):
    assert "".join(event.text for event in events if event.kind == "reasoning_delta") == "先核对"
    assert "".join(event.text for event in events if event.kind == "answer_delta") == "纯正文"
    envelope = next(event.envelope for event in events if event.kind == "done")
    assert envelope.answer == "纯正文"
    assert envelope.reasoning_content == "先核对"
    assert envelope.suggested_questions == ["继续？"]


def test_production_qa_event_stream_separates_reasoning_body_and_trailer(monkeypatch):
    records = []
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **kwargs: records.append(kwargs) or None)
    events = list(stream_answer_question_events(
        "问题", "摘要", "原文", provider=_EnvelopeStreamingProvider(), ai_call_callback=lambda _record: None,
    ))
    _assert_stream_envelope(events)
    assert records[0]["provider_response"].usage.total_tokens == 8


def test_production_summary_event_stream_separates_reasoning_body_and_trailer(monkeypatch):
    records = []
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **kwargs: records.append(kwargs) or None)
    events = list(stream_regenerated_content_summary_events(
        "原文", "标题", provider=_EnvelopeStreamingProvider(), ai_call_callback=lambda _record: None,
    ))
    _assert_stream_envelope(events)
    assert records[0]["provider_response"].usage.total_tokens == 8
