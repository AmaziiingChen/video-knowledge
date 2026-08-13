from __future__ import annotations

from services.knowledge_response_transport import collect_model_response
from services.knowledge_v2 import _answer_model_response
from services.llm_provider import LLMMessage, LLMStreamChunk, LLMUsage


class _StreamingProvider:
    name = "provider"
    model = "model"

    def chat_stream_events(self, *_args, **_kwargs):
        yield object()
        yield LLMStreamChunk(reasoning_content="思考")
        yield LLMStreamChunk(content=" {\"answer\":")
        yield LLMStreamChunk(
            content="\"完成\"} ",
            usage=LLMUsage(prompt_tokens=3, completion_tokens=5, total_tokens=8),
            finish_reason="stop",
        )


def test_stream_transport_preserves_final_content_reasoning_and_usage():
    response = collect_model_response(
        _StreamingProvider(),
        [LLMMessage(role="user", content="问题")],
        temperature=0.1,
        response_format="json_object",
        max_tokens=100,
    )

    assert response.content == '{"answer":"完成"}'
    assert response.reasoning_content == "思考"
    assert response.usage.total_tokens == 8
    assert response.finish_reason == "stop"
    assert _answer_model_response is collect_model_response
