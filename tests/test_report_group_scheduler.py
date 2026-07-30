from __future__ import annotations

from datetime import datetime, timezone

from services.report_group_scheduler import ReportGroupScheduler
from services.wechat_reports import create_group, list_groups, update_report_schedule


def test_report_group_schedule_is_saved_with_group_projection():
    group = create_group("定时校园生活")

    saved = update_report_schedule(
        group["id"],
        enabled=True,
        report_type="weekly",
        weekdays=[1, 3, 5],
        time_of_day="08:30",
    )

    assert saved["enabled"] is True
    assert saved["weekdays"] == [1, 3, 5]
    projected = next(item for item in list_groups() if item["id"] == group["id"])
    assert projected["schedule_enabled"] is True
    assert projected["schedule_report_type"] == "weekly"
    assert projected["schedule_time_of_day"] == "08:30"


def test_report_group_schedule_claims_each_due_minute_only_once(monkeypatch):
    group = create_group("定时市场")
    update_report_schedule(
        group["id"],
        enabled=True,
        report_type="daily",
        weekdays=[1],
        time_of_day="09:00",
    )
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "services.report_group_scheduler.generate_report",
        lambda group_id, report_type, generation_trigger: calls.append(
            (group_id, report_type, generation_trigger)
        ),
    )
    scheduler = ReportGroupScheduler()
    monday = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)

    scheduler.run_due_once(now=monday)
    scheduler.run_due_once(now=monday)

    assert calls == [(group["id"], "daily", "scheduled")]
