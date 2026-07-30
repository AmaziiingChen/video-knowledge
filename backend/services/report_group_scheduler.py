"""Local, opt-in schedules for generating report-group summaries.

Schedules run only while the desktop backend is alive.  Each due minute is
claimed in SQLite before invoking the model pipeline so a restart or the
30-second polling loop cannot create duplicate, billable reports.
"""

from __future__ import annotations

import json
from datetime import datetime
from threading import Event, Lock, Thread

from services.database import connect, initialize_database, utc_now_iso
from services.wechat_reports import generate_report


class ReportGroupScheduler:
    def __init__(self) -> None:
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(target=self._run, name="report-group-scheduler", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run(self) -> None:
        # Keep desktop startup responsive, while still allowing an imminent
        # scheduled minute to be picked up by the first scan.
        if self._stop_event.wait(3):
            return
        while not self._stop_event.is_set():
            self.run_due_once()
            self._stop_event.wait(20)

    def run_due_once(self, *, now: datetime | None = None) -> None:
        current = now or datetime.now().astimezone()
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                """SELECT group_id, report_type, weekdays_json, time_of_day
                   FROM wechat_report_group_schedules
                   WHERE enabled=1
                   ORDER BY time_of_day, group_id"""
            ).fetchall()
        for row in rows:
            if self._stop_event.is_set():
                return
            try:
                weekdays = {int(item) for item in json.loads(str(row["weekdays_json"] or "[]"))}
            except (TypeError, ValueError, json.JSONDecodeError):
                self._record_error(str(row["group_id"]), "定时星期设置无效")
                continue
            if current.isoweekday() not in weekdays or current.strftime("%H:%M") != str(row["time_of_day"]):
                continue
            slot = f"{current.date().isoformat()}T{current.strftime('%H:%M')}"
            group_id = str(row["group_id"])
            if not self._claim_slot(group_id, slot):
                continue
            try:
                generate_report(
                    group_id,
                    str(row["report_type"]),
                    generation_trigger="scheduled",
                )
            except Exception as exc:
                self._record_result(group_id, status="error", message=str(exc))
            else:
                self._record_result(group_id, status="success", message="")

    @staticmethod
    def _claim_slot(group_id: str, slot: str) -> bool:
        now = utc_now_iso()
        with connect() as connection:
            result = connection.execute(
                """UPDATE wechat_report_group_schedules
                   SET last_run_slot=?, last_status='running', last_error='',
                       last_run_at=?, updated_at=?
                   WHERE group_id=? AND enabled=1 AND last_run_slot<>?""",
                (slot, now, now, group_id, slot),
            )
            connection.commit()
        return result.rowcount == 1

    @staticmethod
    def _record_result(group_id: str, *, status: str, message: str) -> None:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """UPDATE wechat_report_group_schedules
                   SET last_status=?, last_error=?, last_run_at=?, updated_at=?
                   WHERE group_id=?""",
                (status, str(message or "")[:600], now, now, group_id),
            )
            connection.commit()

    @classmethod
    def _record_error(cls, group_id: str, message: str) -> None:
        cls._record_result(group_id, status="error", message=message)


report_group_scheduler = ReportGroupScheduler()


__all__ = ["ReportGroupScheduler", "report_group_scheduler"]
