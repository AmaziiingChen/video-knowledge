from __future__ import annotations

from threading import Event, Lock, Thread

from config import settings
from services.rss_sync import sync_due_rss_sources


class RssSubscriptionScheduler:
    """Run due RSS checks in the same low-frequency local loop as other sources."""

    def __init__(self) -> None:
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        if not settings.rss_scheduler_enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="rss-subscription-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        self._sync_due_safely()
        interval = max(30, int(settings.rss_scheduler_interval_seconds))
        while not self._stop_event.wait(interval):
            self._sync_due_safely()

    @staticmethod
    def _sync_due_safely() -> None:
        try:
            sync_due_rss_sources()
        except Exception:
            pass


rss_subscription_scheduler = RssSubscriptionScheduler()
