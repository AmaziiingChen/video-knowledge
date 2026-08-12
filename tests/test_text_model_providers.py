from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from config import settings
from fastapi.testclient import TestClient
from main import app
from services import llm_settings as llm_settings_service
from services.database import connect, initialize_database, utc_now_iso
from services.llm_provider import OpenAICompatibleProvider, default_llm_provider
from services.llm_settings import (
    apply_saved_llm_settings,
    default_text_model_selection,
    delete_text_provider,
    discover_text_provider_models,
    load_llm_settings,
    resolve_text_model_runtime,
    save_deepseek_settings,
    save_default_text_model,
    save_llm_settings,
    save_text_provider,
    text_provider_profiles,
)
from services.llm_settings import (
    test_text_provider_connection as run_text_provider_connection_test,
)
from services.text_model_catalog import (
    normalize_provider_base_url,
    provider_profiles_from_settings,
    resolve_model_selection,
)
from services.text_model_secrets import (
    InMemoryTextModelSecretStore,
    MacOSKeychainTextModelSecretStore,
    TextModelSecretError,
    set_text_model_secret_store,
)


def _save_custom_provider(**overrides):
    values = {
        "provider_id": "local-gateway",
        "provider_type": "custom",
        "label": "Local Gateway",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": ["vendor/model-v1"],
        "thinking_parameter": "none",
        "api_key": "local-test-key",
    }
    values.update(overrides)
    return save_text_provider(**values)


def test_selection_uses_explicit_provider_delimiter_and_preserves_slash_models():
    profiles = provider_profiles_from_settings({})
    legacy = resolve_model_selection("my-provider/text-v1:enabled", profiles)
    assert legacy.provider_id == "deepseek"
    assert legacy.model == "my-provider/text-v1"

    configured_prefix_with_slash = resolve_model_selection(
        "qwen/qwen3.7-plus:enabled", profiles
    )
    assert configured_prefix_with_slash.provider_id == "deepseek"
    assert configured_prefix_with_slash.model == "qwen/qwen3.7-plus"

    qwen = resolve_model_selection("qwen::qwen3.7-plus:enabled", profiles)
    assert qwen.provider_id == "qwen"
    assert qwen.model == "qwen3.7-plus"

    with pytest.raises(ValueError, match="未知 Provider"):
        resolve_model_selection("not-configured::model:enabled", profiles)


def test_provider_id_is_normalized_before_update_and_cannot_duplicate():
    _save_custom_provider(provider_id="  Local-Gateway  ")
    _save_custom_provider(provider_id="local-gateway", label="Renamed")
    matches = [item for item in text_provider_profiles() if item["id"] == "local-gateway"]
    assert len(matches) == 1
    assert matches[0]["label"] == "Renamed"


@pytest.mark.parametrize(
    "url,provider_type",
    [
        ("https://user:secret@example.com/v1", "custom"),
        ("https://example.com/v1?key=value", "custom"),
        ("https://example.com/v1#fragment", "custom"),
        ("http://example.com/v1", "custom"),
        ("http://127.0.0.1:8000/v1", "qwen"),
    ],
)
def test_provider_base_url_rejects_credentials_query_fragment_and_remote_http(url, provider_type):
    with pytest.raises(ValueError):
        normalize_provider_base_url(url, provider_type)


def test_custom_loopback_http_is_allowed():
    assert normalize_provider_base_url("http://localhost:11434/v1/", "custom") == "http://localhost:11434/v1"


def test_legacy_plaintext_key_is_removed_only_after_verified_keychain_migration(tmp_path):
    settings.data_dir = tmp_path
    path = tmp_path / "llm_settings.json"
    path.write_text(
        json.dumps({"deepseek_api_key": "legacy-secret", "deepseek_base_url": "https://api.deepseek.com"}),
        encoding="utf-8",
    )
    store = InMemoryTextModelSecretStore()
    apply_saved_llm_settings(secret_store=store)
    assert "deepseek_api_key" not in load_llm_settings()
    assert store.load("text-provider:deepseek") == "legacy-secret"
    assert "legacy-secret" not in path.read_text(encoding="utf-8")


def test_failed_keychain_migration_keeps_legacy_secret_file_and_runtime(tmp_path):
    class FailingStore(InMemoryTextModelSecretStore):
        def save(self, secret_ref: str, api_key: str) -> None:
            raise TextModelSecretError("denied")

    settings.data_dir = tmp_path
    path = tmp_path / "llm_settings.json"
    path.write_text(json.dumps({"deepseek_api_key": "legacy-secret"}), encoding="utf-8")
    apply_saved_llm_settings(secret_store=FailingStore())
    assert load_llm_settings()["deepseek_api_key"] == "legacy-secret"
    assert settings.deepseek_api_key == "legacy-secret"


def test_nonsecret_deepseek_update_preserves_legacy_key_after_failed_migration():
    class MigrationFailStore(InMemoryTextModelSecretStore):
        def save(self, secret_ref: str, api_key: str) -> None:
            raise TextModelSecretError("denied")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "llm_settings.json").write_text(
        json.dumps({"deepseek_api_key": "legacy-secret"}), encoding="utf-8"
    )
    set_text_model_secret_store(MigrationFailStore())
    save_deepseek_settings(
        deepseek_api_key=None,
        deepseek_base_url="https://proxy.example/v1",
    )
    assert load_llm_settings()["deepseek_api_key"] == "legacy-secret"


def test_provider_profile_update_preserves_legacy_key_after_failed_migration():
    class MigrationFailStore(InMemoryTextModelSecretStore):
        def save(self, secret_ref: str, api_key: str) -> None:
            raise TextModelSecretError("denied")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "llm_settings.json").write_text(
        json.dumps({"deepseek_api_key": "legacy-secret"}), encoding="utf-8"
    )
    set_text_model_secret_store(MigrationFailStore())
    save_text_provider(
        provider_id="deepseek",
        provider_type="deepseek",
        label="DeepSeek",
        base_url="https://proxy.example/v1",
        models=["deepseek-v4-flash"],
        thinking_parameter="thinking",
        api_key=None,
    )
    assert load_llm_settings()["deepseek_api_key"] == "legacy-secret"


def test_mutation_refuses_to_overwrite_malformed_existing_settings():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "llm_settings.json"
    original = "{malformed-json"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="已损坏"):
        _save_custom_provider()
    assert path.read_text(encoding="utf-8") == original


def test_mutation_refuses_to_overwrite_unreadable_existing_settings(monkeypatch):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "llm_settings.json"
    path.write_text("{}", encoding="utf-8")
    real_read_text = type(path).read_text

    def fail_target_read(self, *args, **kwargs):
        if self == path:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", fail_target_read)
    with pytest.raises(ValueError, match="无法读取"):
        save_default_text_model("deepseek-v4-flash:enabled")


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [(0, "saved-secret"), (44, "")],
)
def test_macos_keychain_load_distinguishes_found_and_absent(
    monkeypatch, returncode, expected
):
    monkeypatch.setattr(
        "services.text_model_secrets.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=returncode,
            stdout="saved-secret\n" if returncode == 0 else "",
        ),
    )
    monkeypatch.setattr(
        MacOSKeychainTextModelSecretStore,
        "_security_command",
        lambda _self: "/usr/bin/security",
    )
    assert MacOSKeychainTextModelSecretStore().load("text-provider:test") == expected


def test_macos_keychain_load_raises_on_permission_failure(monkeypatch):
    monkeypatch.setattr(
        "services.text_model_secrets.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=36, stdout=""),
    )
    monkeypatch.setattr(
        MacOSKeychainTextModelSecretStore,
        "_security_command",
        lambda _self: "/usr/bin/security",
    )
    with pytest.raises(TextModelSecretError, match="无法读取"):
        MacOSKeychainTextModelSecretStore().load("text-provider:test")


def test_runtime_resolves_each_provider_key_url_model_and_thinking_parameter(monkeypatch):
    store = InMemoryTextModelSecretStore()
    set_text_model_secret_store(store)
    for provider_id, provider_type, base_url, model, thinking_parameter in [
        ("qwen", "qwen", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen3.7-plus", "enable_thinking"),
        ("mimo", "mimo", "https://api.xiaomimimo.com/v1", "mimo-v2.5", "thinking"),
    ]:
        save_text_provider(
            provider_id=provider_id,
            provider_type=provider_type,
            label=provider_id,
            base_url=base_url,
            models=[model],
            thinking_parameter=thinking_parameter,
            api_key=f"{provider_id}-secret",
        )
        runtime = resolve_text_model_runtime(f"{provider_id}::{model}:enabled")
        assert runtime == {
            "provider_id": provider_id,
            "provider_type": provider_type,
            "api_key": f"{provider_id}-secret",
            "base_url": base_url,
            "model": model,
            "thinking_type": "enabled",
            "thinking_parameter": thinking_parameter,
            "send_temperature": False,
            "stream_options": provider_id == "qwen",
            "response_format": True,
        }


def test_custom_provider_sends_no_guessed_thinking_parameter():
    _save_custom_provider()
    provider = default_llm_provider("local-gateway::vendor/model-v1:enabled")
    assert provider.name == "local-gateway"
    assert provider.model == "vendor/model-v1"
    assert provider.thinking_parameter == "none"


def test_model_discovery_uses_saved_profile_and_falls_back_without_leaking_secret(monkeypatch):
    _save_custom_provider(api_key="sensitive-key")

    def fail(_self):
        raise RuntimeError("upstream sensitive-key unavailable")

    monkeypatch.setattr(OpenAICompatibleProvider, "list_models", fail)
    result = discover_text_provider_models("local-gateway")
    assert result["models"] == ["vendor/model-v1"]
    assert result["source"] == "catalog"
    assert "sensitive-key" not in result["warning"]


def test_deleting_provider_used_by_active_task_is_rejected_and_disabled_provider_fails_closed():
    _save_custom_provider()
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO tasks (id, task_type, request_json, status, priority, progress, created_at, updated_at)
               VALUES ('provider-task', 'process_video', ?, 'queued', 100, 0, ?, ?)""",
            (json.dumps({"ai_model": "local-gateway::vendor/model-v1:enabled"}), now, now),
        )
        connection.commit()
    with pytest.raises(ValueError, match="未完成任务"):
        delete_text_provider("local-gateway")
    with connect() as connection:
        connection.execute("UPDATE tasks SET status='succeeded' WHERE id='provider-task'")
        connection.commit()
    delete_text_provider("local-gateway")
    profile = next(item for item in text_provider_profiles() if item["id"] == "local-gateway")
    assert profile["enabled"] is False
    with pytest.raises(ValueError, match="已停用"):
        resolve_text_model_runtime("local-gateway::vendor/model-v1:enabled")
    with pytest.raises(ValueError, match="已停用"):
        run_text_provider_connection_test("local-gateway")
    with pytest.raises(ValueError, match="已停用"):
        discover_text_provider_models("local-gateway")


def test_delete_failure_still_disables_provider_and_is_not_reported_as_success():
    class DeleteFailStore(InMemoryTextModelSecretStore):
        def delete(self, secret_ref: str) -> None:
            raise TextModelSecretError("denied")

    store = DeleteFailStore()
    set_text_model_secret_store(store)
    _save_custom_provider()
    with pytest.raises(TextModelSecretError, match="Provider 已停用"):
        delete_text_provider("local-gateway")
    profile = next(
        item for item in text_provider_profiles() if item["id"] == "local-gateway"
    )
    assert profile["enabled"] is False
    assert store.load("text-provider:local-gateway") == "local-test-key"
    with pytest.raises(ValueError, match="必须重新输入"):
        _save_custom_provider(api_key=None)


def test_delete_api_does_not_return_204_when_keychain_cleanup_fails():
    class DeleteFailStore(InMemoryTextModelSecretStore):
        def delete(self, secret_ref: str) -> None:
            raise TextModelSecretError("denied")

    set_text_model_secret_store(DeleteFailStore())
    _save_custom_provider()
    response = TestClient(app).delete(
        "/api/llm-settings/text-providers/local-gateway"
    )
    assert response.status_code == 500
    assert "凭据删除失败" in response.text


@pytest.mark.parametrize(
    "filename,payload",
    [
        (
            "clipboard_watcher_settings.json",
            {"ai_model": "local-gateway::vendor/model-v1:enabled"},
        ),
        (
            "telegram_settings.json",
            {"watch_options": {"ai_model": "local-gateway::vendor/model-v1:enabled"}},
        ),
    ],
)
def test_deleting_provider_rejects_persisted_watcher_references(filename, payload):
    _save_custom_provider()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / filename).write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="持久化监听器"):
        delete_text_provider("local-gateway")


@pytest.mark.parametrize("request_json", ["{bad-json", "[]"])
def test_deleting_provider_rejects_malformed_active_task_payload(request_json):
    _save_custom_provider()
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO tasks (id, task_type, request_json, status, priority, progress, created_at, updated_at)
               VALUES ('malformed-provider-task', 'process_video', ?, 'queued', 100, 0, ?, ?)""",
            (request_json, now, now),
        )
        connection.commit()
    with pytest.raises(ValueError, match="无法安全确认"):
        delete_text_provider("local-gateway")


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        ("clipboard_watcher_settings.json", "{bad-json"),
        ("telegram_settings.json", "[]"),
    ],
)
def test_deleting_provider_rejects_malformed_watcher_files(filename, payload):
    _save_custom_provider()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / filename).write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError, match="已拒绝删除"):
        delete_text_provider("local-gateway")


def test_default_model_is_persisted_and_used_by_no_arg_runtime():
    _save_custom_provider()
    selection = "local-gateway::vendor/model-v1:enabled"
    assert save_default_text_model(selection) == {"default_text_model": selection}
    assert default_text_model_selection() == selection
    assert resolve_text_model_runtime()["provider_id"] == "local-gateway"
    with pytest.raises(ValueError, match="默认文本模型"):
        delete_text_provider("local-gateway")
    with pytest.raises(ValueError, match="未知 Provider"):
        save_default_text_model("unknown::model:enabled")


def test_json_write_failure_rolls_back_provider_secret(monkeypatch):
    store = InMemoryTextModelSecretStore({"text-provider:local-gateway": "old-secret"})
    set_text_model_secret_store(store)
    _save_custom_provider(api_key=None)
    before = load_llm_settings()

    def fail_write(_values):
        raise OSError("disk full")

    monkeypatch.setattr(llm_settings_service, "_write_llm_settings", fail_write)
    with pytest.raises(OSError, match="disk full"):
        _save_custom_provider(api_key="new-secret")
    assert store.load("text-provider:local-gateway") == "old-secret"
    assert load_llm_settings() == before


def test_json_write_failure_rolls_back_legacy_deepseek_secret(monkeypatch):
    store = InMemoryTextModelSecretStore({"text-provider:deepseek": "old-secret"})
    set_text_model_secret_store(store)

    def fail_write(_values):
        raise OSError("disk full")

    monkeypatch.setattr(llm_settings_service, "_write_llm_settings", fail_write)
    with pytest.raises(OSError, match="disk full"):
        save_deepseek_settings(
            deepseek_api_key="new-secret",
            deepseek_base_url="https://api.deepseek.com",
        )
    assert store.load("text-provider:deepseek") == "old-secret"


def test_json_write_failure_rolls_back_combined_settings_secret(monkeypatch):
    store = InMemoryTextModelSecretStore({"text-provider:deepseek": "old-secret"})
    set_text_model_secret_store(store)

    def fail_write(_values):
        raise OSError("disk full")

    monkeypatch.setattr(llm_settings_service, "_write_llm_settings", fail_write)
    with pytest.raises(OSError, match="disk full"):
        save_llm_settings(
            deepseek_api_key="new-secret",
            deepseek_base_url="https://api.deepseek.com",
            campus_embedding_api_key="",
            campus_embedding_api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            campus_embedding_api_model="qwen3.7-text-embedding",
        )
    assert store.load("text-provider:deepseek") == "old-secret"


def test_combined_settings_refuses_unverified_keychain_write():
    class DiscardingStore(InMemoryTextModelSecretStore):
        def save(self, secret_ref: str, api_key: str) -> None:
            return None

    store = DiscardingStore({"text-provider:deepseek": "old-secret"})
    set_text_model_secret_store(store)
    with pytest.raises(TextModelSecretError, match="写入校验失败"):
        save_llm_settings(
            deepseek_api_key="new-secret",
            deepseek_base_url="https://api.deepseek.com",
            campus_embedding_api_key="",
            campus_embedding_api_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            campus_embedding_api_model="qwen3.7-text-embedding",
        )
    assert store.load("text-provider:deepseek") == "old-secret"


def test_keychain_read_failure_cancels_save_and_preserves_runtime_key():
    class ReadFailStore(InMemoryTextModelSecretStore):
        def load(self, secret_ref: str) -> str:
            raise TextModelSecretError("denied")

        def save(self, secret_ref: str, api_key: str) -> None:
            raise AssertionError("save must not run after a failed read")

    settings.deepseek_api_key = "runtime-secret"
    set_text_model_secret_store(ReadFailStore())
    with pytest.raises(TextModelSecretError, match="取消保存"):
        _save_custom_provider(api_key="new-secret")
    apply_saved_llm_settings(secret_store=ReadFailStore())
    assert settings.deepseek_api_key == "runtime-secret"


def test_text_provider_api_is_additive_and_never_returns_secret():
    client = TestClient(app)
    response = client.put(
        "/api/llm-settings/text-providers/my-gateway",
        json={
            "type": "custom",
            "label": "My Gateway",
            "base_url": "http://127.0.0.1:11434/v1",
            "models": ["model-one"],
            "thinking_parameter": "none",
            "api_key": "api-secret-value",
        },
    )
    assert response.status_code == 200
    assert "api-secret-value" not in response.text
    listing = client.get("/api/llm-settings/text-providers")
    assert listing.status_code == 200
    assert "api-secret-value" not in listing.text
    assert client.post(
        "/api/llm-settings/text-providers/my-gateway/models",
        json={"base_url": "https://attacker.example/v1"},
    ).status_code == 422
    default_response = client.put(
        "/api/llm-settings/default-text-model",
        json={"selection": "my-gateway::model-one:enabled"},
    )
    assert default_response.status_code == 200
    config = client.get("/api/config").json()
    assert config["default_ai_model"] == "my-gateway::model-one:enabled"
    assert config["text_model_configured"] is True
    option = next(
        item for item in config["available_ai_models"] if item["provider"] == "my-gateway"
    )
    assert option["value"] == "my-gateway::model-one:enabled"
    assert option["response_format"] is False


def test_builtin_capabilities_cannot_be_downgraded_by_put_and_custom_fields_are_preserved():
    save_text_provider(
        provider_id="qwen",
        provider_type="qwen",
        label="Qwen",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        models=["qwen3.7-plus"],
        thinking_parameter="none",
        send_temperature=True,
        stream_options=False,
        response_format=False,
    )
    qwen = next(item for item in text_provider_profiles() if item["id"] == "qwen")
    assert qwen["thinking_parameter"] == "enable_thinking"
    assert qwen["send_temperature"] is False
    assert qwen["stream_options"] is True
    assert qwen["response_format"] is True

    _save_custom_provider(
        send_temperature=True,
        stream_options=True,
        response_format=True,
    )
    _save_custom_provider(label="Updated", api_key=None)
    custom = next(
        item for item in text_provider_profiles() if item["id"] == "local-gateway"
    )
    assert custom["send_temperature"] is True
    assert custom["stream_options"] is True
    assert custom["response_format"] is True
