from services.knowledge_v2 import (
    CONVERSATION_CONTEXT_ANSWER_MAX_CHARS,
    CONVERSATION_CONTEXT_MAX_EXCHANGES,
    KNOWLEDGE_REWRITE_MODEL,
    RetrievedChunk,
    _conversation_context_messages,
    answer_from_evidence,
    rewrite_query,
    stream_answer_from_evidence,
)
from services.llm_provider import LLMResponse, LLMStreamChunk
from services import knowledge_v2
from config import settings


def test_conversation_context_keeps_latest_completed_exchanges_in_role_order():
    messages = []
    for index in range(CONVERSATION_CONTEXT_MAX_EXCHANGES + 2):
        messages.extend([
            {"role": "user", "content": f"问题 {index}"},
            {"role": "assistant", "content": f"回答 {index}"},
        ])
    messages.append({"role": "user", "content": "尚未回答的问题"})

    context = _conversation_context_messages(messages)

    assert [message.role for message in context] == ["user", "assistant"] * CONVERSATION_CONTEXT_MAX_EXCHANGES
    assert context[0].content == "用户问题：问题 2"
    assert context[-1].content == f"回答 {CONVERSATION_CONTEXT_MAX_EXCHANGES + 1}"


def test_conversation_context_truncates_previous_answers_deterministically():
    context = _conversation_context_messages([
        {"role": "user", "content": "上一个问题"},
        {"role": "assistant", "content": "答" * (CONVERSATION_CONTEXT_ANSWER_MAX_CHARS + 10)},
    ])

    assert len(context[1].content) == CONVERSATION_CONTEXT_ANSWER_MAX_CHARS
    assert context[1].content.endswith("…")


class _JsonProvider:
    def __init__(self, content):
        self.content = content
        self.name = "test"
        self.model = "test-model"

    def chat(self, *_args, **_kwargs):
        return LLMResponse(content=self.content, provider=self.name, model=self.model)


class _StreamingJsonProvider(_JsonProvider):
    def chat_stream_events(self, *_args, **_kwargs):
        yield LLMStreamChunk(content=self.content)


def test_knowledge_rewrite_is_always_sent_to_flash(monkeypatch):
    requested_models = []
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "managed_prompt_text", lambda _task_type, default: default)
    monkeypatch.setattr(knowledge_v2, "record_ai_call", lambda **_kwargs: None)
    monkeypatch.setattr(
        knowledge_v2,
        "default_llm_provider",
        lambda model=None: requested_models.append(model) or _JsonProvider('{"search_query":"测试检索词"}'),
    )

    assert rewrite_query("测试问题") == "测试检索词"
    assert requested_models == [KNOWLEDGE_REWRITE_MODEL]


def test_final_answer_uses_the_requested_model(monkeypatch):
    requested_models = []
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "managed_prompt_text", lambda _task_type, default: default)
    monkeypatch.setattr(knowledge_v2, "record_ai_call", lambda **_kwargs: None)
    monkeypatch.setattr(
        knowledge_v2,
        "default_llm_provider",
        lambda model=None: requested_models.append(model) or _JsonProvider(
            '{"answer":"证据支持该结论 [E001]","evidence_ids":["E001"],"insufficient_evidence":false}'
        ),
    )
    result = RetrievedChunk(
        chunk_id="chunk-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="测试文章", source_provider="wechat", source_name="测试号", source_url="",
        published_at="", heading_path="正文", child_text="证据支持该结论。", parent_text="证据支持该结论。", score=1.0,
    )

    answer = answer_from_evidence("结论是什么？", [result], model="deepseek-v4-flash")

    assert answer.answer == "证据支持该结论 [E001]"
    assert requested_models == ["deepseek-v4-flash"]


def test_streamed_final_answer_uses_the_requested_model(monkeypatch):
    requested_models = []
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(knowledge_v2, "managed_prompt_text", lambda _task_type, default: default)
    monkeypatch.setattr(knowledge_v2, "record_ai_call", lambda **_kwargs: None)
    monkeypatch.setattr(
        knowledge_v2,
        "default_llm_provider",
        lambda model=None: requested_models.append(model) or _StreamingJsonProvider(
            '{"answer":"证据支持该结论 [E001]","evidence_ids":["E001"],"insufficient_evidence":false}'
        ),
    )
    result = RetrievedChunk(
        chunk_id="chunk-1", parent_chunk_id="parent-1", content_item_id="content-1",
        title="测试文章", source_provider="wechat", source_name="测试号", source_url="",
        published_at="", heading_path="正文", child_text="证据支持该结论。", parent_text="证据支持该结论。", score=1.0,
    )

    events = list(stream_answer_from_evidence("结论是什么？", [result], model="deepseek-v4-flash"))

    assert events[-1][0] == "done"
    assert requested_models == ["deepseek-v4-flash"]
