from services.llm_provider import LLMStreamChunk
from services.pipeline_contracts import MAX_REASONING_CONTENT_CHARS
from services.summarizer import _build_regeneration_messages, summarize_stream


def test_regeneration_prompt_accepts_source_context_without_mutating_message():
    messages = _build_regeneration_messages(
        "测试视频",
        "完整字幕",
        "video",
        source_context={
            "author": "测试作者",
            "description": "测试描述",
            "engagement": {"like": 12},
        },
    )

    assert len(messages) == 4
    assert messages[1].role == "system"
    assert "KNOWLEDGEHUB_FOLLOWUPS_V1" in messages[1].content
    assert messages[-1].role == "user"
    assert "完整字幕" in messages[-1].content
    assert "平台辅助材料" in messages[-1].content


class _StreamingProvider:
    name = "test"
    model = "test-model"

    def chat_stream(self, _messages, *, temperature, on_usage):
        del temperature
        on_usage(None)
        yield "视频标题\n"
        yield "第一段总结"
        yield "\n第二段总结"


def test_video_summary_stream_publishes_body_without_generated_title(monkeypatch):
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **_kwargs: None)
    updates = []

    title, summary = summarize_stream(
        "00:01 字幕",
        "原始标题",
        provider=_StreamingProvider(),
        on_delta=lambda next_title, next_summary: updates.append((next_title, next_summary)),
    )

    assert title == "视频标题"
    assert summary == "第一段总结\n第二段总结"
    assert updates[-1] == ("视频标题", "第一段总结\n第二段总结")


class _ReasoningStreamingProvider:
    name = "test"
    model = "thinking-model"

    def chat_stream_events(self, _messages, *, temperature):
        del temperature
        yield LLMStreamChunk(reasoning_content="先核对")
        yield LLMStreamChunk(reasoning_content="材料边界")
        yield LLMStreamChunk(content="生成标题\n")
        yield LLMStreamChunk(content="可见摘要")


def test_automatic_summary_keeps_bounded_reasoning_out_of_visible_body(monkeypatch):
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **_kwargs: None)
    reasoning_updates = []
    summary_updates = []

    title, summary = summarize_stream(
        "字幕",
        "原始标题",
        provider=_ReasoningStreamingProvider(),
        on_delta=lambda next_title, next_summary: summary_updates.append((next_title, next_summary)),
        on_reasoning_delta=lambda reasoning, truncated: reasoning_updates.append((reasoning, truncated)),
    )

    assert title == "生成标题"
    assert summary == "可见摘要"
    assert reasoning_updates[-1] == ("先核对材料边界", False)
    assert "先核对" not in summary
    assert summary_updates[-1] == ("生成标题", "可见摘要")


class _OversizedReasoningProvider:
    name = "test"
    model = "thinking-model"

    def chat_stream_events(self, _messages, *, temperature):
        del temperature
        yield LLMStreamChunk(reasoning_content="思" * (MAX_REASONING_CONTENT_CHARS + 7))
        yield LLMStreamChunk(content="文章摘要")


def test_automatic_summary_caps_persistable_reasoning(monkeypatch):
    monkeypatch.setattr("services.summarizer.record_ai_call", lambda **_kwargs: None)
    reasoning_updates = []

    title, summary = summarize_stream(
        "正文",
        "文章标题",
        provider=_OversizedReasoningProvider(),
        task_type="article_summary",
        on_reasoning_delta=lambda reasoning, truncated: reasoning_updates.append((reasoning, truncated)),
    )

    assert title == "文章标题"
    assert summary == "文章摘要"
    assert len(reasoning_updates[-1][0]) == MAX_REASONING_CONTENT_CHARS
    assert reasoning_updates[-1][1] is True
