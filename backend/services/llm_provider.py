from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

import httpx
from config import settings
from openai import OpenAI

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
        thinking_parameter: str = "thinking",
        send_temperature: bool = True,
        supports_stream_options: bool = True,
        supports_response_format: bool = True,
        provider_name: str = "openai_compatible",
        request_timeout_seconds: float | None = None,
    ) -> None:
        self.name = provider_name
        self.model = model
        self.thinking_type = thinking_type
        self.thinking_parameter = thinking_parameter
        self.send_temperature = send_temperature
        self.supports_stream_options = supports_stream_options
        self.supports_response_format = supports_response_format
        self._api_key_redaction = api_key
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=max(
                5.0,
                float(settings.llm_request_timeout_seconds if request_timeout_seconds is None else request_timeout_seconds),
            ),
            max_retries=0,
            http_client=httpx.Client(follow_redirects=False, trust_env=False),
        )

    def _extra_body(self) -> dict[str, object] | None:
        parameter = getattr(self, "thinking_parameter", "thinking")
        if parameter == "thinking":
            return {"thinking": {"type": self.thinking_type}}
        if parameter == "enable_thinking":
            return {"enable_thinking": self.thinking_type == "enabled"}
        return None

    def _reasoning_effort(self) -> str | None:
        # DeepSeek V4 accepts the thinking switch and effort as separate
        # controls. Send both explicitly so a saved thinking selection cannot
        # silently fall back to a response without reasoning metadata.
        if self.name == "deepseek" and self.thinking_type == "enabled":
            return "high"
        return None

    def _safe_error(self, exc: Exception) -> RuntimeError:
        secret = str(getattr(self, "_api_key_redaction", "") or "")
        detail = str(exc).replace(secret, "••••") if secret else str(exc)
        return RuntimeError(detail[:1000] or "文本模型服务调用失败")

    @staticmethod
    def _usage(value: object | None) -> LLMUsage | None:
        if value is None:
            return None
        prompt_tokens = getattr(value, "prompt_tokens", None)
        hit_tokens = getattr(value, "prompt_cache_hit_tokens", None)
        miss_tokens = getattr(value, "prompt_cache_miss_tokens", None)
        prompt_details = getattr(value, "prompt_tokens_details", None)
        if hit_tokens is None and prompt_details is not None:
            hit_tokens = getattr(prompt_details, "cached_tokens", None)
        if miss_tokens is None and prompt_tokens is not None and hit_tokens is not None:
            miss_tokens = max(0, int(prompt_tokens) - int(hit_tokens))
        return LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=getattr(value, "completion_tokens", None),
            total_tokens=getattr(value, "total_tokens", None),
            prompt_cache_hit_tokens=hit_tokens,
            prompt_cache_miss_tokens=miss_tokens,
        )

    def list_models(self) -> list[str]:
        try:
            response = self._client.models.list()
        except Exception as exc:
            raise self._safe_error(exc) from exc
        result: list[str] = []
        for item in getattr(response, "data", []) or []:
            model_id = str(getattr(item, "id", "") or "").strip()
            if model_id and model_id not in result:
                result.append(model_id)
        return result

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        request: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
        }
        if getattr(self, "send_temperature", True):
            request["temperature"] = temperature
        extra_body = self._extra_body()
        if extra_body:
            request["extra_body"] = extra_body
        reasoning_effort = self._reasoning_effort()
        if reasoning_effort:
            request["reasoning_effort"] = reasoning_effort
        if response_format == "json_object":
            if not getattr(self, "supports_response_format", True):
                raise ValueError("当前 Provider 未声明支持 JSON Object 输出")
            request["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            request["max_tokens"] = max(1, int(max_tokens))
        try:
            response = self._client.chat.completions.create(**request)
        except Exception as exc:
            raise self._safe_error(exc) from exc
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
            usage=self._usage(usage),
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
        request: dict[str, object] = {
            "model": self.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "stream": True,
        }
        if getattr(self, "send_temperature", True):
            request["temperature"] = temperature
        if getattr(self, "supports_stream_options", True):
            request["stream_options"] = {"include_usage": True}
        extra_body = self._extra_body()
        if extra_body:
            request["extra_body"] = extra_body
        reasoning_effort = self._reasoning_effort()
        if reasoning_effort:
            request["reasoning_effort"] = reasoning_effort
        if response_format == "json_object":
            if not getattr(self, "supports_response_format", True):
                raise ValueError("当前 Provider 未声明支持 JSON Object 输出")
            request["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            request["max_tokens"] = max(1, int(max_tokens))
        try:
            stream = self._client.chat.completions.create(**request)
            yield from self._stream_chunks(stream)
        except Exception as exc:
            raise self._safe_error(exc) from exc

    def _stream_chunks(self, stream: object) -> Iterator[LLMStreamChunk]:
        for event in stream:
            usage = getattr(event, "usage", None)
            normalized_usage = self._usage(usage)
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
    # Imported lazily to keep settings persistence independent from the client
    # implementation while still resolving the latest saved provider profile.
    from services.llm_settings import resolve_text_model_runtime

    runtime = resolve_text_model_runtime(model)
    return OpenAICompatibleProvider(
        api_key=runtime["api_key"],
        base_url=runtime["base_url"],
        model=runtime["model"],
        thinking_type=runtime["thinking_type"],
        thinking_parameter=runtime["thinking_parameter"],
        send_temperature=runtime["send_temperature"],
        supports_stream_options=runtime["stream_options"],
        supports_response_format=runtime["response_format"],
        provider_name=runtime["provider_id"],
    )
