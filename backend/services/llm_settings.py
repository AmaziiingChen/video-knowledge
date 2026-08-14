from __future__ import annotations

import json
import math
import os
import re
import tempfile
from time import perf_counter
from typing import Any

from config import DEFAULT_DEEPSEEK_PRICING, default_deepseek_pricing, settings
from openai import OpenAI

from services.ai_call_logger import backfill_missing_deepseek_costs, record_ai_call
from services.llm_provider import (
    LLMMessage,
    OpenAICompatibleProvider,
    resolve_deepseek_model,
)
from services.text_model_catalog import (
    BUILTIN_TEXT_PROVIDERS,
    PROVIDER_ID_PATTERN,
    normalize_provider_profile,
    provider_model_options,
    provider_profiles_from_settings,
    resolve_model_selection,
)
from services.text_model_secrets import (
    TextModelSecretError,
    TextModelSecretStore,
    get_text_model_secret_store,
)

SETTINGS_FILE = "llm_settings.json"
# Semantic embeddings are intentionally paused while the feature is under
# development. Keep the saved configuration so users do not need to re-enter
# it when the feature is re-enabled, but never permit a runtime API call.
CAMPUS_EMBEDDINGS_ENABLED = False
_MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$")
_ENV_DEEPSEEK_API_KEY = str(settings.deepseek_api_key or "").strip()


def _path():
    return settings.data_dir / SETTINGS_FILE


def load_llm_settings() -> dict[str, object]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _load_llm_settings_for_update() -> dict[str, object]:
    path = _path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("现有 AI 配置文件无法读取或已损坏，已取消保存") from exc
    if not isinstance(data, dict):
        raise TypeError("现有 AI 配置文件格式无效，已取消保存")
    return data


def _write_llm_settings(values: dict[str, object]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = os.fdopen(descriptor, "w", encoding="utf-8")
    try:
        with temporary:
            json.dump(values, temporary, ensure_ascii=False, indent=2)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def _load_secret(
    secret_ref: str,
    *,
    store: TextModelSecretStore | None = None,
) -> str:
    try:
        return str((store or get_text_model_secret_store()).load(secret_ref) or "").strip()
    except TextModelSecretError:
        return ""


def _try_load_secret(
    secret_ref: str,
    *,
    store: TextModelSecretStore | None = None,
) -> tuple[str, bool]:
    try:
        return str((store or get_text_model_secret_store()).load(secret_ref) or "").strip(), True
    except TextModelSecretError:
        return "", False


def _restore_secret_after_write_failure(
    *,
    store: TextModelSecretStore,
    secret_ref: str,
    old_key: str,
    write_error: OSError,
) -> None:
    try:
        store.save(secret_ref, old_key)
    except TextModelSecretError as rollback_error:
        raise TextModelSecretError(
            "配置写入失败且 API Key 回滚失败；原配置文件未变，请重新检查钥匙串"
        ) from rollback_error
    raise write_error


def _migrate_legacy_deepseek_secret(
    saved: dict[str, object],
    *,
    store: TextModelSecretStore,
) -> dict[str, object]:
    legacy_key = str(saved.get("deepseek_api_key") or "").strip()
    if not legacy_key:
        return saved
    deepseek = provider_profiles_from_settings(saved)[0]
    secret_ref = str(deepseek["secret_ref"])
    try:
        store.save(secret_ref, legacy_key)
        if str(store.load(secret_ref) or "").strip() != legacy_key:
            raise TextModelSecretError("Keychain 写入校验失败")
        migrated = dict(saved)
        migrated.pop("deepseek_api_key", None)
        _write_llm_settings(migrated)
        return migrated
    except (OSError, TextModelSecretError):
        # The plaintext remains available in the private legacy file until a
        # verified Keychain write and atomic rewrite both succeed.
        return saved


def text_provider_profiles(*, include_configured: bool = True) -> list[dict[str, Any]]:
    saved = load_llm_settings()
    profiles = provider_profiles_from_settings(saved)
    result: list[dict[str, Any]] = []
    for profile in profiles:
        public = {key: value for key, value in profile.items() if key != "secret_ref"}
        if include_configured:
            key = _load_secret(str(profile["secret_ref"]))
            if profile["id"] == "deepseek" and not key:
                key = str(saved.get("deepseek_api_key") or settings.deepseek_api_key or "").strip()
            public["configured"] = bool(key)
        result.append(public)
    return result


def _profile_by_id(provider_id: str) -> dict[str, Any]:
    normalized = str(provider_id or "").strip().lower()
    for profile in provider_profiles_from_settings(load_llm_settings()):
        if profile["id"] == normalized:
            if profile.get("enabled") is False:
                raise ValueError("文本模型 Provider 已停用")
            return profile
    raise LookupError("文本模型 Provider 不存在")


def resolve_text_model_runtime(model: str | None = None) -> dict[str, Any]:
    saved = load_llm_settings()
    profiles = provider_profiles_from_settings(saved)
    default_model = str(saved.get("default_text_model") or settings.deepseek_model)
    selection = resolve_model_selection(model, profiles, default_model=default_model)
    if selection.profile.get("enabled") is False:
        raise ValueError("所选文本模型 Provider 已停用，请在设置中重新启用")
    api_key = _load_secret(str(selection.profile["secret_ref"]))
    if selection.provider_id == "deepseek" and not api_key:
        api_key = str(saved.get("deepseek_api_key") or settings.deepseek_api_key or "").strip()
    return {
        "provider_id": selection.provider_id,
        "provider_type": selection.provider_type,
        "api_key": api_key,
        "base_url": str(selection.profile["base_url"]),
        "model": selection.model,
        "thinking_type": selection.thinking_type,
        "auth_scheme": str(selection.profile["auth_scheme"]),
        "thinking_parameter": str(selection.profile["thinking_parameter"]),
        "send_temperature": bool(selection.profile["send_temperature"]),
        "stream_options": bool(selection.profile["stream_options"]),
        "response_format": bool(selection.profile["response_format"]),
    }


def text_model_configured(model: str | None = None) -> bool:
    try:
        return bool(resolve_text_model_runtime(model)["api_key"])
    except (LookupError, ValueError):
        return False


def available_text_model_options() -> list[dict[str, object]]:
    return provider_model_options(provider_profiles_from_settings(load_llm_settings()))


def default_text_model_selection() -> str:
    saved = load_llm_settings()
    return str(saved.get("default_text_model") or settings.deepseek_model)


def save_default_text_model(selection: str) -> dict[str, object]:
    raw = str(selection or "").strip()
    model_selection = raw
    if ":" in model_selection:
        model_part, suffix = model_selection.rsplit(":", 1)
        if suffix in {"enabled", "disabled"}:
            model_selection = model_part
    model_id = model_selection.split("::", 1)[-1]
    if not _MODEL_NAME_PATTERN.fullmatch(model_id):
        raise ValueError("默认文本模型 selection 无效")
    saved = _load_llm_settings_for_update()
    profiles = provider_profiles_from_settings(saved)
    resolved = resolve_model_selection(raw, profiles, default_model=settings.deepseek_model)
    if resolved.profile.get("enabled") is False:
        raise ValueError("不能将已停用的 Provider 设为默认模型")
    # Reject malformed values and unknown provider-like prefixes while keeping
    # legacy slash-containing DeepSeek model IDs backward compatible.
    if not raw or len(raw) > 220:
        raise ValueError("默认文本模型 selection 无效")
    saved["default_text_model"] = raw
    _write_llm_settings(saved)
    return {"default_text_model": raw}


def apply_saved_llm_settings(
    *, secret_store: TextModelSecretStore | None = None
) -> dict[str, object]:
    store = secret_store or get_text_model_secret_store()
    saved = _migrate_legacy_deepseek_secret(load_llm_settings(), store=store)
    # Environment variables remain a valid deployment mechanism. A value saved
    # in the local settings screen deliberately takes precedence for desktop use.
    profiles = provider_profiles_from_settings(saved)
    deepseek = next(profile for profile in profiles if profile["id"] == "deepseek")
    keychain_key, keychain_read_ok = _try_load_secret(str(deepseek["secret_ref"]), store=store)
    if keychain_key:
        settings.deepseek_api_key = keychain_key
    elif "deepseek_api_key" in saved:
        settings.deepseek_api_key = str(saved["deepseek_api_key"] or "").strip()
    elif keychain_read_ok:
        settings.deepseek_api_key = _ENV_DEEPSEEK_API_KEY
    settings.deepseek_base_url = str(deepseek["base_url"])
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
    existing = _load_llm_settings_for_update()
    deepseek = next(
        profile
        for profile in provider_profiles_from_settings(existing)
        if profile["id"] == "deepseek"
    )
    normalized_base_url = normalize_provider_profile(
        {**deepseek, "base_url": deepseek_base_url},
        fallback=dict(BUILTIN_TEXT_PROVIDERS[0]),
    )["base_url"]
    store = get_text_model_secret_store()
    old_key, old_key_read_ok = _try_load_secret(str(deepseek["secret_ref"]), store=store)
    if not old_key_read_ok:
        raise TextModelSecretError("无法读取现有 API Key，已取消保存以避免凭据丢失")
    store.save(str(deepseek["secret_ref"]), deepseek_api_key.strip())
    saved_key, saved_key_read_ok = _try_load_secret(
        str(deepseek["secret_ref"]), store=store
    )
    if not saved_key_read_ok or saved_key != deepseek_api_key.strip():
        store.save(str(deepseek["secret_ref"]), old_key)
        raise TextModelSecretError("API Key 写入校验失败，配置未保存")
    values: dict[str, object] = dict(existing)
    values.update({
        "deepseek_base_url": normalized_base_url,
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
    })
    values.pop("deepseek_api_key", None)
    values["text_providers"] = [
        {**profile, "base_url": normalized_base_url}
        if profile["id"] == "deepseek"
        else profile
        for profile in provider_profiles_from_settings(existing)
    ]
    values["campus_embedding_enabled"] = campus_embedding_enabled()
    try:
        _write_llm_settings(values)
    except OSError as exc:
        _restore_secret_after_write_failure(
            store=store,
            secret_ref=str(deepseek["secret_ref"]),
            old_key=old_key,
            write_error=exc,
        )
    apply_saved_llm_settings()
    return llm_settings_status()


def _save_partial_llm_settings(
    values: dict[str, object],
    *,
    saved: dict[str, object] | None = None,
) -> dict[str, object]:
    """Update one credential family without touching the other one.

    The settings screen deliberately never returns stored secrets to the
    browser.  Consequently, using one shared "save" request for two secret
    fields turns the untouched field into an empty string and clears it.
    Merge the requested family with the on-disk values instead.
    """
    saved = dict(saved) if saved is not None else _load_llm_settings_for_update()
    remove_legacy_deepseek_key = values.get("deepseek_api_key", object()) is None
    saved.update({key: value for key, value in values.items() if value is not None})
    if remove_legacy_deepseek_key:
        saved.pop("deepseek_api_key", None)
    _write_llm_settings(saved)
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
    saved = _load_llm_settings_for_update()
    profiles = provider_profiles_from_settings(saved)
    deepseek = next(profile for profile in profiles if profile["id"] == "deepseek")
    normalized = normalize_provider_profile(
        {**deepseek, "base_url": deepseek_base_url},
        fallback=dict(BUILTIN_TEXT_PROVIDERS[0]),
    )
    values: dict[str, object] = {
        "deepseek_base_url": normalized["base_url"],
        "text_providers": [
            normalized if profile["id"] == "deepseek" else profile
            for profile in profiles
        ],
    }
    store: TextModelSecretStore | None = None
    old_key = ""
    remove_legacy_key = False
    if deepseek_api_key is not None:
        store = get_text_model_secret_store()
        old_key, old_key_read_ok = _try_load_secret(str(normalized["secret_ref"]), store=store)
        if not old_key_read_ok:
            raise TextModelSecretError("无法读取现有 API Key，已取消保存以避免凭据丢失")
        store.save(str(normalized["secret_ref"]), deepseek_api_key.strip())
        saved_key, saved_key_read_ok = _try_load_secret(
            str(normalized["secret_ref"]), store=store
        )
        if not saved_key_read_ok or saved_key != deepseek_api_key.strip():
            store.save(str(normalized["secret_ref"]), old_key)
            raise TextModelSecretError("API Key 写入校验失败，配置未保存")
        remove_legacy_key = True
    else:
        keychain_key, keychain_read_ok = _try_load_secret(str(normalized["secret_ref"]))
        remove_legacy_key = keychain_read_ok and bool(keychain_key)
    if remove_legacy_key:
        values["deepseek_api_key"] = None
    if deepseek_pricing is not None:
        values["deepseek_pricing"] = _normalize_deepseek_pricing(deepseek_pricing)
    if deepseek_peak_pricing_multiplier is not None:
        values["deepseek_peak_pricing_multiplier"] = _normalize_peak_pricing_multiplier(
            deepseek_peak_pricing_multiplier
        )
    try:
        status = _save_partial_llm_settings(values, saved=saved)
    except OSError as exc:
        if store is not None:
            _restore_secret_after_write_failure(
                store=store,
                secret_ref=str(normalized["secret_ref"]),
                old_key=old_key,
                write_error=exc,
            )
        raise
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
    api_key = (deepseek_api_key or reveal_deepseek_api_key()).strip()
    base_url = normalize_provider_profile(
        {
            **next(
                profile
                for profile in provider_profiles_from_settings(load_llm_settings())
                if profile["id"] == "deepseek"
            ),
            "base_url": deepseek_base_url or settings.deepseek_base_url,
        },
        fallback=dict(BUILTIN_TEXT_PROVIDERS[0]),
    )["base_url"]
    if not api_key:
        raise ValueError("请先填写或保存 DeepSeek API Key")

    model, thinking_type = resolve_deepseek_model(settings.deepseek_model)
    provider = OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        thinking_type=thinking_type,
        thinking_parameter="thinking",
        send_temperature=False,
        supports_stream_options=True,
        supports_response_format=True,
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


def save_text_provider(
    *,
    provider_id: str,
    provider_type: str,
    label: str,
    base_url: str,
    models: list[str],
    thinking_parameter: str = "none",
    auth_scheme: str = "bearer",
    send_temperature: bool | None = None,
    stream_options: bool | None = None,
    response_format: bool | None = None,
    api_key: str | None = None,
) -> dict[str, object]:
    provider_id = str(provider_id or "").strip().lower()
    if not PROVIDER_ID_PATTERN.fullmatch(provider_id):
        raise ValueError("Provider ID 只能包含小写字母、数字、下划线和连字符")
    saved = _load_llm_settings_for_update()
    profiles = provider_profiles_from_settings(saved)
    builtins = {str(item["id"]): dict(item) for item in BUILTIN_TEXT_PROVIDERS}
    existing = next((item for item in profiles if item["id"] == provider_id), None)
    if existing is not None and existing.get("enabled") is False and api_key is None:
        raise ValueError("重新启用 Provider 时必须重新输入 API Key")
    fallback = builtins.get(provider_id)
    if fallback and provider_type != fallback["type"]:
        raise ValueError("内置 Provider 类型不可更改")
    profile_input: dict[str, object] = {
        "id": provider_id,
        "type": provider_type,
        "label": label,
        "base_url": base_url,
        "models": models,
        "thinking_parameter": thinking_parameter,
        "auth_scheme": auth_scheme,
        "model_discovery": (
            existing.get("model_discovery") if existing else provider_type == "custom"
        ),
        "enabled": True,
    }
    for field, value in (
        ("send_temperature", send_temperature),
        ("stream_options", stream_options),
        ("response_format", response_format),
    ):
        if value is not None:
            profile_input[field] = value
    profile = normalize_provider_profile(
        profile_input,
        fallback=fallback or existing,
    )
    if existing is None and profile["type"] != "custom" and not fallback:
        raise ValueError("非内置 Provider 必须使用 custom 类型")

    store = get_text_model_secret_store()
    old_key = ""
    if api_key is not None:
        old_key, old_key_read_ok = _try_load_secret(str(profile["secret_ref"]), store=store)
        if not old_key_read_ok:
            raise TextModelSecretError("无法读取现有 API Key，已取消保存以避免凭据丢失")
        store.save(str(profile["secret_ref"]), api_key.strip())
        saved_key, saved_key_read_ok = _try_load_secret(
            str(profile["secret_ref"]), store=store
        )
        if not saved_key_read_ok or saved_key != api_key.strip():
            store.save(str(profile["secret_ref"]), old_key)
            raise TextModelSecretError("API Key 写入校验失败，配置未保存")
    updated = [profile if item["id"] == provider_id else item for item in profiles]
    if existing is None:
        updated.append(profile)
    next_saved = dict(saved)
    next_saved["text_providers"] = updated
    if provider_id == "deepseek":
        next_saved["deepseek_base_url"] = profile["base_url"]
        if api_key is not None:
            next_saved.pop("deepseek_api_key", None)
        else:
            keychain_key, keychain_read_ok = _try_load_secret(
                str(profile["secret_ref"]), store=store
            )
            if keychain_read_ok and keychain_key:
                next_saved.pop("deepseek_api_key", None)
    try:
        _write_llm_settings(next_saved)
    except OSError as exc:
        if api_key is not None:
            _restore_secret_after_write_failure(
                store=store,
                secret_ref=str(profile["secret_ref"]),
                old_key=old_key,
                write_error=exc,
            )
        raise
    apply_saved_llm_settings()
    return next(
        item for item in text_provider_profiles() if item["id"] == provider_id
    )


def delete_text_provider(provider_id: str) -> None:
    normalized = str(provider_id or "").strip().lower()
    if normalized in {str(item["id"]) for item in BUILTIN_TEXT_PROVIDERS}:
        raise ValueError("内置 Provider 不能删除")
    saved = _load_llm_settings_for_update()
    profiles = provider_profiles_from_settings(saved)
    profile = next((item for item in profiles if item["id"] == normalized), None)
    if profile is None:
        raise LookupError("文本模型 Provider 不存在")
    from services.database import connect, ensure_database_initialized

    ensure_database_initialized()
    with connect() as connection:
        active_rows = connection.execute(
            "SELECT request_json FROM tasks WHERE status IN ('queued', 'running', 'paused')"
        ).fetchall()
    selection_prefix = f"{normalized}::"
    if str(saved.get("default_text_model") or "").startswith(selection_prefix):
        raise ValueError("当前 Provider 是默认文本模型，请先切换默认模型")
    for row in active_rows:
        try:
            request = json.loads(str(row["request_json"] or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("未完成任务配置损坏，无法安全确认 Provider 是否仍被引用") from exc
        if not isinstance(request, dict):
            # A malformed persisted payload is a deletion precondition failure,
            # exposed as the same 400 contract as an explicit active reference.
            raise ValueError(  # noqa: TRY004
                "未完成任务配置格式无效，无法安全确认 Provider 是否仍被引用"
            )
        if str(request.get("ai_model") or "").startswith(selection_prefix):
            raise ValueError("当前 Provider 仍被未完成任务引用，任务完成或取消后才能删除")
    referenced_selections: list[object] = []
    for filename, nested_key in (
        ("clipboard_watcher_settings.json", None),
        ("telegram_settings.json", "watch_options"),
    ):
        path = settings.data_dir / filename
        if not path.exists():
            continue
        try:
            persisted = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"持久化监听器配置 {filename} 无法读取或已损坏，已拒绝删除 Provider"
            ) from exc
        if not isinstance(persisted, dict):
            # Fail closed because non-object watcher state cannot prove that
            # the provider is unreferenced.
            raise ValueError(  # noqa: TRY004
                f"持久化监听器配置 {filename} 格式无效，已拒绝删除 Provider"
            )
        if nested_key:
            persisted = persisted.get(nested_key)
            if persisted is None:
                continue
            if not isinstance(persisted, dict):
                # Nested watcher state follows the same 400 deletion contract.
                raise ValueError(
                    f"持久化监听器配置 {filename} 格式无效，已拒绝删除 Provider"
                )
        referenced_selections.append(persisted.get("ai_model"))
    if any(str(value or "").startswith(selection_prefix) for value in referenced_selections):
        raise ValueError("当前 Provider 仍被持久化监听器引用，请先修改监听器模型")
    next_saved = dict(saved)
    disabled = {**profile, "enabled": False}
    next_saved["text_providers"] = [
        disabled if item["id"] == normalized else item for item in profiles
    ]
    _write_llm_settings(next_saved)
    try:
        get_text_model_secret_store().delete(str(profile["secret_ref"]))
    except TextModelSecretError as exc:
        # An orphaned Keychain item is safer than restoring a deleted profile
        # after the non-secret configuration has already been committed.
        raise TextModelSecretError(
            "Provider 已停用，但钥匙串凭据删除失败；请重试或手动处理"
        ) from exc


def reveal_text_provider_api_key(provider_id: str) -> str:
    profile = _profile_by_id(provider_id)
    api_key = _load_secret(str(profile["secret_ref"]))
    if profile["id"] == "deepseek" and not api_key:
        saved = load_llm_settings()
        api_key = str(saved.get("deepseek_api_key") or settings.deepseek_api_key or "").strip()
    return api_key


def test_text_provider_connection(
    provider_id: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, object]:
    profile = _profile_by_id(provider_id)
    key = str(api_key or reveal_text_provider_api_key(provider_id) or "").strip()
    if not key:
        raise ValueError("请先填写或保存 API Key")
    selected_model = str(model or next(iter(profile.get("models", [])), "")).strip()
    if not _MODEL_NAME_PATTERN.fullmatch(selected_model):
        raise ValueError("请填写有效的模型名称")
    provider = OpenAICompatibleProvider(
        api_key=key,
        base_url=str(profile["base_url"]),
        model=selected_model,
        thinking_type="enabled",
        thinking_parameter=str(profile["thinking_parameter"]),
        auth_scheme=str(profile["auth_scheme"]),
        send_temperature=bool(profile["send_temperature"]),
        supports_stream_options=bool(profile["stream_options"]),
        supports_response_format=bool(profile["response_format"]),
        provider_name=str(profile["id"]),
        request_timeout_seconds=20,
    )
    message = LLMMessage(role="user", content="这是连接测试。请只回复 OK。")
    started_at = perf_counter()
    try:
        response = provider.chat([message], temperature=0, max_tokens=8)
    except Exception as exc:
        safe_detail = str(exc).replace(key, "••••").strip()
        record_ai_call(
            call_type="connection_test",
            provider_response=None,
            input_chars=len(message.content),
            elapsed_seconds=perf_counter() - started_at,
            error=safe_detail,
        )
        raise RuntimeError(safe_detail[:320] or "模型服务未返回有效响应") from exc
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
        "provider": profile["id"],
        "model": response.model,
        "elapsed_ms": round(elapsed_seconds * 1000),
        "total_tokens": response.usage.total_tokens if response.usage else None,
    }


def discover_text_provider_models(
    provider_id: str,
    *,
    api_key: str | None = None,
) -> dict[str, object]:
    profile = _profile_by_id(provider_id)
    catalog = list(profile.get("models", []))
    if not profile.get("model_discovery"):
        return {"models": catalog, "source": "catalog", "discovery_supported": False}
    key = str(api_key or reveal_text_provider_api_key(provider_id) or "").strip()
    if not key:
        raise ValueError("请先填写或保存 API Key")
    provider = OpenAICompatibleProvider(
        api_key=key,
        base_url=str(profile["base_url"]),
        model=str(catalog[0] if catalog else "model-discovery"),
        thinking_type="enabled",
        thinking_parameter="none",
        auth_scheme=str(profile["auth_scheme"]),
        send_temperature=False,
        supports_stream_options=False,
        supports_response_format=False,
        provider_name=str(profile["id"]),
        request_timeout_seconds=20,
    )
    try:
        discovered = [
            item for item in provider.list_models() if _MODEL_NAME_PATTERN.fullmatch(item)
        ][:100]
    except Exception as exc:  # noqa: BLE001 - SDK/transport errors fall back to the saved catalog.
        detail = str(exc).replace(key, "••••").strip()
        return {
            "models": catalog,
            "source": "catalog",
            "discovery_supported": True,
            "warning": detail[:240] or "模型发现失败，已返回内置目录",
        }
    return {
        "models": discovered or catalog,
        "source": "remote" if discovered else "catalog",
        "discovery_supported": True,
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
    providers = text_provider_profiles()
    deepseek = next(item for item in providers if item["id"] == "deepseek")
    return {
        "deepseek_configured": bool(deepseek["configured"]),
        "deepseek_base_url": deepseek["base_url"],
        "deepseek_pricing": settings.deepseek_pricing,
        "deepseek_peak_pricing_multiplier": settings.deepseek_peak_pricing_multiplier,
        "campus_embedding_configured": bool(settings.campus_embedding_api_key),
        "campus_embedding_enabled": campus_embedding_enabled(),
        "campus_embedding_api_base_url": settings.campus_embedding_api_base_url,
        "campus_embedding_api_model": settings.campus_embedding_api_model,
        "campus_embedding_api_dimensions": settings.campus_embedding_api_dimensions,
        "text_providers": providers,
        "default_text_model": default_text_model_selection(),
        "text_model_configured": text_model_configured(),
    }


def reveal_deepseek_api_key() -> str:
    """Return the local DeepSeek secret only after an explicit UI reveal action."""
    return reveal_text_provider_api_key("deepseek")


def reveal_campus_embedding_api_key() -> str:
    """Return the local embedding secret only after an explicit UI reveal action."""
    saved = load_llm_settings()
    return str(saved.get("campus_embedding_api_key") or settings.campus_embedding_api_key or "").strip()
