"""Low-frequency uploader for the consented, fixed-schema telemetry queue."""

from __future__ import annotations

import ipaddress
import sqlite3
from threading import Event, Lock, Thread
from urllib.parse import urlparse

import httpx
from config import settings

from services import telemetry

COLLECTOR_PATH = "/v1/events"
# Exact reviewed Cloudflare Workers hostname. Sibling workers, preview URLs,
# ports, redirects and environment-provided destinations remain inert.
OFFICIAL_COLLECTOR_HOSTS: frozenset[str] = frozenset(
    {"knowledgehub-telemetry-collector.knowledgehub4chen.workers.dev"}
)
INITIAL_DELAY_SECONDS = 60.0
REGULAR_INTERVAL_SECONDS = 12 * 60 * 60.0
MIN_RETRY_SECONDS = 5 * 60.0
MAX_RETRY_SECONDS = REGULAR_INTERVAL_SECONDS
REQUEST_TIMEOUT_SECONDS = 5.0


def validated_collector_url(
    value: object,
    *,
    allowed_hosts: frozenset[str] | None = None,
) -> str:
    raw = str(value or "").strip()
    active_hosts = OFFICIAL_COLLECTOR_HOSTS if allowed_hosts is None else allowed_hosts
    if not raw or not active_hosts:
        return ""
    parsed = urlparse(raw)
    hostname = str(parsed.hostname or "").lower()
    try:
        ipaddress.ip_address(hostname)
        return ""
    except ValueError:
        pass
    try:
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path != COLLECTOR_PATH
        or parsed.params
        or parsed.query
        or parsed.fragment
        or hostname not in active_hosts
    ):
        return ""
    return f"https://{hostname}{COLLECTOR_PATH}"


def upload_once(*, collector_url: object | None = None, client: httpx.Client | None = None) -> str:
    url = validated_collector_url(settings.telemetry_collector_url if collector_url is None else collector_url)
    if not url:
        return "disabled"
    try:
        payload = telemetry.upload_batch(limit=100)
    except (OSError, sqlite3.Error):
        return "failed"
    if not payload:
        return "empty"
    events = payload["events"]
    if not isinstance(events, list):
        return "failed"
    event_ids = [str(event.get("event_id") or "") for event in events if isinstance(event, dict)]
    if len(event_ids) != len(events) or any(not event_id for event_id in event_ids):
        return "failed"
    active_client = client or httpx.Client(
        timeout=REQUEST_TIMEOUT_SECONDS,
        follow_redirects=False,
        trust_env=False,
    )
    owns_client = client is None
    try:
        response = active_client.post(url, json=payload, headers={"content-type": "application/json"})
        response.raise_for_status()
        result = response.json()
        if response.status_code != 202 or not isinstance(result, dict) or int(result.get("accepted") or -1) != len(event_ids):
            return "failed"
        telemetry.acknowledge_uploaded_events(event_ids)
        return "succeeded"
    except (httpx.HTTPError, OSError, sqlite3.Error, TypeError, ValueError):
        return "failed"
    finally:
        if owns_client:
            active_client.close()


def next_upload_delay(result: str, consecutive_failures: int) -> tuple[float, int]:
    if result == "failed":
        failures = max(1, consecutive_failures + 1)
        return min(MAX_RETRY_SECONDS, MIN_RETRY_SECONDS * (2 ** (failures - 1))), failures
    return REGULAR_INTERVAL_SECONDS, 0


class TelemetryUploader:
    def __init__(self) -> None:
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None

    def start(self) -> bool:
        if not validated_collector_url(settings.telemetry_collector_url):
            return False
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="telemetry-uploader", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=REQUEST_TIMEOUT_SECONDS + 1)
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def _run(self) -> None:
        delay = INITIAL_DELAY_SECONDS
        failures = 0
        while not self._stop_event.wait(delay):
            result = upload_once()
            delay, failures = next_upload_delay(result, failures)


telemetry_uploader = TelemetryUploader()
