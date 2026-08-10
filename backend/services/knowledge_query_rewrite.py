"""Model-assisted, fail-open query rewriting for knowledge retrieval."""
from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Callable, Iterable

from config import settings

from services.llm_provider import LLMMessage
from services.prompt_templates import DEFAULT_KNOWLEDGE_QUERY_REWRITE_PROMPT


def parse_json_object(value: str) -> dict[str, object]:
    raw = str(value or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("模型没有返回有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    return parsed


def rewrite_knowledge_query(
    question: str,
    *,
    conversation_context: Iterable[dict[str, object]] | None,
    task_id: str | None,
    model: str,
    provider_factory: Callable[[str], object],
    conversation_message_builder: Callable[[Iterable[dict[str, object]] | None], list[LLMMessage]],
    conversation_guardrail: str,
    prompt_loader: Callable[[str, str], str],
    call_recorder: Callable[..., object],
) -> str:
    """Rewrite vague questions without letting model failure block retrieval."""
    original = str(question or "").strip()
    if not original or not settings.deepseek_api_key:
        return original
    messages = [
        LLMMessage(
            role="system",
            content=prompt_loader("knowledge_query_rewrite", DEFAULT_KNOWLEDGE_QUERY_REWRITE_PROMPT),
        ),
        LLMMessage(role="system", content=conversation_guardrail),
        *conversation_message_builder(conversation_context),
        LLMMessage(role="user", content=f"用户问题：{original}"),
    ]
    started = perf_counter()
    try:
        response = provider_factory(model).chat(
            messages,
            temperature=0,
            response_format="json_object",
            max_tokens=800,
        )
        rewritten = re.sub(r"\s+", " ", str(parse_json_object(response.content).get("search_query") or "")).strip()
        if not 2 <= len(rewritten) <= 320:
            raise ValueError("查询改写结果为空或过长")
    except Exception as exc:
        call_recorder(
            call_type="knowledge_v2_query_rewrite",
            provider_response=None,
            input_chars=sum(len(message.content) for message in messages),
            elapsed_seconds=perf_counter() - started,
            task_id=task_id,
            error=str(exc),
        )
        return original
    call_recorder(
        call_type="knowledge_v2_query_rewrite",
        provider_response=response,
        input_chars=sum(len(message.content) for message in messages),
        output_chars=len(rewritten),
        elapsed_seconds=perf_counter() - started,
        task_id=task_id,
    )
    return rewritten
