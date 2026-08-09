from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any

import httpx

from config import settings
from services.clipboard_watcher import extract_supported_links
from services.pipeline_runner import PipelineRequest
from services.task_manager import task_manager
from services.telegram_settings import load_telegram_settings, save_telegram_watcher_checkpoint
from services.manual_collection_settings import manual_collection_settings


TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_token(token: str | None) -> str | None:
    if not token:
        return None
    if len(token) <= 10:
        return "***"
    return f"{token[:6]}...{token[-4:]}"


def _mask_proxy(proxy_url: str | None) -> str | None:
    if not proxy_url:
        return None
    if "@" not in proxy_url:
        return proxy_url
    scheme, rest = proxy_url.split("://", 1) if "://" in proxy_url else ("", proxy_url)
    host = rest.rsplit("@", 1)[-1]
    return f"{scheme}://***@{host}" if scheme else f"***@{host}"


def _as_nonnegative_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _allowed_user_ids(value: Any) -> set[int]:
    if not isinstance(value, list):
        return set()
    user_ids: set[int] = set()
    for item in value:
        parsed = _as_nonnegative_int(item)
        if parsed is not None and parsed > 0:
            user_ids.add(parsed)
    return user_ids


@dataclass
class TelegramEvent:
    update_id: int
    message_id: int | None
    chat_id: int | None
    user_id: int | None
    text: str
    link: str
    task_id: str | None
    created_at: str
    duplicate: bool = False


class TelegramWatcher:
    def __init__(self) -> None:
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._bot_token: str | None = None
        self._allowed_user_ids: set[int] = set()
        self._last_update_id: int | None = None
        self._last_error: str | None = None
        self._last_checked_at: str | None = None
        self._started_at: str | None = None
        self._events: list[TelegramEvent] = []
        self._seen_links: set[str] = set()
        self._reply_enabled = True
        self._use_cache = True
        self._whisper_model: str | None = None
        self._ai_model: str | None = None
        self._asr_options: dict[str, Any] = {}
        self._poll_timeout = 8
        self._restore_saved_settings()

    def _restore_saved_settings(self) -> None:
        saved = load_telegram_settings()
        token = str(saved.get("bot_token") or "").strip()
        if not token:
            return
        self._bot_token = token
        self._allowed_user_ids = _allowed_user_ids(saved.get("allowed_user_ids"))
        self._reply_enabled = bool(saved.get("reply_enabled", True))
        self._last_update_id = _as_nonnegative_int(saved.get("last_update_id"))
        watch_options = saved.get("watch_options") if isinstance(saved.get("watch_options"), dict) else {}
        self._whisper_model = watch_options.get("whisper_model")
        self._ai_model = watch_options.get("ai_model")
        self._use_cache = bool(watch_options.get("use_cache", True))
        self._asr_options = {
            "asr_backend": watch_options.get("asr_backend"),
            "asr_model_strategy": watch_options.get("asr_model_strategy"),
            "asr_short_video_model": watch_options.get("asr_short_video_model"),
            "asr_long_video_model": watch_options.get("asr_long_video_model"),
            "asr_beam_size": watch_options.get("asr_beam_size"),
            "asr_vad_filter": watch_options.get("asr_vad_filter"),
            "asr_fallback_enabled": watch_options.get("asr_fallback_enabled"),
        }

    def configure(
        self,
        *,
        bot_token: str,
        allowed_user_ids: list[int],
        reply_enabled: bool = True,
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
    ) -> dict:
        with self._lock:
            self._bot_token = bot_token.strip()
            self._allowed_user_ids = {int(user_id) for user_id in allowed_user_ids}
            self._reply_enabled = reply_enabled
            self._whisper_model = whisper_model
            self._ai_model = ai_model
            self._use_cache = use_cache
            self._asr_options = {
                "asr_backend": asr_backend,
                "asr_model_strategy": asr_model_strategy,
                "asr_short_video_model": asr_short_video_model,
                "asr_long_video_model": asr_long_video_model,
                "asr_beam_size": asr_beam_size,
                "asr_vad_filter": asr_vad_filter,
                "asr_fallback_enabled": asr_fallback_enabled,
            }
            self._last_error = None
        return self.status()

    def start(self) -> dict:
        with self._lock:
            if not self._bot_token:
                self._last_error = "Telegram Bot Token 未配置"
                return self.status()
            if not self._allowed_user_ids:
                self._last_error = "Telegram 用户白名单未配置"
                return self.status()
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._started_at = _now_iso()
            self._last_error = None
            self._thread = Thread(target=self._run, daemon=True, name="telegram-watcher")
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
            "configured": bool(self._bot_token),
            "bot_token_masked": _mask_token(self._bot_token),
            "proxy_url_masked": _mask_proxy((settings.telegram_proxy_url or "").strip()),
            "allowed_user_ids": sorted(self._allowed_user_ids),
            "reply_enabled": self._reply_enabled,
            "whisper_model": self._whisper_model,
            **self._asr_options,
            "ai_model": self._ai_model,
            "use_cache": self._use_cache,
            "last_update_id": self._last_update_id,
            "last_error": self._last_error,
            "last_checked_at": self._last_checked_at,
            "started_at": self._started_at if running else None,
            "captured_links": [
                {
                    "update_id": event.update_id,
                    "message_id": event.message_id,
                    "chat_id": event.chat_id,
                    "user_id": event.user_id,
                    "link": event.link,
                    "task_id": event.task_id,
                    "created_at": event.created_at,
                    "duplicate": event.duplicate,
                }
                for event in self._events[:20]
            ],
            "created_task_ids": [event.task_id for event in self._events[:50] if event.task_id],
        }

    def test_connection(self, bot_token: str | None = None) -> dict:
        token = (bot_token or self._bot_token or "").strip()
        if not token:
            raise RuntimeError("Telegram Bot Token 未配置")
        data = self._request(token, "getMe")
        return {
            "ok": True,
            "id": data.get("id"),
            "username": data.get("username"),
            "first_name": data.get("first_name"),
        }

    def poll_once(self) -> list[TelegramEvent]:
        with self._lock:
            token = self._bot_token
            offset = self._last_update_id + 1 if self._last_update_id is not None else None
        if not token:
            return []

        params: dict[str, Any] = {
            "timeout": 1,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = offset
        try:
            updates = self._request(token, "getUpdates", params=params)
            events = self._handle_updates(updates if isinstance(updates, list) else [])
            with self._lock:
                self._last_error = None
                self._last_checked_at = _now_iso()
            return events
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
                self._last_checked_at = _now_iso()
            return []

    def _run(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                token = self._bot_token
                offset = self._last_update_id + 1 if self._last_update_id is not None else None
                timeout = self._poll_timeout
            if not token:
                self._stop_event.wait(5)
                continue
            params: dict[str, Any] = {
                "timeout": timeout,
                "allowed_updates": ["message"],
            }
            if offset is not None:
                params["offset"] = offset
            try:
                updates = self._request(token, "getUpdates", params=params, timeout=timeout + 5)
                self._handle_updates(updates if isinstance(updates, list) else [])
                with self._lock:
                    self._last_error = None
                    self._last_checked_at = _now_iso()
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                    self._last_checked_at = _now_iso()
                self._stop_event.wait(5)

    def _handle_updates(self, updates: list[dict]) -> list[TelegramEvent]:
        created: list[TelegramEvent] = []
        for update in updates:
            update_id = int(update.get("update_id", 0))
            message = update.get("message") or {}
            text = str(message.get("text") or message.get("caption") or "")
            sender = message.get("from") or {}
            user_id = sender.get("id")
            chat = message.get("chat") or {}
            chat_id = chat.get("id")
            message_id = message.get("message_id")
            with self._lock:
                allowed = int(user_id or 0) in self._allowed_user_ids
            if not allowed:
                if chat_id:
                    self._send_message(chat_id, "未授权的 Telegram 用户，已忽略。")
                self._mark_update_processed(update_id)
                continue

            links = extract_supported_links(text)
            if not links:
                if chat_id and text.strip():
                    self._send_message(chat_id, "暂未识别到可处理链接。支持抖音、B站、微信公众号文章和小红书笔记。")
                self._mark_update_processed(update_id)
                continue

            for link in links:
                with self._lock:
                    duplicate = link in self._seen_links
                    if not duplicate:
                        self._seen_links.add(link)
                    whisper_model = self._whisper_model
                    asr_options = dict(self._asr_options)
                    ai_model = self._ai_model
                    use_cache = self._use_cache
                if duplicate:
                    event = TelegramEvent(
                        update_id=update_id,
                        message_id=message_id,
                        chat_id=chat_id,
                        user_id=user_id,
                        text=text,
                        link=link,
                        task_id=None,
                        created_at=_now_iso(),
                        duplicate=True,
                    )
                    created.append(event)
                    self._record_event(event)
                    if chat_id:
                        self._send_message(chat_id, f"已收到过，跳过重复链接：{link}")
                    continue

                record = task_manager.create(
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
                event = TelegramEvent(
                    update_id=update_id,
                    message_id=message_id,
                    chat_id=chat_id,
                    user_id=user_id,
                    text=text,
                    link=link,
                    task_id=record.task_id,
                    created_at=_now_iso(),
                )
                created.append(event)
                self._record_event(event)
                if chat_id:
                    self._send_message(chat_id, f"已加入处理队列：{link}")
            self._mark_update_processed(update_id)
        return created

    def _mark_update_processed(self, update_id: int) -> None:
        if update_id < 0:
            return
        with self._lock:
            if self._last_update_id is not None and update_id <= self._last_update_id:
                return
            self._last_update_id = update_id
        save_telegram_watcher_checkpoint(update_id)

    def _record_event(self, event: TelegramEvent) -> None:
        with self._lock:
            self._events.insert(0, event)
            self._events = self._events[:100]

    def _send_message(self, chat_id: int, text: str) -> None:
        with self._lock:
            token = self._bot_token
            enabled = self._reply_enabled
        if not token or not enabled:
            return
        try:
            self._request(token, "sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
        except Exception:
            return

    def _request(
        self,
        token: str,
        method: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float = 15,
    ) -> Any:
        url = TELEGRAM_API.format(token=token, method=method)
        proxy = (settings.telegram_proxy_url or "").strip() or None
        request_timeout = httpx.Timeout(
            timeout + 10,
            connect=10,
            read=timeout + 10,
            write=10,
            pool=10,
        )
        with httpx.Client(proxy=proxy, timeout=request_timeout, trust_env=False) as client:
            response = client.post(url, params=params, json=json)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(str(payload.get("description") or "Telegram API 调用失败"))
        return payload.get("result")


telegram_watcher = TelegramWatcher()
