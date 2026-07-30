"""Reliable, model-free delivery of KnowledgeHub terminal task results."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
from threading import Event, Thread
from typing import Callable

from services.openclaw_conversations import (
    complete_terminal_notification,
    release_terminal_notification,
    reserve_terminal_notifications,
)


logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10


class OpenClawNotificationError(RuntimeError):
    pass


def _session_hash(session_key: str) -> str:
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()


def _session_indexes() -> list[Path]:
    return list((Path.home() / ".openclaw" / "agents").glob("*/sessions/sessions.json"))


def _resolve_weixin_route(session_hash: str, *, indexes: list[Path] | None = None) -> dict[str, str]:
    for index_path in indexes if indexes is not None else _session_indexes():
        try:
            sessions = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(sessions, dict):
            continue
        for session_key, metadata in sessions.items():
            if not isinstance(session_key, str) or _session_hash(session_key) != session_hash or not isinstance(metadata, dict):
                continue
            route = metadata.get("route") if isinstance(metadata.get("route"), dict) else {}
            target = route.get("target") if isinstance(route.get("target"), dict) else {}
            channel = str(route.get("channel") or metadata.get("lastChannel") or "")
            account_id = str(route.get("accountId") or metadata.get("lastAccountId") or "")
            recipient = str(target.get("to") or "")
            if channel != "openclaw-weixin" or not account_id or not recipient.endswith("@im.wechat"):
                raise OpenClawNotificationError("未找到可用的微信原会话投递路由")
            return {"channel": channel, "account_id": account_id, "recipient": recipient}
    raise OpenClawNotificationError("对应的 OpenClaw 会话已不可用，暂不能投递")


def _notification_text(delivery: dict[str, object]) -> str:
    status = str(delivery["status"])
    if status == "succeeded":
        try:
            result = json.loads(str(delivery.get("result_json") or ""))
        except json.JSONDecodeError:
            result = {}
        summary = str(result.get("summary") or "").strip() if isinstance(result, dict) else ""
        if summary:
            # This is the exact DeepSeek-generated summary. Do not pass it
            # through an OpenClaw agent or prepend an agent-written paraphrase.
            return summary
        return "处理已完成，但本次没有生成 DeepSeek 总结。"
    if status == "cancelled":
        return "处理已取消。"
    error = str(delivery.get("error_message") or "处理失败，请稍后重试。").strip()
    return f"处理失败：{error}"


def _openclaw_binary() -> str:
    executable = shutil.which("openclaw") or str(Path.home() / ".npm-global" / "bin" / "openclaw")
    if not Path(executable).is_file():
        raise OpenClawNotificationError("未找到 OpenClaw CLI")
    return executable


def _send_weixin_text(route: dict[str, str], text: str) -> None:
    result = subprocess.run(
        [
            _openclaw_binary(), "message", "send",
            "--channel", route["channel"],
            "--account", route["account_id"],
            "--target", route["recipient"],
            "--message", text,
            "--json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "OpenClaw 微信投递失败").strip()
        raise OpenClawNotificationError(detail[:300])


def deliver_pending_notifications(
    *,
    indexes: list[Path] | None = None,
    sender: Callable[[dict[str, str], str], None] = _send_weixin_text,
) -> int:
    """Deliver each reserved terminal result directly through the Weixin plugin."""
    delivered = 0
    for item in reserve_terminal_notifications():
        session_hash = str(item["session_hash"])
        task_id = str(item["task_id"])
        reservation_id = str(item["reservation_id"])
        try:
            sender(_resolve_weixin_route(session_hash, indexes=indexes), _notification_text(item))
        except (OSError, subprocess.SubprocessError, OpenClawNotificationError) as exc:
            release_terminal_notification(
                session_hash=session_hash,
                task_id=task_id,
                reservation_id=reservation_id,
                error=str(exc),
            )
            logger.warning("OpenClaw terminal delivery deferred for task %s", task_id)
            continue
        if complete_terminal_notification(
            session_hash=session_hash,
            task_id=task_id,
            reservation_id=reservation_id,
        ):
            delivered += 1
    return delivered


class OpenClawNotificationScheduler:
    def __init__(self) -> None:
        self._wake_event = Event()
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, name="openclaw-notifications", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def wake(self) -> None:
        self._wake_event.set()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                deliver_pending_notifications()
            except Exception:
                logger.exception("OpenClaw terminal delivery scan failed")
            self._wake_event.wait(POLL_INTERVAL_SECONDS)
            self._wake_event.clear()


openclaw_notification_scheduler = OpenClawNotificationScheduler()
