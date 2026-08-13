from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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
    assert request["reasoning_effort"] == "high"
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
    assert request["reasoning_effort"] == "high"
    assert "tools" not in request
    assert "tool_choice" not in request


def test_qwen_uses_enable_thinking_while_custom_sends_no_vendor_parameter():
    completions = _FakeCompletions()
    provider = object.__new__(OpenAICompatibleProvider)
    provider.name = "qwen"
    provider.model = "qwen3.7-plus"
    provider.thinking_type = "enabled"
    provider.thinking_parameter = "enable_thinking"
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider.chat([LLMMessage(role="user", content="test")])
    assert completions.calls[-1]["extra_body"] == {"enable_thinking": True}
    assert "reasoning_effort" not in completions.calls[-1]

    provider.name = "custom"
    provider.thinking_parameter = "none"
    provider.chat([LLMMessage(role="user", content="test")])
    assert "extra_body" not in completions.calls[-1]
    assert "reasoning_effort" not in completions.calls[-1]


@pytest.mark.parametrize(
    (
        "provider_name",
        "thinking_parameter",
        "send_temperature",
        "stream_options",
        "response_format",
        "expected_extra_body",
    ),
    [
        ("deepseek", "thinking", False, True, True, {"thinking": {"type": "enabled"}}),
        ("qwen", "enable_thinking", False, True, True, {"enable_thinking": True}),
        ("mimo", "thinking", False, False, True, {"thinking": {"type": "enabled"}}),
        ("custom", "none", False, False, False, None),
    ],
)
def test_provider_capabilities_control_request_shape(
    provider_name,
    thinking_parameter,
    send_temperature,
    stream_options,
    response_format,
    expected_extra_body,
):
    completions = _FakeCompletions()
    provider = object.__new__(OpenAICompatibleProvider)
    provider.name = provider_name
    provider.model = "test-model"
    provider.thinking_type = "enabled"
    provider.thinking_parameter = thinking_parameter
    provider.send_temperature = send_temperature
    provider.supports_stream_options = stream_options
    provider.supports_response_format = response_format
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    if response_format:
        list(provider.chat_stream_events(
            [LLMMessage(role="user", content="test")],
            temperature=0.7,
            response_format="json_object",
        ))
    else:
        with pytest.raises(ValueError, match="未声明支持"):
            list(provider.chat_stream_events(
                [LLMMessage(role="user", content="test")],
                response_format="json_object",
            ))
        list(provider.chat_stream_events([LLMMessage(role="user", content="test")]))

    request = completions.calls[-1]
    assert ("temperature" in request) is send_temperature
    assert ("stream_options" in request) is stream_options
    assert ("response_format" in request) is response_format
    if expected_extra_body is None:
        assert "extra_body" not in request
    else:
        assert request["extra_body"] == expected_extra_body


def test_provider_error_is_redacted_at_boundary_and_not_retried():
    secret = "provider-secret"

    class FailingCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **_request):
            self.calls += 1
            raise RuntimeError(f"authorization failed for {secret}")

    completions = FailingCompletions()
    provider = object.__new__(OpenAICompatibleProvider)
    provider.name = "custom"
    provider.model = "test-model"
    provider.thinking_type = "enabled"
    provider.thinking_parameter = "none"
    provider.send_temperature = False
    provider.supports_response_format = False
    provider._api_key_redaction = secret
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    with pytest.raises(RuntimeError) as error:
        provider.chat([LLMMessage(role="user", content="test")])
    assert secret not in str(error.value)
    assert completions.calls == 1
