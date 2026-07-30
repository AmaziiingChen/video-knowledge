from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import platform
import re
import subprocess
from threading import Event, Lock, Thread

from services.inbox import capture_link_to_inbox
from services.manual_collection_settings import manual_collection_settings
from services.pipeline_runner import PipelineRequest
from services.task_manager import TaskRecord, task_manager


VIDEO_LINK_PATTERNS = [
    re.compile(r"https?://v\.douyin\.com/[A-Za-z0-9_/-]+"),
    re.compile(r"https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9]+"),
    re.compile(r"https?://b23\.tv/[A-Za-z0-9]+"),
    re.compile(r"https?://mp\.weixin\.qq\.com/[^\s]+"),
    re.compile(
        r"https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item|search_result)/[^\s]+",
        re.IGNORECASE,
    ),
    re.compile(r"https?://(?:www\.)?xhslink\.com/[^\s]+", re.IGNORECASE),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_supported_links(text: str) -> list[str]:
    if not text.strip():
        return []

    matches: list[tuple[int, str]] = []
    for pattern in VIDEO_LINK_PATTERNS:
        for match in pattern.finditer(text):
            link = match.group(0).rstrip("，。；、,.!?)）]")
            matches.append((match.start(), link))
    links: list[str] = []
    for _, link in sorted(matches, key=lambda item: item[0]):
        if link not in links:
            links.append(link)
    return links


def read_system_clipboard() -> str:
    """Read the native clipboard without adding a GUI toolkit dependency."""
    system = platform.system()
    if system == "Darwin":
        command = ["pbpaste"]
    elif system == "Windows":
        command = ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    else:
        raise RuntimeError("本机剪贴板监听仅支持 macOS 和 Windows")
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=1,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "读取剪贴板失败")
    return result.stdout


def read_macos_clipboard() -> str:
    """Compatibility alias retained for integrations importing the old name."""
    return read_system_clipboard()


@dataclass
class ClipboardEvent:
    link: str
    item_id: str | None
    task_id: str | None
    created_at: str
    duplicate: bool = False
    capture_mode: str = "inbox"


TaskCreator = Callable[[PipelineRequest], TaskRecord]
ClipboardReader = Callable[[], str]


class ClipboardWatcher:
    def __init__(
        self,
        task_creator: TaskCreator | None = None,
        clipboard_reader: ClipboardReader | None = None,
    ) -> None:
        self._task_creator = task_creator or task_manager.create
        self._clipboard_reader = clipboard_reader or read_system_clipboard
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._last_clipboard_text: str = ""
        self._events: list[ClipboardEvent] = []
        self._last_error: str | None = None
        self._last_checked_at: str | None = None
        self._started_at: str | None = None
        self._whisper_model: str | None = None
        self._use_cache = True
        self._ai_model: str | None = None
        self._poll_interval = 2.5
        self._capture_mode = "task"
        self._asr_options: dict = {}

    def start(
        self,
        whisper_model: str | None = None,
        asr_backend: str | None = None,
        asr_model_strategy: str | None = None,
        asr_short_video_model: str | None = None,
        asr_long_video_model: str | None = None,
        asr_beam_size: int | None = None,
        asr_vad_filter: bool | None = None,
        asr_fallback_enabled: bool | None = None,
        ai_model: str | None = None,
        use_cache: bool = True,
        poll_interval: float = 2.5,
        capture_mode: str = "task",
        skip_current_clipboard: bool = False,
    ) -> dict:
        with self._lock:
            self._whisper_model = whisper_model
            self._asr_options = {
                "asr_backend": asr_backend,
                "asr_model_strategy": asr_model_strategy,
                "asr_short_video_model": asr_short_video_model,
                "asr_long_video_model": asr_long_video_model,
                "asr_beam_size": asr_beam_size,
                "asr_vad_filter": asr_vad_filter,
                "asr_fallback_enabled": asr_fallback_enabled,
            }
            self._use_cache = use_cache
            self._ai_model = ai_model
            self._poll_interval = max(1.0, min(float(poll_interval), 10.0))
            self._capture_mode = capture_mode if capture_mode in {"inbox", "task"} else "task"
            self._last_error = None
            if self._thread and self._thread.is_alive():
                return self.status()

            if skip_current_clipboard:
                # A restored watcher must not create a second task for the
                # link that happened to be on the clipboard when the desktop
                # app was closed.  Manual starts retain the existing behavior.
                try:
                    self._last_clipboard_text = self._clipboard_reader().strip()
                except Exception as exc:
                    self._last_error = str(exc)
            self._stop_event.clear()
            self._started_at = _now_iso()
            self._thread = Thread(target=self._run, daemon=True, name="clipboard-watcher")
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
            "whisper_model": self._whisper_model,
            **self._asr_options,
            "ai_model": self._ai_model,
            "use_cache": self._use_cache,
            "poll_interval": self._poll_interval,
            "capture_mode": self._capture_mode,
            "last_error": self._last_error,
            "last_checked_at": self._last_checked_at,
            "started_at": self._started_at if running else None,
            "captured_links": [
                {
                    "link": event.link,
                    "item_id": event.item_id,
                    "task_id": event.task_id,
                    "created_at": event.created_at,
                    "duplicate": event.duplicate,
                    "capture_mode": event.capture_mode,
                }
                for event in self._events[:20]
            ],
            "created_task_ids": [event.task_id for event in self._events[:50] if event.task_id],
        }

    def scan_once(self) -> list[ClipboardEvent]:
        try:
            text = self._clipboard_reader()
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._last_checked_at = _now_iso()
            return []
        return self.scan_text(text)

    def scan_text(self, text: str) -> list[ClipboardEvent]:
        normalized_text = text.strip()
        with self._lock:
            if normalized_text == self._last_clipboard_text:
                self._last_checked_at = _now_iso()
                return []
            self._last_clipboard_text = normalized_text

        links = extract_supported_links(text)
        created: list[ClipboardEvent] = []
        for link in links:
            with self._lock:
                whisper_model = self._whisper_model
                asr_options = dict(self._asr_options)
                use_cache = self._use_cache
                ai_model = self._ai_model
                capture_mode = self._capture_mode

            if capture_mode == "task":
                record = self._task_creator(
                    PipelineRequest(
                        share_text=link,
                        whisper_model=whisper_model,
                        **asr_options,
                        ai_model=ai_model,
                        use_cache=use_cache,
                        processing_mode="full" if manual_collection_settings()["auto_summarize"] else "transcript",
                        manual_collection=True,
                        execution_mode="background",
                    )
                )
                event = ClipboardEvent(
                    link=link,
                    item_id=None,
                    task_id=record.task_id,
                    created_at=_now_iso(),
                    capture_mode="task",
                )
            else:
                result = capture_link_to_inbox(link)
                if result.error or result.item is None:
                    with self._lock:
                        self._last_error = result.error or "收件箱捕获失败"
                    continue
                event = ClipboardEvent(
                    link=link,
                    item_id=result.item.id,
                    task_id=None,
                    created_at=_now_iso(),
                    duplicate=result.duplicate,
                    capture_mode="inbox",
                )
            created.append(event)
            with self._lock:
                self._events.insert(0, event)
                self._events = self._events[:100]

        with self._lock:
            self._last_error = None
            self._last_checked_at = _now_iso()
        return created

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.scan_once()
            with self._lock:
                interval = self._poll_interval
            self._stop_event.wait(interval)


clipboard_watcher = ClipboardWatcher()
