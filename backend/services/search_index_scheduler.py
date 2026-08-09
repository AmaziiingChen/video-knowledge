from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, Lock, Thread
import time

from services.search_index import (
    LocalMarkdownDocument,
    index_local_markdown_document,
    local_markdown_documents,
    rebuild_search_index,
)


logger = logging.getLogger(__name__)


class SearchIndexScheduler:
    """Keep full-text search aligned with local Markdown without network work."""

    def __init__(
        self,
        *,
        interval_seconds: float = 2.0,
        debounce_seconds: float = 1.0,
        max_updates_per_sync: int = 8,
        max_idle_interval_seconds: float = 60.0,
    ) -> None:
        self._interval_seconds = max(0.25, interval_seconds)
        self._max_idle_interval_seconds = max(self._interval_seconds, max_idle_interval_seconds)
        self._debounce_seconds = max(0.0, debounce_seconds)
        self._max_updates_per_sync = max(1, int(max_updates_per_sync))
        self._stop_event = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._fingerprints: dict[str, tuple[str, int, int] | None] = {}
        self._pending: dict[str, float] = {}
        self._next_interval_seconds = self._interval_seconds

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="search-index-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def sync_once(self, *, force: bool = False) -> dict[str, int]:
        """Run one local scan; exposed for deterministic tests and startup."""
        if force:
            stats = rebuild_search_index()
            documents = local_markdown_documents()
            self._fingerprints = {document.content_key: _fingerprint(document.markdown_path) for document in documents}
            self._pending.clear()
            return {
                "updated_count": stats["markdown_indexed_count"],
                "pending_count": 0,
                "scanned_count": len(documents),
                **stats,
            }

        documents = local_markdown_documents()
        live_ids = {document.content_key for document in documents}
        self._fingerprints = {key: value for key, value in self._fingerprints.items() if key in live_ids}
        self._pending = {key: due_at for key, due_at in self._pending.items() if key in live_ids}
        now = time.monotonic()
        changed: list[LocalMarkdownDocument] = []
        for document in documents:
            fingerprint = _fingerprint(document.markdown_path)
            previous = self._fingerprints.get(document.content_key, _UNSEEN)
            if previous is _UNSEEN or previous != fingerprint:
                self._fingerprints[document.content_key] = fingerprint
                self._pending[document.content_key] = now + self._debounce_seconds
            if self._pending.get(document.content_key, float("inf")) <= now:
                changed.append(document)

        selected = changed[: self._max_updates_per_sync]
        indexed_count = 0
        for document in selected:
            self._pending.pop(document.content_key, None)
            if index_local_markdown_document(document):
                indexed_count += 1
        return {
            "updated_count": len(selected),
            "markdown_indexed_count": indexed_count,
            "pending_count": len(self._pending),
            "scanned_count": len(documents),
        }

    def _schedule_next_sync(self, stats: dict[str, int]) -> float:
        """Use a short cadence only while a local change still needs indexing."""
        if stats.get("updated_count", 0) > 0 or stats.get("pending_count", 0) > 0:
            self._next_interval_seconds = self._interval_seconds
        else:
            self._next_interval_seconds = min(
                self._max_idle_interval_seconds,
                self._next_interval_seconds * 2,
            )
        return self._next_interval_seconds

    def _run(self) -> None:
        try:
            # The search table is durable and normal content writes already
            # update it. Rebuilding every row in one startup transaction can
            # hold SQLite's writer lock long enough to reject a user task.
            # Discover changes incrementally and commit only a small batch on
            # each pass so foreground queue writes can interleave.
            initial_stats = self.sync_once()
            self._schedule_next_sync(initial_stats)
        except Exception:
            logger.warning("Initial local search index refresh failed", exc_info=True)
        while not self._stop_event.wait(self._next_interval_seconds):
            try:
                self._schedule_next_sync(self.sync_once())
            except Exception:
                logger.warning("Incremental local search index refresh failed", exc_info=True)


_UNSEEN = object()


def _fingerprint(path: Path | None) -> tuple[str, int, int] | None:
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


search_index_scheduler = SearchIndexScheduler()
