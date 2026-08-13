"""Pure title and file-name rules for generated reports."""

from __future__ import annotations

import re
from datetime import date, datetime


def report_title(
    report_type: str,
    *,
    start: date,
    end: date,
    group_name: str,
    title_window: tuple[datetime, datetime] | None = None,
) -> str:
    if report_type == "range" and title_window is not None:
        window_start, window_end = title_window
        if window_start.date() == window_end.date():
            period = f"{window_start.date().isoformat()} {window_start.strftime('%H时%M分')}至{window_end.strftime('%H时%M分')}区间汇总"
        else:
            period = f"{window_start.strftime('%Y-%m-%d %H时%M分')}至{window_end.strftime('%Y-%m-%d %H时%M分')}区间汇总"
        return f"{period}｜{group_name}"
    period = (
        f"{end.isoformat()}日报"
        if report_type == "daily"
        else f"{start.isoformat()}至{end.isoformat()}周报"
    )
    return f"{period}｜{group_name}"


def safe_report_document_name(value: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    return stem.rstrip(". ")[:96] or "报告"


def report_document_name(
    requested_name: str | None,
    *,
    report_type: str,
    start: date,
    end: date,
    group_name: str,
    title_window: tuple[datetime, datetime] | None,
) -> str:
    requested = " ".join(str(requested_name or "").replace("\x00", "").split()).strip()
    if requested.lower().endswith(".md"):
        requested = requested[:-3].rstrip()
    if requested:
        return safe_report_document_name(requested)
    if report_type == "range" and title_window is not None:
        window_start, window_end = title_window
        start_label = window_start.date().isoformat()
        end_label = (
            f"{window_end.month:02d}-{window_end.day:02d}"
            if window_start.year == window_end.year
            else window_end.date().isoformat()
        )
        period = (
            start_label
            if window_start.date() == window_end.date()
            else f"{start_label}至{end_label}"
        )
        return safe_report_document_name(f"{group_name}｜{period}汇总")
    if report_type == "daily":
        return safe_report_document_name(f"{group_name}｜{end.isoformat()}日报")
    return safe_report_document_name(
        f"{group_name}｜{start.isoformat()}至{end.month:02d}-{end.day:02d}周报"
    )
