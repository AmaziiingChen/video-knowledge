from __future__ import annotations

import sqlite3
from unittest.mock import Mock

import httpx
from services import telemetry_uploader

ALLOWED_HOSTS = frozenset({"telemetry.example.test"})
COLLECTOR_URL = "https://telemetry.example.test/v1/events"
OFFICIAL_HOST = "knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev"
OFFICIAL_URL = f"https://{OFFICIAL_HOST}/v1/events"


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
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_batch", lambda limit: batch)
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
        "upload_batch",
        lambda limit: {"events": [{"event_id": "keep-me"}]},
    )
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
        "upload_batch",
        Mock(side_effect=sqlite3.OperationalError("database is locked")),
    )

    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "failed"
    assert client.calls == []


def test_empty_or_disabled_upload_never_creates_a_request(monkeypatch):
    client = _Client(_Response(payload={"accepted": 0}))
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_batch", lambda limit: None)

    assert telemetry_uploader.upload_once(collector_url="", client=client) == "disabled"
    assert telemetry_uploader.upload_once(collector_url=COLLECTOR_URL, client=client) == "empty"
    assert client.calls == []


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


def test_default_client_disables_proxies_and_redirects(monkeypatch):
    batch = {"events": [{"event_id": "event-one"}]}
    client = _Client(_Response(payload={"accepted": 1}))
    client_options: list[dict[str, object]] = []
    monkeypatch.setattr(telemetry_uploader, "OFFICIAL_COLLECTOR_HOSTS", ALLOWED_HOSTS)
    monkeypatch.setattr(telemetry_uploader.telemetry, "upload_batch", lambda limit: batch)
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
        "trust_env": False,
    }]
    assert client.closed is True


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
