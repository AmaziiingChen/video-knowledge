"""Pure local-time report-window rules."""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta


def normalize_report_window(
    start: datetime, end: datetime
) -> tuple[datetime, datetime]:
    local_timezone = datetime.now().astimezone().tzinfo

    def localize(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=local_timezone)
            if value.tzinfo is None
            else value.astimezone(local_timezone)
        )

    return localize(start), localize(end)


def manual_report_window(report_type: str, end: date) -> tuple[datetime, datetime]:
    timezone = datetime.now().astimezone().tzinfo
    start_date = end if report_type == "daily" else end - timedelta(days=6)
    return datetime.combine(start_date, dt_time.min, tzinfo=timezone), datetime.combine(
        end, dt_time.max, tzinfo=timezone
    )


def in_window(value: str, start: datetime, end: datetime) -> bool:
    published = parse_publication_time(value, timezone=start.tzinfo)
    return bool(published and start <= published <= end)


def parse_publication_time(value: str, *, timezone) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return datetime.combine(
                date.fromisoformat(text), dt_time(hour=12), tzinfo=timezone
            )
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone)
    except ValueError:
        return None
