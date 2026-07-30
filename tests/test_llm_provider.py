from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from services.llm_provider import LLMMessage, OpenAICompatibleProvider


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def create(self, **request):
        self.calls.append(request)
        if request.get("stream"):
            return iter([
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                reasoning_content="先分析来源关系。",
                            ),
                            finish_reason=None,
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content='{"sections":[]}',
                                reasoning_content=None,
                            ),
                            finish_reason=None,
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                reasoning_content=None,
                            ),
                            finish_reason="stop",
                        )
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[],
                    usage=SimpleNamespace(
                        prompt_tokens=12,
                        completion_tokens=8,
                        total_tokens=20,
                        prompt_cache_hit_tokens=4,
                        prompt_cache_miss_tokens=8,
                    ),
                ),
            ])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"sections":[]}'),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


def test_json_object_uses_standard_chat_completion_response_format():
    completions = _FakeCompletions()
    provider = object.__new__(OpenAICompatibleProvider)
    provider.name = "deepseek"
    provider.model = "deepseek-v4-pro"
    provider.thinking_type = "enabled"
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    response = provider.chat(
        [LLMMessage(role="user", content="返回栏目规划 JSON")],
        temperature=0.0,
        response_format="json_object",
    )

    assert response.content == '{"sections":[]}'
    assert response.finish_reason == "stop"
    assert len(completions.calls) == 1
    request = completions.calls[0]
    assert request["response_format"] == {"type": "json_object"}
    assert request["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "tools" not in request
    assert "tool_choice" not in request


def test_stream_events_separate_reasoning_from_json_content():
    completions = _FakeCompletions()
    provider = object.__new__(OpenAICompatibleProvider)
    provider.name = "deepseek"
    provider.model = "deepseek-v4-pro"
    provider.thinking_type = "enabled"
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions)
    )

    chunks = list(provider.chat_stream_events(
        [LLMMessage(role="user", content="返回栏目规划 JSON")],
        temperature=0.0,
        response_format="json_object",
    ))

    assert "".join(chunk.reasoning_content for chunk in chunks) == "先分析来源关系。"
    assert "".join(chunk.content for chunk in chunks) == '{"sections":[]}'
    assert next(
        chunk.finish_reason for chunk in chunks if chunk.finish_reason
    ) == "stop"
    usage = next(chunk.usage for chunk in chunks if chunk.usage)
    assert usage.total_tokens == 20
    request = completions.calls[0]
    assert request["stream"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["response_format"] == {"type": "json_object"}
    assert "tools" not in request
    assert "tool_choice" not in request
