"""Collect complete model responses for grounded knowledge answer stages."""

from __future__ import annotations

from services.llm_provider import LLMMessage, LLMResponse, LLMStreamChunk, LLMUsage


def collect_model_response(
    provider: object,
    messages: list[LLMMessage],
    *,
    temperature: float,
    response_format: str,
    max_tokens: int,
) -> LLMResponse:
    """Use provider streaming when available while retaining final metadata."""
    stream = getattr(provider, "chat_stream_events", None)
    if not callable(stream):
        return provider.chat(
            messages,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
        )
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    usage: LLMUsage | None = None
    finish_reason: str | None = None
    for event in stream(
        messages,
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
    ):
        if not isinstance(event, LLMStreamChunk):
            continue
        if event.content:
            content_parts.append(event.content)
        if event.reasoning_content:
            reasoning_parts.append(event.reasoning_content)
        if event.usage:
            usage = event.usage
        if event.finish_reason:
            finish_reason = event.finish_reason
    return LLMResponse(
        content="".join(content_parts).strip(),
        provider=str(getattr(provider, "name", "unknown")),
        model=str(getattr(provider, "model", "unknown")),
        usage=usage,
        finish_reason=finish_reason,
        reasoning_content="".join(reasoning_parts),
    )
