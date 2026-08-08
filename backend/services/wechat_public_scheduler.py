from __future__ import annotations

from threading import Event, Lock, Thread

from services.wechat_discovery import enqueue_due_album_sources


class WeChatPublicAlbumScheduler:
    """Low-frequency local scheduler for explicitly enabled public albums."""

    def __init__(self, *, poll_interval_seconds: int = 60) -> None:
        self._poll_interval_seconds = max(30, int(poll_interval_seconds))
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run,
                name="wechat-public-album-sync",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        self._sync_due_safely()
        while not self._stop_event.wait(self._poll_interval_seconds):
            self._sync_due_safely()

    @staticmethod
    def _sync_due_safely() -> None:
        try:
            enqueue_due_album_sources()
        except Exception:
            # Per-run failures are persisted by the discovery service. The
            # scheduler must remain available for the next due source.
            pass


wechat_public_album_scheduler = WeChatPublicAlbumScheduler()


__all__ = ["WeChatPublicAlbumScheduler", "wechat_public_album_scheduler"]
