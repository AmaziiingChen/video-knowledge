from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from config import settings
from services.campus_source_settings import load_campus_source_settings, record_campus_source_sync


class CampusSourceScheduler:
    """Local scheduler for the newest window of each campus website source."""

    def __init__(self) -> None:
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        if not settings.campus_source_scheduler_enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="campus-source-sync", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        self._sync_due_safely()
        interval = max(30, int(settings.campus_source_scheduler_interval_seconds))
        while not self._stop_event.wait(interval):
            self._sync_due_safely()

    def _sync_due_safely(self) -> None:
        now = datetime.now(timezone.utc)
        for source in load_campus_source_settings():
            if self._stop_event.is_set() or not bool(source["enabled"]):
                continue
            last_sync = _parse_time(str(source.get("last_sync_at") or ""))
            interval = timedelta(minutes=max(30, int(source.get("interval_minutes") or 360)))
            if last_sync and now < last_sync + interval:
                continue
            slug = str(source["slug"])
            try:
                from services.task_manager import task_manager

                task_manager.create_source_sync(
                    {"kind": "campus", "source_slug": slug, "mode": "latest"},
                    source_title=f"自动检查校园来源：{source.get('name') or slug}",
                    execution_mode="background",
                )
            except Exception as exc:
                try:
                    record_campus_source_sync(slug, status="error", message=str(exc))
                except Exception:
                    pass


def _parse_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


campus_source_scheduler = CampusSourceScheduler()


__all__ = ["CampusSourceScheduler", "campus_source_scheduler"]
