from __future__ import annotations

import pytest
from services.ai_response_envelope import (
    SUGGESTIONS_CLOSE,
    SUGGESTIONS_OPEN,
    parse_suggested_questions_response,
)
from services.llm_provider import LLMResponse, LLMStreamChunk, LLMUsage
from services.summarizer import (
    answer_question_envelope,
    stream_answer_question_events,
    stream_regenerated_content_summary_events,
)


class _MissingSuggestionStreamProvider:
    name = "same-provider"
    model = "same-model"

    def __init__(self, primary_content: str = "最终正文", fallback_content: str = '{"questions":["继续追问？"]}'):
        self.primary_content = primary_content
        self.fallback_content = fallback_content
        self.fallback_messages = []
        self.fallback_calls = 0
        self.fail_fallback = False

    def chat_stream_events(self, *_args, **_kwargs):
        yield LLMStreamChunk(content=self.primary_content)
        yield LLMStreamChunk(usage=LLMUsage(prompt_tokens=4, completion_tokens=6, total_tokens=10))

    def chat(self, messages, **kwargs):
        self.fallback_calls += 1
        self.fallback_messages.append((messages, kwargs))
        if self.fail_fallback:
            raise RuntimeError("fallback unavailable")
        return LLMResponse(
            content=self.fallback_content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(prompt_tokens=2, completion_tokens=3, total_tokens=5),
        )


def _done(events):
    return next(event.envelope for event in events if event.kind == "done")


def test_fenced_and_noisy_followup_json_is_recovered_and_normalized():
    assert parse_suggested_questions_response(
        '```json\n{"questions":[" 问题一？ ","问题一？","问题二？"]}\n```'
    ) == ["问题一？", "问题二？"]
    assert parse_suggested_questions_response(
        '生成结果如下：\n{"questions":["下一步？"]}\n以上。'
    ) == ["下一步？"]


@pytest.mark.parametrize("primary_content", [
    "没有 trailer 的正文",
    "畸形 trailer 前的正文" + SUGGESTIONS_OPEN + "{bad json}" + SUGGESTIONS_CLOSE,
])
def test_missing_or_malformed_qa_trailer_calls_same_provider_once(primary_content, monkeypatch):
    records = []
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **kwargs: records.append(kwargs) or None)
    provider = _MissingSuggestionStreamProvider(
        primary_content=primary_content,
        fallback_content='说明：```json\n{"questions":["可以继续核实什么？"]}\n```',
    )

    envelope = _done(list(stream_answer_question_events(
        "当前问题", "摘要", "原始资料", provider=provider,
    )))

    assert envelope.answer.endswith("正文")
    assert envelope.suggested_questions == ["可以继续核实什么？"]
    assert provider.fallback_calls == 1
    assert provider.fallback_messages[0][1] == {
        "temperature": 0.1,
        "max_tokens": 400,
    }
    assert [record["call_type"] for record in records] == ["qa", "qa_followup_suggestions"]
    assert records[1]["provider_response"].usage.total_tokens == 5


def test_streamed_qa_answer_precedes_fallback_and_done_without_source_leak(monkeypatch):
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **_kwargs: None)
    provider = _MissingSuggestionStreamProvider()
    stream = stream_answer_question_events(
        "当前问题",
        "不可泄露的旧摘要",
        "不可泄露的完整原始资料",
        history=[{"question": "不可泄露的历史问题", "answer": "不可泄露的历史答案"}],
        provider=provider,
    )

    first = next(stream)
    assert first.kind == "answer_delta"
    assert first.text == "最终正文"
    assert provider.fallback_calls == 0

    remaining = list(stream)
    assert [event.kind for event in remaining] == ["done"]
    assert provider.fallback_calls == 1
    fallback_prompt = "\n".join(message.content for message in provider.fallback_messages[0][0])
    assert "当前问题" in fallback_prompt
    assert "最终正文" in fallback_prompt
    assert "不可泄露的旧摘要" not in fallback_prompt
    assert "不可泄露的完整原始资料" not in fallback_prompt
    assert "不可泄露的历史问题" not in fallback_prompt


def test_fallback_failure_is_recorded_but_never_fails_the_streamed_answer(monkeypatch):
    records = []
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **kwargs: records.append(kwargs) or None)
    provider = _MissingSuggestionStreamProvider()
    provider.fail_fallback = True

    envelope = _done(list(stream_answer_question_events(
        "当前问题", "摘要", "原始资料", provider=provider,
    )))

    assert envelope.answer == "最终正文"
    assert envelope.suggested_questions == []
    fallback_record = next(record for record in records if record["call_type"] == "qa_followup_suggestions")
    assert fallback_record["provider_response"] is None
    assert fallback_record["error"] == "fallback unavailable"


def test_non_stream_qa_uses_one_bounded_fallback_without_source_or_history(monkeypatch):
    records = []
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **kwargs: records.append(kwargs) or None)

    class Provider:
        name = "same-provider"
        model = "same-model"

        def __init__(self):
            self.calls = []

        def chat(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            if len(self.calls) == 1:
                return LLMResponse(content="非流正文", provider=self.name, model=self.model)
            return LLMResponse(
                content='```json\n{"questions":["非流建议？"]}\n```',
                provider=self.name,
                model=self.model,
            )

    provider = Provider()
    envelope = answer_question_envelope(
        "当前非流问题",
        "不可泄露摘要",
        "不可泄露原文",
        history=[{"question": "不可泄露历史", "answer": "历史回答"}],
        provider=provider,
        ai_call_callback=lambda _record: None,
    )

    assert envelope.answer == "非流正文"
    assert envelope.suggested_questions == ["非流建议？"]
    assert len(provider.calls) == 2
    fallback_prompt = "\n".join(message.content for message in provider.calls[1][0])
    assert "当前非流问题" in fallback_prompt
    assert "非流正文" in fallback_prompt
    assert "不可泄露摘要" not in fallback_prompt
    assert "不可泄露原文" not in fallback_prompt
    assert "不可泄露历史" not in fallback_prompt
    assert [record["call_type"] for record in records] == ["qa", "qa_followup_suggestions"]


def test_manual_summary_fallback_uses_title_and_final_body_only(monkeypatch):
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **_kwargs: None)
    provider = _MissingSuggestionStreamProvider(primary_content="摘要正文")

    envelope = _done(list(stream_regenerated_content_summary_events(
        "不可泄露的文章原文",
        "摘要主题标题",
        provider=provider,
    )))

    assert envelope.suggested_questions == ["继续追问？"]
    assert provider.fallback_calls == 1
    fallback_prompt = "\n".join(message.content for message in provider.fallback_messages[0][0])
    assert "摘要主题标题" in fallback_prompt
    assert "摘要正文" in fallback_prompt
    assert "不可泄露的文章原文" not in fallback_prompt
