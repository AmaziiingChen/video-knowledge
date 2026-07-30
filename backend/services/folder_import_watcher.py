"""Low-frequency, opt-in local folder listener for external materials."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread

from services.folder_import_settings import load_folder_import_watcher_settings
from services.local_file_imports import import_kind_for_filename


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FolderImportEvent:
    path: str
    content_item_id: str | None
    task_id: str | None
    created_at: str
    duplicate: bool = False
    error: str = ""


class FolderImportWatcher:
    """Poll one explicit directory without watching recursively or retaining source paths."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._folder_path = ""
        self._poll_interval = 15.0
        self._seen: dict[str, tuple[int, int]] = {}
        self._events: list[FolderImportEvent] = []
        self._last_error = ""
        self._last_checked_at: str | None = None
        self._started_at: str | None = None

    def start(self, *, folder_path: str, poll_interval: float = 15.0, skip_existing: bool = True) -> dict:
        folder = Path(folder_path).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("本地收件箱文件夹不可访问")
        with self._lock:
            self._folder_path = str(folder)
            self._poll_interval = max(10.0, min(float(poll_interval), 600.0))
            self._last_error = ""
            if self._thread and self._thread.is_alive():
                return self.status()
            self._seen = self._snapshot(folder) if skip_existing else {}
            self._stop_event.clear()
            self._started_at = _now_iso()
            self._thread = Thread(target=self._run, name="folder-import-watcher", daemon=True)
            self._thread.start()
            return self.status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        with self._lock:
            self._thread = None
            return self.status()

    def status(self) -> dict:
        running = bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())
        return {
            "running": running,
            "folder_path": self._folder_path,
            "poll_interval": self._poll_interval,
            "last_error": self._last_error or None,
            "last_checked_at": self._last_checked_at,
            "started_at": self._started_at if running else None,
            "events": [event.__dict__ for event in self._events[:20]],
        }

    def scan_once(self) -> list[FolderImportEvent]:
        with self._lock:
            folder_path = self._folder_path
        if not folder_path:
            return []
        folder = Path(folder_path)
        if not folder.is_dir():
            with self._lock:
                self._last_error = "本地收件箱文件夹已不可访问，监听已停止"
                self._last_checked_at = _now_iso()
            self._stop_event.set()
            return []
        created: list[FolderImportEvent] = []
        for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
            if self._stop_event.is_set() or not path.is_file() or path.name.startswith("."):
                continue
            try:
                import_kind_for_filename(path.name)
                stat = path.stat()
            except (OSError, ValueError):
                continue
            signature = (int(stat.st_mtime_ns), int(stat.st_size))
            key = str(path.resolve())
            with self._lock:
                if self._seen.get(key) == signature:
                    continue
                self._seen[key] = signature
            try:
                from services.local_folder_import import import_folder_file

                result = import_folder_file(path)
                event = FolderImportEvent(
                    path=key,
                    content_item_id=result.get("content_item_id"),
                    task_id=result.get("task_id"),
                    duplicate=bool(result.get("duplicate")),
                    created_at=_now_iso(),
                )
            except Exception as exc:
                event = FolderImportEvent(path=key, content_item_id=None, task_id=None, created_at=_now_iso(), error=str(exc))
                with self._lock:
                    self._last_error = event.error
            created.append(event)
            with self._lock:
                self._events.insert(0, event)
                self._events = self._events[:100]
        with self._lock:
            self._last_checked_at = _now_iso()
            if not created or not any(event.error for event in created):
                self._last_error = ""
        return created

    def _snapshot(self, folder: Path) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in folder.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                import_kind_for_filename(path.name)
                stat = path.stat()
                snapshot[str(path.resolve())] = (int(stat.st_mtime_ns), int(stat.st_size))
            except (OSError, ValueError):
                continue
        return snapshot

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.scan_once()
            with self._lock:
                interval = self._poll_interval
            self._stop_event.wait(interval)


folder_import_watcher = FolderImportWatcher()
