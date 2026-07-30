from __future__ import annotations

import json
import math
import re
from time import perf_counter

from openai import OpenAI

from config import DEFAULT_DEEPSEEK_PRICING, default_deepseek_pricing, settings
from services.ai_call_logger import backfill_missing_deepseek_costs, record_ai_call
from services.llm_provider import LLMMessage, OpenAICompatibleProvider, resolve_deepseek_model


SETTINGS_FILE = "llm_settings.json"
# Semantic embeddings are intentionally paused while the feature is under
# development. Keep the saved configuration so users do not need to re-enter
# it when the feature is re-enabled, but never permit a runtime API call.
CAMPUS_EMBEDDINGS_ENABLED = False
_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")


def _path():
    return settings.data_dir / SETTINGS_FILE


def load_llm_settings() -> dict[str, object]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_saved_llm_settings() -> dict[str, object]:
    saved = load_llm_settings()
    # Environment variables remain a valid deployment mechanism. A value saved
    # in the local settings screen deliberately takes precedence for desktop use.
    if "deepseek_api_key" in saved:
        settings.deepseek_api_key = str(saved["deepseek_api_key"] or "").strip()
    if saved.get("deepseek_base_url"):
        settings.deepseek_base_url = str(saved["deepseek_base_url"]).strip()
    settings.deepseek_pricing = _normalize_deepseek_pricing(saved.get("deepseek_pricing"))
    settings.deepseek_peak_pricing_multiplier = _normalize_peak_pricing_multiplier(
        saved.get("deepseek_peak_pricing_multiplier")
    )
    if "campus_embedding_api_key" in saved:
        settings.campus_embedding_api_key = str(saved["campus_embedding_api_key"] or "").strip()
    if saved.get("campus_embedding_api_base_url"):
        settings.campus_embedding_api_base_url = str(saved["campus_embedding_api_base_url"]).strip()
    if saved.get("campus_embedding_api_model"):
        settings.campus_embedding_api_model = str(saved["campus_embedding_api_model"]).strip()
    return saved


def _normalize_deepseek_pricing(value: object) -> dict[str, dict[str, float]]:
    """Keep safe price cards for built-in and user-configured text models."""
    saved = value if isinstance(value, dict) else {}
    normalized = default_deepseek_pricing()
    model_names = list(DEFAULT_DEEPSEEK_PRICING)
    model_names.extend(
        str(model)
        for model in saved
        if str(model) not in DEFAULT_DEEPSEEK_PRICING
        and _MODEL_NAME_PATTERN.fullmatch(str(model))
    )
    for model in model_names[:24]:
        defaults = DEFAULT_DEEPSEEK_PRICING.get(
            model,
            {"input_cache_hit": 0.0, "input_cache_miss": 0.0, "output": 0.0},
        )
        normalized.setdefault(model, dict(defaults))
        candidate = saved.get(model)
        if not isinstance(candidate, dict):
            continue
        for key, default in defaults.items():
            try:
                price = float(candidate.get(key, default))
            except (TypeError, ValueError):
                price = default
            if not math.isfinite(price):
                price = default
            normalized[model][key] = min(max(price, 0.0), 1_000_000.0)
    return normalized


def _normalize_peak_pricing_multiplier(value: object) -> float:
    try:
        multiplier = float(value)
    except (TypeError, ValueError):
        multiplier = 1.0
    if not math.isfinite(multiplier):
        multiplier = 1.0
    return min(max(multiplier, 0.0), 100.0)


def save_llm_settings(
    *,
    deepseek_api_key: str,
    deepseek_base_url: str,
    campus_embedding_api_key: str,
    campus_embedding_api_base_url: str,
    campus_embedding_api_model: str,
) -> dict[str, object]:
    existing = load_llm_settings()
    values: dict[str, object] = {
        "deepseek_api_key": deepseek_api_key.strip(),
        "deepseek_base_url": deepseek_base_url.strip() or "https://api.deepseek.com",
        "campus_embedding_api_key": campus_embedding_api_key.strip(),
        "campus_embedding_api_base_url": (
            campus_embedding_api_base_url.strip()
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        "campus_embedding_api_model": campus_embedding_api_model.strip() or "qwen3.7-text-embedding",
        "deepseek_pricing": _normalize_deepseek_pricing(existing.get("deepseek_pricing")),
        "deepseek_peak_pricing_multiplier": _normalize_peak_pricing_multiplier(
            existing.get("deepseek_peak_pricing_multiplier")
        ),
    }
    values["campus_embedding_enabled"] = campus_embedding_enabled()
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    apply_saved_llm_settings()
    return llm_settings_status()


def _save_partial_llm_settings(values: dict[str, object]) -> dict[str, object]:
    """Update one credential family without touching the other one.

    The settings screen deliberately never returns stored secrets to the
    browser.  Consequently, using one shared "save" request for two secret
    fields turns the untouched field into an empty string and clears it.
    Merge the requested family with the on-disk values instead.
    """
    saved = load_llm_settings()
    saved.update(values)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    apply_saved_llm_settings()
    return llm_settings_status()


def save_deepseek_settings(
    *,
    deepseek_api_key: str | None,
    deepseek_base_url: str,
    deepseek_pricing: dict[str, dict[str, float]] | None = None,
    deepseek_peak_pricing_multiplier: float | None = None,
) -> dict[str, object]:
    """Save DeepSeek settings without clearing a masked, untouched API key."""
    values = {"deepseek_base_url": deepseek_base_url.strip() or "https://api.deepseek.com"}
    if deepseek_api_key is not None:
        values["deepseek_api_key"] = deepseek_api_key.strip()
    if deepseek_pricing is not None:
        values["deepseek_pricing"] = _normalize_deepseek_pricing(deepseek_pricing)
    if deepseek_peak_pricing_multiplier is not None:
        values["deepseek_peak_pricing_multiplier"] = _normalize_peak_pricing_multiplier(
            deepseek_peak_pricing_multiplier
        )
    status = _save_partial_llm_settings(values)
    # Earlier records already have actual token usage but no price snapshot.
    # Price those once with the newly saved card; future price edits leave all
    # non-null historical estimates untouched.
    backfill_missing_deepseek_costs()
    return status


def test_deepseek_connection(
    *,
    deepseek_api_key: str | None,
    deepseek_base_url: str | None,
) -> dict[str, object]:
    """Run the smallest useful DeepSeek request without persisting form input."""
    api_key = (deepseek_api_key or settings.deepseek_api_key).strip()
    base_url = (deepseek_base_url or settings.deepseek_base_url or "https://api.deepseek.com").strip()
    if not api_key:
        raise ValueError("请先填写或保存 DeepSeek API Key")

    model, thinking_type = resolve_deepseek_model(settings.deepseek_model)
    provider = OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        thinking_type=thinking_type,
        provider_name="deepseek",
        request_timeout_seconds=20,
    )
    message = LLMMessage(role="user", content="这是连接测试。请只回复 OK。")
    started_at = perf_counter()
    try:
        response = provider.chat([message], temperature=0, max_tokens=8)
    except Exception as exc:
        record_ai_call(
            call_type="connection_test",
            provider_response=None,
            input_chars=len(message.content),
            elapsed_seconds=perf_counter() - started_at,
            error=str(exc).replace(api_key, "••••"),
        )
        detail = str(exc).replace(api_key, "••••").strip()
        raise RuntimeError(detail[:320] or "DeepSeek 未返回有效响应") from exc

    elapsed_seconds = perf_counter() - started_at
    record_ai_call(
        call_type="connection_test",
        provider_response=response,
        input_chars=len(message.content),
        output_chars=len(response.content),
        elapsed_seconds=elapsed_seconds,
    )
    return {
        "ok": True,
        "model": response.model,
        "elapsed_ms": round(elapsed_seconds * 1000),
        "total_tokens": response.usage.total_tokens if response.usage else None,
    }


def save_campus_embedding_settings(
    *,
    campus_embedding_api_key: str | None,
    campus_embedding_api_base_url: str,
    campus_embedding_api_model: str,
) -> dict[str, object]:
    """Save embedding settings without clearing a masked, untouched API key."""
    model = campus_embedding_api_model.strip() or "qwen3.7-text-embedding"
    values: dict[str, object] = {
        "campus_embedding_api_base_url": (
            campus_embedding_api_base_url.strip()
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        "campus_embedding_api_model": model,
    }
    if campus_embedding_api_key is not None:
        values["campus_embedding_api_key"] = campus_embedding_api_key.strip()
    return _save_partial_llm_settings(values)


def test_campus_embedding_connection(
    *,
    campus_embedding_api_key: str | None,
    campus_embedding_api_base_url: str | None,
    campus_embedding_api_model: str | None,
) -> dict[str, object]:
    """Run one minimal embedding request without persisting form input."""
    api_key = (campus_embedding_api_key or settings.campus_embedding_api_key).strip()
    base_url = (
        campus_embedding_api_base_url
        or settings.campus_embedding_api_base_url
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).strip()
    model = (campus_embedding_api_model or settings.campus_embedding_api_model).strip()
    if not api_key:
        raise ValueError("请先填写或保存 Embedding API Key")
    if not model:
        raise ValueError("请填写 Embedding 模型名称")

    started_at = perf_counter()
    try:
        response = OpenAI(api_key=api_key, base_url=base_url, timeout=20, max_retries=0).embeddings.create(
            model=model,
            input="KnowledgeHub embedding connection test",
            encoding_format="float",
        )
        vector = response.data[0].embedding if response.data else []
        if not vector:
            raise RuntimeError("Embedding 服务未返回向量")
    except Exception as exc:
        elapsed_seconds = perf_counter() - started_at
        detail = str(exc).replace(api_key, "••••").strip()
        record_ai_call(
            call_type="knowledge_embedding_test",
            provider_response=None,
            input_chars=37,
            elapsed_seconds=elapsed_seconds,
            error=detail,
        )
        raise RuntimeError(detail[:320] or "Embedding 服务未返回有效响应") from exc

    elapsed_seconds = perf_counter() - started_at
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    record_ai_call(
        call_type="knowledge_embedding_test",
        provider_response=None,
        input_chars=37,
        elapsed_seconds=elapsed_seconds,
    )
    return {
        "ok": True,
        "model": str(getattr(response, "model", "") or model),
        "dimensions": len(vector),
        "elapsed_ms": round(elapsed_seconds * 1000),
        "total_tokens": int(total_tokens or prompt_tokens) if (total_tokens or prompt_tokens) is not None else None,
    }


def campus_embedding_enabled() -> bool:
    """Whether the user permits embedding API calls right now.

    The key stays stored while paused so pausing a batch never means deleting
    credentials or re-entering them later.
    """
    if not CAMPUS_EMBEDDINGS_ENABLED:
        return False
    return load_llm_settings().get("campus_embedding_enabled", True) is not False


def set_campus_embedding_enabled(enabled: bool) -> dict[str, object]:
    return _save_partial_llm_settings({"campus_embedding_enabled": bool(enabled)})


def llm_settings_status() -> dict[str, object]:
    return {
        "deepseek_configured": bool(settings.deepseek_api_key),
        "deepseek_base_url": settings.deepseek_base_url,
        "deepseek_pricing": settings.deepseek_pricing,
        "deepseek_peak_pricing_multiplier": settings.deepseek_peak_pricing_multiplier,
        "campus_embedding_configured": bool(settings.campus_embedding_api_key),
        "campus_embedding_enabled": campus_embedding_enabled(),
        "campus_embedding_api_base_url": settings.campus_embedding_api_base_url,
        "campus_embedding_api_model": settings.campus_embedding_api_model,
        "campus_embedding_api_dimensions": settings.campus_embedding_api_dimensions,
    }


def reveal_deepseek_api_key() -> str:
    """Return the local DeepSeek secret only after an explicit UI reveal action."""
    saved = load_llm_settings()
    return str(saved.get("deepseek_api_key") or settings.deepseek_api_key or "").strip()


def reveal_campus_embedding_api_key() -> str:
    """Return the local embedding secret only after an explicit UI reveal action."""
    saved = load_llm_settings()
    return str(saved.get("campus_embedding_api_key") or settings.campus_embedding_api_key or "").strip()
