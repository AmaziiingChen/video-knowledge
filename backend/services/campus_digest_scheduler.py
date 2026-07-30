from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
import json
from threading import Event, Lock, Thread

from config import settings
from services.campus_source_settings import load_campus_source_settings
from services.database import connect, initialize_database, utc_now_iso
from services.wechat_reports import generate_report


@dataclass(frozen=True)
class ScheduledDigestWindow:
    report_type: str
    window_start: datetime
    window_end: datetime
    generate_at: datetime


class CampusDigestScheduler:
    """Generate local drafts after the agreed daily and weekly cutoffs."""

    def __init__(self) -> None:
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        if not settings.campus_digest_scheduler_enabled:
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="campus-digest-generate", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        # Give the source schedulers a short head start after a cold desktop
        # launch, without blocking FastAPI startup.
        if not self._stop_event.wait(5):
            self._generate_due_safely()
        interval = max(15, int(settings.campus_digest_scheduler_interval_seconds))
        while not self._stop_event.wait(interval):
            self._generate_due_safely()

    def _generate_due_safely(self) -> None:
        now = datetime.now().astimezone()
        initialize_database()
        group_ids = {
            str(group_id)
            for source in load_campus_source_settings()
            for group_id in source.get("group_ids", [])
        }
        windows = [latest_daily_window(now), latest_weekly_window(now)]
        for group_id in sorted(group_ids):
            if self._stop_event.is_set():
                return
            for window in windows:
                if now < window.generate_at or self._already_generated(group_id, window):
                    continue
                if not self._may_attempt(group_id, window, now):
                    continue
                try:
                    generate_report(
                        group_id,
                        window.report_type,
                        period_end=window.window_end.date(),
                        window_start=window.window_start,
                        window_end=window.window_end,
                        generation_trigger="scheduled",
                    )
                except ValueError as exc:
                    message = str(exc)
                    status = "no_sources" if "没有可汇总" in message or "没有可生成" in message else "error"
                    self._record_attempt(group_id, window, status=status, message=message)
                except Exception as exc:
                    self._record_attempt(group_id, window, status="error", message=str(exc))
                else:
                    self._record_attempt(group_id, window, status="success", message="草稿已生成")

    @staticmethod
    def _already_generated(group_id: str, window: ScheduledDigestWindow) -> bool:
        with connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM wechat_reports
                   WHERE group_id=? AND report_type=? AND window_end=?
                   LIMIT 1""",
                (group_id, window.report_type, window.window_end.isoformat()),
            ).fetchone()
        return row is not None

    @staticmethod
    def _state_key(group_id: str, window: ScheduledDigestWindow) -> str:
        return f"attempt:{group_id}:{window.report_type}:{window.window_end.isoformat()}"

    def _may_attempt(self, group_id: str, window: ScheduledDigestWindow, now: datetime) -> bool:
        key = self._state_key(group_id, window)
        with connect() as connection:
            row = connection.execute(
                "SELECT state_value, updated_at FROM campus_digest_scheduler_state WHERE state_key=?",
                (key,),
            ).fetchone()
        if not row:
            return True
        try:
            state = json.loads(str(row["state_value"]))
        except json.JSONDecodeError:
            return True
        if state.get("status") in {"success", "no_sources"}:
            return False
        try:
            updated = datetime.fromisoformat(str(row["updated_at"])).astimezone(now.tzinfo)
        except ValueError:
            return True
        return now >= updated + timedelta(minutes=15)

    def _record_attempt(
        self,
        group_id: str,
        window: ScheduledDigestWindow,
        *,
        status: str,
        message: str,
    ) -> None:
        key = self._state_key(group_id, window)
        now = utc_now_iso()
        value = json.dumps(
            {"status": status, "message": str(message)[:500]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with connect() as connection:
            connection.execute(
                """INSERT INTO campus_digest_scheduler_state(state_key,state_value,updated_at)
                   VALUES (?,?,?)
                   ON CONFLICT(state_key) DO UPDATE SET
                     state_value=excluded.state_value, updated_at=excluded.updated_at""",
                (key, value, now),
            )
            connection.commit()


def latest_daily_window(now: datetime) -> ScheduledDigestWindow:
    cutoff = _parse_clock(settings.campus_digest_daily_cutoff)
    generate_clock = _parse_clock(settings.campus_digest_daily_generate_at)
    target = now.date() if now.timetz().replace(tzinfo=None) >= generate_clock else now.date() - timedelta(days=1)
    window_end = datetime.combine(target, cutoff, tzinfo=now.tzinfo)
    window_start = datetime.combine(target - timedelta(days=1), cutoff, tzinfo=now.tzinfo)
    generate_at = datetime.combine(target, generate_clock, tzinfo=now.tzinfo)
    return ScheduledDigestWindow("daily", window_start, window_end, generate_at)


def latest_weekly_window(now: datetime) -> ScheduledDigestWindow:
    cutoff = _parse_clock(settings.campus_digest_weekly_cutoff)
    generate_clock = _parse_clock(settings.campus_digest_weekly_generate_at)
    days_since_sunday = (now.weekday() + 1) % 7
    target = now.date() - timedelta(days=days_since_sunday)
    target_generate = datetime.combine(target, generate_clock, tzinfo=now.tzinfo)
    if now < target_generate:
        target -= timedelta(days=7)
        target_generate = datetime.combine(target, generate_clock, tzinfo=now.tzinfo)
    window_end = datetime.combine(target, cutoff, tzinfo=now.tzinfo)
    window_start = datetime.combine(target - timedelta(days=7), cutoff, tzinfo=now.tzinfo)
    return ScheduledDigestWindow("weekly", window_start, window_end, target_generate)


def _parse_clock(value: str) -> dt_time:
    try:
        hour, minute = str(value).split(":", 1)
        return dt_time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError):
        raise ValueError(f"无效的本机调度时间：{value}")


campus_digest_scheduler = CampusDigestScheduler()


__all__ = [
    "CampusDigestScheduler",
    "ScheduledDigestWindow",
    "campus_digest_scheduler",
    "latest_daily_window",
    "latest_weekly_window",
]
