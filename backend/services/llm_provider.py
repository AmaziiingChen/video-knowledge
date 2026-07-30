from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterator
import re
from typing import Protocol

from openai import OpenAI

from config import settings

DEEPSEEK_MODEL_OPTIONS = [
    {
        "value": "deepseek-v4-flash:enabled",
        "label": "deepseek-v4-flash",
        "model": "deepseek-v4-flash",
        "thinking": "enabled",
    },
    {
        "value": "deepseek-v4-pro:enabled",
        "label": "deepseek-v4-pro",
        "model": "deepseek-v4-pro",
        "thinking": "enabled",
    },
]

_DEEPSEEK_MODELS = {"deepseek-v4-flash", "deepseek-v4-pro"}
_THINKING_TYPES = {"enabled", "disabled"}
_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
_LEGACY_MODEL_ALIASES = {
    "deepseek-chat": ("deepseek-v4-flash", "enabled"),
    "deepseek-reasoner": ("deepseek-v4-flash", "enabled"),
}

ResponseFormat = str | None


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    usage: LLMUsage | None = None
    finish_reason: str | None = None
    reasoning_content: str = ""


@dataclass(frozen=True)
class LLMStreamChunk:
    content: str = ""
    reasoning_content: str = ""
    usage: LLMUsage | None = None
    finish_reason: str | None = None


class LLMProvider(Protocol):
    name: str
    model: str

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...
    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        on_usage: Callable[[LLMUsage], None] | None = None,
    ) -> Iterator[str]: ...
    def chat_stream_events(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> Iterator[LLMStreamChunk]: ...


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        thinking_type: str = "enabled",
        provider_name: str = "openai_compatible",
        request_timeout_seconds: float | None = None,
    ) -> None:
        self.name = provider_name
        self.model = model
        self.thinking_type = thinking_type
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=max(
                5.0,
                float(settings.llm_request_timeout_seconds if request_timeout_seconds is None else request_timeout_seconds),
            ),
            max_retries=0,
        )

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        extra_body = {"thinking": {"type": self.thinking_type}}
        request: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "temperature": temperature,
            "extra_body": extra_body,
        }
        if response_format == "json_object":
            request["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            request["max_tokens"] = max(1, int(max_tokens))
        response = self._client.chat.completions.create(
            **request,
        )
        choice = response.choices[0]
        content = (choice.message.content or "").strip()
        reasoning_content = str(
            getattr(choice.message, "reasoning_content", "") or ""
        )
        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            usage=LLMUsage(
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                total_tokens=getattr(usage, "total_tokens", None),
                prompt_cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", None),
                prompt_cache_miss_tokens=getattr(usage, "prompt_cache_miss_tokens", None),
            ) if usage else None,
            finish_reason=str(getattr(choice, "finish_reason", "") or "") or None,
            reasoning_content=reasoning_content,
        )

    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        on_usage: Callable[[LLMUsage], None] | None = None,
    ) -> Iterator[str]:
        for chunk in self.chat_stream_events(
            messages,
            temperature=temperature,
        ):
            if chunk.usage and on_usage:
                on_usage(chunk.usage)
            if chunk.content:
                yield chunk.content

    def chat_stream_events(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> Iterator[LLMStreamChunk]:
        extra_body = {"thinking": {"type": self.thinking_type}}
        request: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
            "extra_body": extra_body,
        }
        if response_format == "json_object":
            request["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            request["max_tokens"] = max(1, int(max_tokens))
        stream = self._client.chat.completions.create(**request)
        for event in stream:
            usage = getattr(event, "usage", None)
            normalized_usage = (
                LLMUsage(
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                    prompt_cache_hit_tokens=getattr(usage, "prompt_cache_hit_tokens", None),
                    prompt_cache_miss_tokens=getattr(usage, "prompt_cache_miss_tokens", None),
                )
                if usage
                else None
            )
            if not event.choices:
                if normalized_usage:
                    yield LLMStreamChunk(usage=normalized_usage)
                continue
            choice = event.choices[0]
            delta = getattr(choice, "delta", None)
            text = getattr(delta, "content", None) if delta else None
            reasoning = (
                getattr(delta, "reasoning_content", None)
                if delta
                else None
            )
            finish_reason = (
                str(getattr(choice, "finish_reason", "") or "") or None
            )
            if text or reasoning or normalized_usage or finish_reason:
                yield LLMStreamChunk(
                    content=str(text or ""),
                    reasoning_content=str(reasoning or ""),
                    usage=normalized_usage,
                    finish_reason=finish_reason,
                )


def resolve_deepseek_model(model: str | None = None) -> tuple[str, str]:
    raw_model = (model or settings.deepseek_model or "deepseek-v4-flash:enabled").strip()
    thinking_type = "enabled"

    if ":" in raw_model:
        raw_model, raw_thinking = raw_model.split(":", 1)
        if raw_thinking in _THINKING_TYPES:
            # Thinking is now the product-wide contract. Accept old persisted
            # values so upgrades do not fail, but never send a direct-mode
            # request after the setting has been retired from the UI.
            thinking_type = "enabled"

    if raw_model in _LEGACY_MODEL_ALIASES:
        return _LEGACY_MODEL_ALIASES[raw_model]

    # Desktop users may point the OpenAI-compatible endpoint at a newer
    # provider model before the application has a built-in preset for it.
    # Keep the legacy fallback for malformed values, but do not silently
    # replace a valid user-selected model with an old preset.
    if not _MODEL_NAME_PATTERN.fullmatch(raw_model):
        raw_model = "deepseek-v4-flash"

    return raw_model, thinking_type


def deepseek_model_option_value(model: str | None = None) -> str:
    resolved_model, thinking_type = resolve_deepseek_model(model)
    return f"{resolved_model}:{thinking_type}"


def default_llm_provider(model: str | None = None) -> LLMProvider:
    resolved_model, thinking_type = resolve_deepseek_model(model)
    return OpenAICompatibleProvider(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=resolved_model,
        thinking_type=thinking_type,
        provider_name="deepseek",
    )
