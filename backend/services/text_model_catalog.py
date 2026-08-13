"""Built-in text-provider metadata and backward-compatible model selections."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
THINKING_TYPES = {"enabled", "disabled"}
PROVIDER_TYPES = {"deepseek", "qwen", "mimo", "custom"}
THINKING_PARAMETERS = {"thinking", "enable_thinking", "none"}

BUILTIN_TEXT_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "deepseek",
        "type": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "thinking_parameter": "thinking",
        "model_discovery": True,
        "send_temperature": False,
        "stream_options": True,
        "response_format": True,
    },
    {
        "id": "qwen",
        "type": "qwen",
        "label": "阿里云百炼 · 千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.7-plus", "qwen3.7-max", "qwen3.6-flash"],
        "thinking_parameter": "enable_thinking",
        "model_discovery": False,
        "send_temperature": False,
        "stream_options": True,
        "response_format": True,
    },
    {
        "id": "mimo",
        "type": "mimo",
        "label": "Xiaomi MiMo",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.5", "mimo-v2.5-pro"],
        "thinking_parameter": "thinking",
        "model_discovery": False,
        "send_temperature": False,
        "stream_options": False,
        "response_format": True,
    },
)

LEGACY_MODEL_ALIASES = {
    "deepseek-chat": ("deepseek-v4-flash", "enabled"),
    "deepseek-reasoner": ("deepseek-v4-flash", "enabled"),
}


@dataclass(frozen=True)
class TextModelSelection:
    provider_id: str
    provider_type: str
    model: str
    thinking_type: str
    profile: dict[str, Any]


def secret_ref_for_provider(provider_id: str) -> str:
    return f"text-provider:{provider_id}"


def _is_loopback_hostname(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower().rstrip(".")
    if lowered == "localhost":
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def normalize_provider_base_url(value: object, provider_type: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw or len(raw) > 500:
        raise ValueError("Base URL 不能为空且不得超过 500 个字符")
    parsed = urlsplit(raw)
    if parsed.username or parsed.password:
        raise ValueError("Base URL 不得包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise ValueError("Base URL 不得包含查询参数或片段")
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        raise ValueError("Base URL 必须是完整的 HTTP(S) 地址")
    if parsed.scheme != "https" and not (
        provider_type == "custom" and _is_loopback_hostname(parsed.hostname)
    ):
        raise ValueError("云端模型服务必须使用 HTTPS；自定义 HTTP 仅允许本机回环地址")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def normalize_provider_profile(value: object, *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate = value if isinstance(value, dict) else {}
    defaults = fallback or {}
    provider_id = str(candidate.get("id") or defaults.get("id") or "").strip().lower()
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError("Provider ID 只能包含小写字母、数字、下划线和连字符")
    provider_type = str(candidate.get("type") or defaults.get("type") or "custom").strip().lower()
    if provider_type not in PROVIDER_TYPES:
        raise ValueError("不支持的文本模型 Provider 类型")
    label = str(candidate.get("label") or defaults.get("label") or provider_id).strip()[:80]
    if not label:
        raise ValueError("Provider 名称不能为空")
    base_url = normalize_provider_base_url(
        candidate.get("base_url") or defaults.get("base_url"),
        provider_type,
    )
    raw_models = candidate.get("models", defaults.get("models", []))
    models: list[str] = []
    if isinstance(raw_models, list):
        for item in raw_models:
            model = str(item or "").strip()
            if MODEL_ID_PATTERN.fullmatch(model) and model not in models:
                models.append(model)
    thinking_parameter = str(
        candidate.get("thinking_parameter")
        or defaults.get("thinking_parameter")
        or "none"
    ).strip()
    if thinking_parameter not in THINKING_PARAMETERS:
        raise ValueError("不支持的思考参数类型")
    if provider_type != "custom":
        thinking_parameter = str(defaults.get("thinking_parameter") or thinking_parameter)
        send_temperature = bool(defaults.get("send_temperature", False))
        stream_options = bool(defaults.get("stream_options", False))
        response_format = bool(defaults.get("response_format", False))
    else:
        # Unknown OpenAI-compatible servers get conservative request shapes.
        # A user may explicitly opt into each extension after verifying it.
        send_temperature = candidate.get(
            "send_temperature", defaults.get("send_temperature", False)
        ) is True
        stream_options = candidate.get(
            "stream_options", defaults.get("stream_options", False)
        ) is True
        response_format = candidate.get(
            "response_format", defaults.get("response_format", False)
        ) is True
    return {
        "id": provider_id,
        "type": provider_type,
        "label": label,
        "base_url": base_url,
        "models": models[:40],
        "thinking_parameter": thinking_parameter,
        "model_discovery": bool(
            candidate.get("model_discovery", defaults.get("model_discovery", provider_type == "custom"))
        ),
        "enabled": candidate.get("enabled", defaults.get("enabled", True)) is not False,
        "send_temperature": send_temperature,
        "stream_options": stream_options,
        "response_format": response_format,
        "secret_ref": secret_ref_for_provider(provider_id),
    }


def provider_profiles_from_settings(saved: dict[str, object]) -> list[dict[str, Any]]:
    raw_profiles = saved.get("text_providers")
    saved_by_id = {
        str(item.get("id") or "").strip().lower(): item
        for item in raw_profiles
        if isinstance(item, dict)
    } if isinstance(raw_profiles, list) else {}
    profiles: list[dict[str, Any]] = []
    for builtin in BUILTIN_TEXT_PROVIDERS:
        override = dict(saved_by_id.pop(str(builtin["id"]), {}))
        if builtin["id"] == "deepseek" and saved.get("deepseek_base_url"):
            override["base_url"] = saved["deepseek_base_url"]
        try:
            profiles.append(normalize_provider_profile(override, fallback=dict(builtin)))
        except ValueError:
            profiles.append(normalize_provider_profile(dict(builtin), fallback=dict(builtin)))
    for item in saved_by_id.values():
        try:
            profile = normalize_provider_profile(item)
        except ValueError:
            continue
        if profile["type"] == "custom":
            profiles.append(profile)
    return profiles[:24]


def resolve_model_selection(
    value: str | None,
    profiles: list[dict[str, Any]],
    *,
    default_model: str = "deepseek-v4-flash:enabled",
) -> TextModelSelection:
    raw = str(value or default_model or "deepseek-v4-flash:enabled").strip()
    thinking_type = "enabled"
    if ":" in raw:
        model_part, suffix = raw.rsplit(":", 1)
        if suffix in THINKING_TYPES:
            raw = model_part
            # Preserve the product-wide thinking contract for legacy values.
            thinking_type = "enabled"

    by_id = {str(profile["id"]): profile for profile in profiles}
    provider = by_id.get("deepseek")
    model = raw
    if "::" in raw:
        prefix, remainder = raw.split("::", 1)
        provider = by_id.get(prefix)
        if provider is None:
            raise ValueError("文本模型 selection 引用了未知 Provider")
        if not MODEL_ID_PATTERN.fullmatch(remainder):
            raise ValueError("文本模型 selection 包含无效模型名称")
        model = remainder
    # Slash is deliberately never provider syntax. Older custom DeepSeek model
    # IDs can contain slashes and must continue to round-trip unchanged.
    if provider is None:
        provider = normalize_provider_profile(dict(BUILTIN_TEXT_PROVIDERS[0]))
    if str(provider["id"]) == "deepseek" and model in LEGACY_MODEL_ALIASES:
        model, thinking_type = LEGACY_MODEL_ALIASES[model]
    if not MODEL_ID_PATTERN.fullmatch(model):
        model = str(provider.get("models", ["deepseek-v4-flash"])[0])
    return TextModelSelection(
        provider_id=str(provider["id"]),
        provider_type=str(provider["type"]),
        model=model,
        thinking_type=thinking_type,
        profile=provider,
    )


def selection_value(provider_id: str, model: str, thinking_type: str = "enabled") -> str:
    suffix = thinking_type if thinking_type in THINKING_TYPES else "enabled"
    if provider_id == "deepseek":
        return f"{model}:{suffix}"
    return f"{provider_id}::{model}:{suffix}"


def provider_model_options(profiles: list[dict[str, Any]]) -> list[dict[str, object]]:
    options: list[dict[str, object]] = []
    for profile in profiles:
        if profile.get("enabled") is False:
            continue
        for model in profile.get("models", []):
            options.append(
                {
                    "value": selection_value(str(profile["id"]), str(model)),
                    "label": str(model),
                    "model": str(model),
                    "provider": str(profile["id"]),
                    "thinking": "enabled",
                    "response_format": bool(profile.get("response_format")),
                }
            )
    return options
