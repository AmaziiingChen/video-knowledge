"""Bounded, deterministic prior-turn context for grounded knowledge Q&A."""

from __future__ import annotations

from collections.abc import Iterable

from services.llm_provider import LLMMessage

CONVERSATION_CONTEXT_MAX_EXCHANGES = 4
CONVERSATION_CONTEXT_QUESTION_MAX_CHARS = 500
CONVERSATION_CONTEXT_ANSWER_MAX_CHARS = 1_200


def conversation_context_messages(
    messages: Iterable[dict[str, object]] | None,
) -> list[LLMMessage]:
    """Return the latest completed exchanges as a safe, bounded message prefix."""
    if not messages:
        return []
    exchanges: list[tuple[str, str]] = []
    pending_question = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "")
        content = str(message.get("content") or "").strip()
        if role == "user":
            pending_question = content
        elif role == "assistant" and pending_question:
            if content:
                exchanges.append((pending_question, content))
            pending_question = ""
    context: list[LLMMessage] = []
    for prior_question, prior_answer in exchanges[-CONVERSATION_CONTEXT_MAX_EXCHANGES:]:
        context.append(
            LLMMessage(
                role="user",
                content=f"用户问题：{_truncate(prior_question, CONVERSATION_CONTEXT_QUESTION_MAX_CHARS)}",
            )
        )
        context.append(
            LLMMessage(
                role="assistant",
                content=_truncate(prior_answer, CONVERSATION_CONTEXT_ANSWER_MAX_CHARS),
            )
        )
    return context


def _truncate(value: str, limit: int) -> str:
    compact = str(value or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)].rstrip() + "…"
