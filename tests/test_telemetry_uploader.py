from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from threading import Event, Thread
from unittest.mock import Mock

import httpx
from services import telemetry_uploader

ALLOWED_HOSTS = frozenset({"telemetry.example.test"})
COLLECTOR_URL = "https://telemetry.example.test/v1/events"
OFFICIAL_HOST = "knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev"
OFFICIAL_URL = f"https://{OFFICIAL_HOST}/v1/events"


@contextmanager
def _send_allowed(_generation: int):
    yield True


def _reset_service_runtime(service) -> None:
    with service._lock:
        if service._flush_timer is not None:
            service._flush_timer.cancel()
        service._flush_timer = None
        service._flush_timer_path = None
        service._pending_events.clear()
        service._pending_events_path = None
        service._enabled_cache = None
        service._enabled_cache_path = None
        service._preference_cache = None
        service._upload_generation = 0


class _Response:
    def __init__(self, *, status_code: int = 202, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("collector failed", request=Mock(), response=Mock())

    def json(self) -> object:
        return self._payload


class _Client:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> _Response:
        self.calls.append((url, json))
        assert headers == {"content-type": "application/json"}
        return self.response

    def close(self) -> None:
        self.closed = True


def test_collector_url_requires_the_exact_reviewed_https_destination():
    assert telemetry_uploader.validated_collector_url(COLLECTOR_URL, allowed_hosts=ALLOWED_HOSTS) == COLLECTOR_URL
    for value in (
        "",
        "http://telemetry.example.test/v1/events",
        "https://other.example.test/v1/events",
        "https://telemetry.example.test/other",
        "https://user@telemetry.example.test/v1/events",
        "https://telemetry.example.test/v1/events?next=private",
        "https://telemetry.example.test:bad/v1/events",
        "https://127.0.0.1/v1/events",
    ):
        assert telemetry_uploader.validated_collector_url(value, allowed_hosts=ALLOWED_HOSTS) == ""


def test_default_collector_accepts_only_the_exact_workers_dev_host():
    assert telemetry_uploader.settings.telemetry_collector_url == OFFICIAL_URL
    assert telemetry_uploader.OFFICIAL_COLLECTOR_HOSTS == frozenset({OFFICIAL_HOST})
    assert telemetry_uploader.validated_collector_url(OFFICIAL_URL) == OFFICIAL_URL
    for value in (
        "https://other.knowledgehub4chen.workers.dev/v1/events",
        "https://knowledgehub-telemetry-collector-preview.knowledgehub4chen.workers.dev/v1/events",
        "https://knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev.evil/v1/events",
        f"https://{OFFICIAL_HOST}:444/v1/events",
        f"https://{OFFICIAL_HOST}/v1/events?debug=1",
    ):
        assert telemetry_uploader.validated_collector_url(value) == ""


def test_upload_success_acknowledges_only_the_sent_event_ids(monkeypatch):
    batch = {
        "schema_version": 1,
        "privacy_notice_version": "notice-v1",
        "installation_id": "installation-id",
        "events": [{"event_id": "event-one"}, {"event_id": "event-two"}],
    }
    acknowledged: list[list[str]] = []
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_batch_snapshot", lambda limit: (7, batch))
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_send_permission", _send_allowed)
    monkeypatch.setattr(
        telemetry_uploader.telemetry,
        "acknowledge_uploaded_events",
        lambda event_ids: acknowledged.append(event_ids),
    )
    client = _Client(_Response(payload={"accepted": 2}))

    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "succeeded"
    assert client.calls == [(COLLECTOR_URL, batch)]
    assert acknowledged == [["event-one", "event-two"]]


def test_upload_failure_keeps_the_local_queue(monkeypatch):
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(
        telemetry_uploader.telemetry,
        "upload_batch_snapshot",
        lambda limit: (7, {"events": [{"event_id": "keep-me"}]}),
    )
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_send_permission", _send_allowed)
    acknowledge = Mock()
    monkeypatch.setattr(telemetry_uploader.telemetry, "acknowledge_uploaded_events", acknowledge)

    result = telemetry_uploader.upload_once(
        collector_url=COLLECTOR_URL,
        client=_Client(_Response(status_code=503)),
    )

    assert result == "failed"
    acknowledge.assert_not_called()


def test_local_queue_failure_enters_retry_without_creating_a_request(monkeypatch):
    client = _Client(_Response(payload={"accepted": 1}))
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(
        telemetry_uploader.telemetry,
        "upload_batch_snapshot",
        Mock(side_effect=sqlite3.OperationalError("database is locked")),
    )

    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "failed"
    assert client.calls == []


def test_empty_or_disabled_upload_never_creates_a_request(monkeypatch):
    client = _Client(_Response(payload={"accepted": 0}))
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_batch_snapshot", lambda limit: None)

    assert telemetry_uploader.upload_once(collector_url="", client=client) == "disabled"
    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "empty"
    assert client.calls == []


def test_explicit_opt_out_keeps_the_real_uploader_inert_across_restart(tmp_path, monkeypatch):
    service = telemetry_uploader.telemetry
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(service.settings, "data_dir", tmp_path)
    _reset_service_runtime(service)
    assert service.status()["enabled"] is True
    service.set_enabled(False)
    with service._lock:
        service._enabled_cache = None
        service._enabled_cache_path = None
        service._preference_cache = None

    client = _Client(_Response(payload={"accepted": 1}))
    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "empty"
    assert client.calls == []


def test_opt_out_after_batch_snapshot_prevents_the_network_request(tmp_path, monkeypatch):
    service = telemetry_uploader.telemetry
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(service.settings, "data_dir", tmp_path)
    _reset_service_runtime(service)
    assert service.status()["enabled"] is True
    assert service.record("app_started") is True
    service.flush()
    original_snapshot = service.upload_batch_snapshot

    def snapshot_then_disable(limit: int):
        snapshot = original_snapshot(limit)
        service.set_enabled(False)
        return snapshot

    monkeypatch.setattr(service, "upload_batch_snapshot", snapshot_then_disable)
    client = _Client(_Response(payload={"accepted": 1}))

    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "empty"
    assert client.calls == []
    assert (tmp_path / "telemetry-preference").exists()
    assert not (tmp_path / "telemetry.sqlite").exists()


def test_opt_out_waits_for_an_already_started_request_before_returning(tmp_path, monkeypatch):
    service = telemetry_uploader.telemetry
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(service.settings, "data_dir", tmp_path)
    _reset_service_runtime(service)
    assert service.status()["enabled"] is True
    assert service.record("app_started") is True
    service.flush()
    post_started = Event()
    release_post = Event()
    disable_finished = Event()
    upload_results: list[str] = []

    class BlockingClient(_Client):
        def post(self, url: str, *, json: dict[str, object], headers: dict[str, str]) -> _Response:
            post_started.set()
            assert release_post.wait(2)
            return super().post(url, json=json, headers=headers)

    client = BlockingClient(_Response(payload={"accepted": 1}))
    upload_thread = Thread(
        target=lambda: upload_results.append(
            telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client)
        )
    )
    upload_thread.start()
    assert post_started.wait(2)

    disable_thread = Thread(target=lambda: (service.set_enabled(False), disable_finished.set()))
    disable_thread.start()
    assert disable_finished.wait(0.05) is False
    release_post.set()
    upload_thread.join(2)
    disable_thread.join(2)

    assert upload_results == ["succeeded"]
    assert disable_finished.is_set()
    assert len(client.calls) == 1
    assert (tmp_path / "telemetry-preference").exists()
    assert not (tmp_path / "telemetry.sqlite").exists()


def test_environment_url_cannot_enable_an_unreviewed_destination(monkeypatch):
    monkeypatch.setattr(
        telemetry_uploader.settings,
        "telemetry_collector_url",
        "https://unreviewed.knowledgehub4chen.workers.dev/v1/events",
    )
    client = _Client(_Response(payload={"accepted": 1}))
    uploader = telemetry_uploader.TelemetryUploader()

    assert uploader.start() is False
    assert uploader._thread is None
    assert telemetry_uploader.upload_once(client=client) == "disabled"
    assert client.calls == []


def test_default_client_allows_system_proxy_only_for_the_fixed_destination(monkeypatch):
    batch = {"events": [{"event_id": "event-one"}]}
    client = _Client(_Response(payload={"accepted": 1}))
    client_options: list[dict[str, object]] = []
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_batch_snapshot", lambda limit: (7, batch))
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_send_permission", _send_allowed)
    monkeypatch.setattr(telemetry_uploader.telemetry, "acknowledge_uploaded_events", lambda event_ids: 1)
    monkeypatch.setattr(
        telemetry_uploader.httpx,
        "Client",
        lambda **options: client_options.append(options) or client,
    )

    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL) == "succeeded"
    assert client_options == [{
        "timeout": telemetry_uploader.REQUEST_TIMEOUT_SECONDS,
        "follow_redirects": False,
        "trust_env": True,
    }]
    assert client.closed is True


def test_uploader_exposes_bounded_retry_status(monkeypatch):
    results = iter(["failed", "succeeded"])
    monkeypatch.setattr(telemetry_uploader, "upload_once", lambda: next(results))
    uploader = telemetry_uploader.TelemetryUploader()

    failed = uploader.upload_now()
    succeeded = uploader.upload_now()

    assert failed["last_upload_result"] == "failed"
    assert failed["consecutive_upload_failures"] == 1
    assert failed["last_upload_attempt_at"]
    assert failed["last_upload_success_at"] == ""
    assert succeeded["last_upload_result"] == "succeeded"
    assert succeeded["consecutive_upload_failures"] == 0
    assert succeeded["last_upload_success_at"] == succeeded["last_upload_attempt_at"]


def test_failed_uploads_back_off_without_exceeding_the_regular_interval():
    delay, failures = telemetry_uploader.next_upload_delay("failed", 0)
    assert (delay, failures) == (telemetry_uploader.MIN_RETRY_SECONDS, 1)
    for _ in range(20):
        delay, failures = telemetry_uploader.next_upload_delay("failed", failures)
    assert delay == telemetry_uploader.MAX_RETRY_SECONDS
    assert telemetry_uploader.next_upload_delay("succeeded", failures) == (
        telemetry_uploader.REGULAR_INTERVAL_SECONDS,
        0,
    )
