import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from config import settings
from fastapi.testclient import TestClient
from main import app
from services import telemetry


@pytest.fixture(autouse=True)
def reset_telemetry_runtime_state():
    with telemetry._lock:
        if telemetry._flush_timer is not None:
            telemetry._flush_timer.cancel()
        telemetry._flush_timer = None
        telemetry._flush_timer_path = None
        telemetry._pending_events.clear()
        telemetry._pending_events_path = None
        telemetry._enabled_cache = None
        telemetry._enabled_cache_path = None
        telemetry._preference_cache = None
        telemetry._upload_generation = 0
    yield
    with telemetry._lock:
        if telemetry._flush_timer is not None:
            telemetry._flush_timer.cancel()
        telemetry._flush_timer = None
        telemetry._flush_timer_path = None
        telemetry._pending_events.clear()
        telemetry._pending_events_path = None
        telemetry._enabled_cache = None
        telemetry._enabled_cache_path = None
        telemetry._preference_cache = None
        telemetry._upload_generation = 0


def _installation_id(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT value FROM telemetry_settings WHERE key = 'installation_id'").fetchone()[0])


def test_telemetry_is_on_by_default_and_queues_only_fixed_events():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        status = telemetry.status()
        assert status["enabled"] is True
        assert status["requires_consent"] is False
        assert status["notice_required"] is True
        assert status["preference_source"] == telemetry.DEFAULT_ENABLED
        assert telemetry.record("app_started") is True
        telemetry.flush()
        assert telemetry.status()["pending_events"] == 1
        assert (Path(temporary_directory) / "telemetry.sqlite").exists()
        assert not (Path(temporary_directory) / "telemetry-preference").exists()


def test_telemetry_persists_an_explicit_opt_out_and_rotates_id_on_reenable():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        database_path = Path(temporary_directory) / "telemetry.sqlite"
        telemetry.status()
        original_installation_id = _installation_id(database_path)
        with pytest.raises(ValueError, match="阅读当前隐私"):
            telemetry.set_enabled(True)
        assert telemetry.record("task_finished", {"result": "failed", "stage": "user supplied path"}) is True
        assert telemetry.status()["pending_events"] == 1
        with pytest.raises(ValueError, match="固定目录"):
            telemetry.record("task_finished", {"error": "a user URL must never be stored"})
        with pytest.raises(ValueError, match="固定目录"):
            telemetry.record("task_finished", {"result": "failed"})
        payloads = telemetry.event_payloads_for_upload()
        assert payloads[-1]["properties"] == {"result": "failed", "stage": "other"}
        batch = telemetry.upload_batch()
        assert batch is not None
        assert batch["installation_id"]
        assert all("installation_id" not in event for event in batch["events"])
        first_event_id = str(batch["events"][0]["event_id"])
        assert telemetry.acknowledge_uploaded_events([first_event_id, "missing-event"]) == 1
        assert telemetry.status()["pending_events"] == 0
        assert telemetry.set_enabled(False) == {
            "enabled": False,
            "pending_events": 0,
            "event_catalog_size": 17,
            "privacy_notice_version": telemetry.PRIVACY_NOTICE_VERSION,
            "requires_consent": False,
            "notice_required": False,
            "preference_source": telemetry.EXPLICIT_DISABLED,
        }
        assert not database_path.exists()
        assert (Path(temporary_directory) / "telemetry-preference").read_text(encoding="utf-8") == "explicit_disabled\n"

        # Simulate a backend restart: the opt-out marker remains authoritative
        # and must not be interpreted as a fresh default-enabled installation.
        telemetry._enabled_cache = None
        telemetry._enabled_cache_path = None
        telemetry._preference_cache = None
        assert telemetry.status()["enabled"] is False
        assert telemetry.record("app_started") is False
        assert telemetry.event_payloads_for_upload() == []

        enabled = telemetry.set_enabled(True, notice_version=telemetry.PRIVACY_NOTICE_VERSION)
        assert enabled["enabled"] is True
        assert enabled["preference_source"] == telemetry.EXPLICIT_ENABLED
        assert _installation_id(database_path) != original_installation_id
        assert not (Path(temporary_directory) / "telemetry-preference").exists()


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("", "unknown"),
        ("parse", "prepare"),
        ("info", "prepare"),
        ("extract_audio", "prepare"),
        ("wait_for_ocr", "ocr"),
        ("transcribe", "transcribe"),
        ("summarize", "summary"),
        ("save", "export"),
        ("cover_generate", "analyze"),
        ("private/path", "other"),
    ],
)
def test_internal_pipeline_stages_map_to_the_fixed_public_catalog(stage, expected):
    assert telemetry.telemetry_stage_bucket(stage) == expected


def test_telemetry_discards_an_old_notice_queue_without_fabricating_default_consent():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        database_path = Path(temporary_directory) / "telemetry.sqlite"
        telemetry.status()
        telemetry.record("app_started")
        telemetry.flush()
        old_installation_id = _installation_id(database_path)
        with sqlite3.connect(database_path) as connection:
            connection.execute("UPDATE telemetry_settings SET value = '2026-08-telemetry-v2' WHERE key = 'privacy_notice_version'")
            connection.execute("DELETE FROM telemetry_settings WHERE key = 'preference'")
        telemetry._enabled_cache = None
        telemetry._enabled_cache_path = None
        telemetry._preference_cache = None

        status = telemetry.status()
        assert status["enabled"] is True
        assert status["preference_source"] == telemetry.EXPLICIT_ENABLED
        assert status["pending_events"] == 0
        assert _installation_id(database_path) != old_installation_id


def test_telemetry_fails_closed_when_existing_storage_is_not_a_database():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        database_path = Path(temporary_directory) / "telemetry.sqlite"
        database_path.write_bytes(b"not-a-sqlite-database")

        status = telemetry.status()

        assert status["enabled"] is False
        assert status["preference_source"] == telemetry.ERROR_DISABLED
        assert telemetry.record("app_started") is False


def test_transient_storage_error_recovers_without_restarting_the_backend(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    original_connect = telemetry._connect
    attempts = 0

    def flaky_connect():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("temporary filesystem denial")
        return original_connect()

    monkeypatch.setattr(telemetry, "_connect", flaky_connect)

    first = telemetry.status()
    second = telemetry.status()

    assert first["enabled"] is False
    assert first["preference_source"] == telemetry.ERROR_DISABLED
    assert second["enabled"] is True
    assert second["preference_source"] == telemetry.DEFAULT_ENABLED
    assert attempts >= 2


def test_pending_events_and_delayed_flush_never_cross_data_directories(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    with patch.object(settings, "data_dir", first_dir):
        assert telemetry.status()["enabled"] is True
        assert telemetry.record("app_started") is True
        first_path = (first_dir / "telemetry.sqlite").resolve()
        assert telemetry._pending_events_path == first_path

    with patch.object(settings, "data_dir", second_dir):
        telemetry.flush()
        status = telemetry.status()
        assert status["enabled"] is True
        assert status["pending_events"] == 0
        with sqlite3.connect(second_dir / "telemetry.sqlite") as connection:
            assert connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0] == 0

    # A cancelled callback that was already entering must not clear or flush a
    # newer path's timer or queue.
    telemetry._flush_for_path(first_path)
    assert telemetry._pending_events == []


def test_permission_errors_never_escape_record_flush_or_status(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert telemetry.bootstrap() == telemetry.DEFAULT_ENABLED
    for _ in range(telemetry.FLUSH_BATCH_SIZE - 1):
        assert telemetry.record("app_started") is True

    monkeypatch.setattr(
        telemetry,
        "_connect",
        lambda: (_ for _ in ()).throw(PermissionError("disk unavailable")),
    )

    assert telemetry.record("app_started") is True
    telemetry.flush()
    status = telemetry.status()
    assert status["enabled"] is False
    assert status["preference_source"] == telemetry.ERROR_DISABLED


def test_opt_out_deletes_every_sqlite_artifact_and_keeps_the_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert telemetry.status()["enabled"] is True
    database_path = tmp_path / "telemetry.sqlite"
    artifacts = [
        database_path,
        Path(f"{database_path}-journal"),
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ]
    for artifact in artifacts[1:]:
        artifact.write_bytes(b"old sqlite pages")

    disabled = telemetry.set_enabled(False)

    assert disabled["enabled"] is False
    assert all(not artifact.exists() for artifact in artifacts)
    assert (tmp_path / "telemetry-preference").read_text(encoding="utf-8") == "explicit_disabled\n"


def test_opt_out_reports_incomplete_cleanup_while_remaining_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert telemetry.status()["enabled"] is True
    original_delete = telemetry._delete_database_files
    monkeypatch.setattr(telemetry, "_delete_database_files", lambda: False)

    with pytest.raises(OSError, match="尚未完全清除"):
        telemetry.set_enabled(False)

    assert (tmp_path / "telemetry-preference").exists()
    assert telemetry.record("app_started") is False
    monkeypatch.setattr(telemetry, "_delete_database_files", original_delete)
    assert telemetry.status()["enabled"] is False
    assert not (tmp_path / "telemetry.sqlite").exists()


def test_payload_collection_cannot_recreate_database_after_concurrent_opt_out(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert telemetry.status()["enabled"] is True
    assert telemetry.record("app_started") is True
    telemetry.flush()
    original_flush = telemetry.flush

    def disable_during_payload_flush():
        monkeypatch.setattr(telemetry, "flush", original_flush)
        telemetry.set_enabled(False)

    monkeypatch.setattr(telemetry, "flush", disable_during_payload_flush)

    assert telemetry.event_payloads_for_upload() == []
    assert (tmp_path / "telemetry-preference").exists()
    assert not (tmp_path / "telemetry.sqlite").exists()


def test_disk_queue_never_exceeds_the_documented_hard_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    assert telemetry.status()["enabled"] is True
    database_path = tmp_path / "telemetry.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO telemetry_events(id, event_name, occurred_at, properties) VALUES (?, 'app_started', ?, '{}')",
            [(f"seed-{index}", f"2026-08-13T00:{index // 60:02d}:{index % 60:02d}+00:00") for index in range(telemetry.MAX_PENDING_EVENTS)],
        )

    for _ in range(telemetry.FLUSH_BATCH_SIZE):
        assert telemetry.record("app_started") is True

    with sqlite3.connect(database_path) as connection:
        count = int(connection.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0])
    assert count == telemetry.MAX_PENDING_EVENTS


def test_telemetry_route_rejects_stale_notice_versions(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")
    headers = {"Origin": "knowledgehub://app", "X-KnowledgeHub-Token": "desktop-launch-token"}
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)), TestClient(app) as client:
        rejected = client.put("/api/telemetry", headers=headers, json={"enabled": True, "privacy_notice_version": "old"})

    assert rejected.status_code == 400
    assert "当前隐私" in rejected.json()["detail"]
