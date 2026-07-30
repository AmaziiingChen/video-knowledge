from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from config import settings
from services import telemetry


def test_telemetry_is_off_by_default_and_does_not_queue_events():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        assert telemetry.status()["enabled"] is False
        assert telemetry.record("app_started") is False
        assert telemetry.event_payloads_for_upload() == []
        assert telemetry.status()["pending_events"] == 0
        assert not (Path(temporary_directory) / "telemetry.sqlite").exists()


def test_telemetry_accepts_only_catalogued_short_enum_fields_and_clears_on_disable():
    with TemporaryDirectory() as temporary_directory, patch.object(settings, "data_dir", Path(temporary_directory)):
        assert telemetry.set_enabled(True)["enabled"] is True
        assert telemetry.record("task_finished", {"result": "failed", "stage": "transcribe"}) is True
        assert telemetry.status()["pending_events"] == 2
        with pytest.raises(ValueError, match="未允许字段"):
            telemetry.record("task_finished", {"error": "a user URL must never be stored"})
        assert telemetry.set_enabled(False) == {"enabled": False, "pending_events": 0, "event_catalog_size": 20}
        assert telemetry.event_payloads_for_upload() == []
