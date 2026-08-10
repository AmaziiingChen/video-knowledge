from services import knowledge_v2
from services.knowledge_query_rewrite import (
    DEFAULT_KNOWLEDGE_QUERY_REWRITE_PROMPT,
    parse_json_object,
    rewrite_knowledge_query,
)
from services.llm_provider import LLMResponse


def test_query_rewrite_uses_flash_and_records_the_rewritten_query(monkeypatch):
    calls = []
    requested_models = []
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")

    class Provider:
        def chat(self, messages, **kwargs):
            assert messages[-1].content == "用户问题：原问题"
            assert kwargs == {"temperature": 0, "response_format": "json_object", "max_tokens": 800}
            return LLMResponse(content='{"search_query":"  RRF   融合  "}', provider="test", model="flash")

    rewritten = rewrite_knowledge_query(
        "原问题",
        conversation_context=[],
        task_id="rewrite:test",
        model="deepseek-v4-flash:enabled",
        provider_factory=lambda model: requested_models.append(model) or Provider(),
        conversation_message_builder=lambda _context: [],
        conversation_guardrail="guardrail",
        prompt_loader=lambda _task_type, default: default,
        call_recorder=lambda **entry: calls.append(entry),
    )

    assert rewritten == "RRF 融合"
    assert requested_models == ["deepseek-v4-flash:enabled"]
    assert calls[-1]["provider_response"].content
    assert calls[-1]["task_id"] == "rewrite:test"


def test_query_rewrite_keeps_the_original_question_when_the_model_response_is_invalid(monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_v2.settings, "deepseek_api_key", "test-key")

    class Provider:
        def chat(self, *_args, **_kwargs):
            return LLMResponse(content="not-json", provider="test", model="flash")

    original = rewrite_knowledge_query(
        "原问题",
        conversation_context=None,
        task_id=None,
        model="deepseek-v4-flash:enabled",
        provider_factory=lambda _model: Provider(),
        conversation_message_builder=lambda _context: [],
        conversation_guardrail="guardrail",
        prompt_loader=lambda _task_type, default: default,
        call_recorder=lambda **entry: calls.append(entry),
    )

    assert original == "原问题"
    assert calls[-1]["provider_response"] is None
    assert "有效 JSON" in calls[-1]["error"]


def test_knowledge_v2_keeps_the_structured_response_parser_compatibility_alias():
    assert knowledge_v2._parse_answer_json is parse_json_object
    assert knowledge_v2.DEFAULT_KNOWLEDGE_QUERY_REWRITE_PROMPT == DEFAULT_KNOWLEDGE_QUERY_REWRITE_PROMPT
