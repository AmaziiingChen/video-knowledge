from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from config import settings
from fastapi.testclient import TestClient
from main import app
from services import telemetry


def test_telemetry_is_off_by_default_and_does_not_queue_events():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        assert telemetry.status()["enabled"] is False
        assert telemetry.status()["requires_consent"] is True
        assert telemetry.record("app_started") is False
        assert telemetry.event_payloads_for_upload() == []
        assert telemetry.status()["pending_events"] == 0
        assert not (Path(temporary_directory) / "telemetry.sqlite").exists()


def test_telemetry_requires_the_current_notice_and_sanitizes_unknown_enum_values():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        with pytest.raises(ValueError, match="阅读当前隐私"):
            telemetry.set_enabled(True)
        assert telemetry.set_enabled(True, notice_version=telemetry.PRIVACY_NOTICE_VERSION)["enabled"] is True
        assert telemetry.record("task_finished", {"result": "failed", "stage": "user supplied path"}) is True
        assert telemetry.status()["pending_events"] == 2
        with pytest.raises(ValueError, match="未允许字段"):
            telemetry.record("task_finished", {"error": "a user URL must never be stored"})
        payloads = telemetry.event_payloads_for_upload()
        assert payloads[-1]["properties"] == {"result": "failed", "stage": "other"}
        assert telemetry.set_enabled(False) == {
            "enabled": False,
            "pending_events": 0,
            "event_catalog_size": 20,
            "privacy_notice_version": telemetry.PRIVACY_NOTICE_VERSION,
            "requires_consent": True,
        }
        assert telemetry.event_payloads_for_upload() == []


def test_telemetry_discards_an_old_consent_queue_when_the_notice_changes():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        telemetry.set_enabled(True, notice_version=telemetry.PRIVACY_NOTICE_VERSION)
        telemetry.record("app_started")
        with patch.object(telemetry, "PRIVACY_NOTICE_VERSION", "2026-09-telemetry-v2"):
            status = telemetry.status()
        assert status["enabled"] is False
        assert status["requires_consent"] is True
        assert status["pending_events"] == 0


def test_telemetry_route_rejects_stale_notice_versions(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")
    headers = {"Origin": "knowledgehub://app", "X-KnowledgeHub-Token": "desktop-launch-token"}
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)), TestClient(app) as client:
        rejected = client.put("/api/telemetry", headers=headers, json={"enabled": True, "privacy_notice_version": "old"})

    assert rejected.status_code == 400
    assert "当前隐私" in rejected.json()["detail"]
