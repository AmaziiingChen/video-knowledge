from __future__ import annotations

from datetime import date
import re


PUBLISHED_AT_PARSER_VERSION = 1
_NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*"
    r"(?P<day>\d{1,2})\s*日?"
    r"(?:\s*T?\s*(?P<hour>[01]?\d|2[0-3])\s*(?:[:：]|时)\s*"
    r"(?P<minute>[0-5]?\d)(?:\s*(?:[:：]|分)\s*(?P<second>[0-5]?\d)\s*秒?)?\s*分?)?"
)
_ENGLISH_DATE_RE = re.compile(
    r"\b(?P<month_name>January|February|March|April|May|June|July|August|September|October|"
    r"November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+"
    r"(?P<day>\d{1,2}),\s*(?P<year>20\d{2})"
    r"(?:\s+(?P<hour>[01]?\d|2[0-3])\s*[:：]\s*(?P<minute>[0-5]?\d)"
    r"(?:\s*[:：]\s*(?P<second>[0-5]?\d))?)?\b",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def extract_published_at(value: str) -> str:
    """Normalize a visible publication time without inventing extra precision."""
    text = str(value or "")
    numeric = _NUMERIC_DATE_RE.search(text)
    english = _ENGLISH_DATE_RE.search(text)
    matches = [match for match in (numeric, english) if match is not None]
    if not matches:
        return ""
    match = min(matches, key=lambda item: item.start())
    month_name = match.groupdict().get("month_name")
    month = _MONTHS[month_name.lower()] if month_name else int(match.group("month"))
    year = int(match.group("year"))
    day = int(match.group("day"))
    try:
        date(year, month, day)
    except ValueError:
        return ""

    normalized = f"{year:04d}-{month:02d}-{day:02d}"
    hour = match.groupdict().get("hour")
    minute = match.groupdict().get("minute")
    second = match.groupdict().get("second")
    if hour is not None and minute is not None:
        normalized += f" {int(hour):02d}:{int(minute):02d}"
        if second is not None:
            normalized += f":{int(second):02d}"
    return normalized


__all__ = ["PUBLISHED_AT_PARSER_VERSION", "extract_published_at"]
