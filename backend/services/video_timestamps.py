from __future__ import annotations

import re
from collections.abc import Iterable


_TIMESTAMP_LABEL = re.compile(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})$")
_MARKDOWN_TIMESTAMP = re.compile(
    r"\[(?P<label>\d{1,2}:\d{2}(?::\d{2})?)\]"
    r"\((?:#(?:video-)?t=)(?P<seconds>\d+(?:\.\d+)?)\)"
)
_BARE_BRACKET_TIMESTAMP = re.compile(r"\[(?P<label>\d{1,2}:\d{2}(?::\d{2})?)\](?!\()")


def format_video_timestamp(seconds: float | int) -> str:
    total = max(0, int(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, remaining = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{remaining:02}"
    return f"{minutes:02}:{remaining:02}"


def timestamped_video_transcript(transcript: str, segments: Iterable[dict] | None) -> tuple[str, set[int]]:
    """Attach stable, copyable timestamp links to reliable subtitle segments.

    Approximate timeline entries are intentionally excluded: they are useful for
    scrolling a transcript, but not precise enough to cite in an AI summary.
    """
    lines: list[str] = []
    valid_seconds: set[int] = set()
    for segment in segments or []:
        if not isinstance(segment, dict) or segment.get("approximate"):
            continue
        text = str(segment.get("text") or "").strip()
        try:
            seconds = int(float(segment.get("start_seconds")))
        except (TypeError, ValueError):
            continue
        if not text or seconds < 0:
            continue
        valid_seconds.add(seconds)
        lines.append(f"[{format_video_timestamp(seconds)}](#video-t={seconds}) {text}")
    return ("\n".join(lines).strip() or str(transcript or "").strip(), valid_seconds)


def normalize_video_summary_timestamps(markdown: str, valid_seconds: set[int]) -> str:
    """Keep only timestamp links that point to a real source subtitle segment."""
    if not markdown or not valid_seconds:
        return str(markdown or "")

    def linked_replacement(match: re.Match[str]) -> str:
        try:
            seconds = int(float(match.group("seconds")))
        except (TypeError, ValueError):
            return match.group(0)
        if seconds not in valid_seconds:
            return match.group("label")
        return f"[{format_video_timestamp(seconds)}](#video-t={seconds})"

    normalized = _MARKDOWN_TIMESTAMP.sub(linked_replacement, str(markdown))

    def bare_replacement(match: re.Match[str]) -> str:
        seconds = timestamp_label_seconds(match.group("label"))
        if seconds is None or seconds not in valid_seconds:
            return match.group(0)
        return f"[{format_video_timestamp(seconds)}](#video-t={seconds})"

    return _BARE_BRACKET_TIMESTAMP.sub(bare_replacement, normalized)


def timestamp_label_seconds(value: str) -> int | None:
    match = _TIMESTAMP_LABEL.match(str(value or ""))
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds
