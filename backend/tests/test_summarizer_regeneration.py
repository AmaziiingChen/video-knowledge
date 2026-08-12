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
