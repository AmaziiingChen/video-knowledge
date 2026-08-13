"""Strict JSON recovery and local-only diagnostics for group reports.

Model responses are untrusted.  This module accepts only valid JSON, apart from
the narrowly defined recovery for raw control characters inside JSON strings.
The exact invalid response remains local to the application data directory so a
report can be diagnosed without retrying a costly model call.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from config import settings
from services.database import utc_now_iso


def save_failed_json_output(label: str, value: str) -> Path:
    """Persist the exact invalid model payload locally for diagnosis."""
    raw = str(value or "")
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    timestamp = re.sub(r"[^0-9]", "", utc_now_iso())[:20]
    safe_label = _safe_label(label)
    directory = settings.data_dir / "diagnostics" / "group-report-plans"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timestamp}-{safe_label}-{digest}.invalid.json"
    path.write_text(raw, encoding="utf-8")
    path.chmod(0o600)
    return path


def save_planner_trace(label: str, payload: dict[str, object]) -> Path:
    """Persist a complete local-only planner reasoning and timing trace."""
    fingerprint = (
        str(payload.get("reasoning_content") or "")
        + "\n"
        + str(payload.get("content") or "")
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    timestamp = re.sub(r"[^0-9]", "", utc_now_iso())[:20]
    safe_label = _safe_label(label)
    directory = settings.data_dir / "diagnostics" / "group-report-plans"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{timestamp}-{safe_label}-{digest}.thinking.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def parse_json(value: str) -> object:
    """Return decoded JSON, or an empty object when the payload is invalid."""
    parsed, is_valid, _ = decode_json_payload(value)
    return parsed if is_valid else {}


def is_json_payload(value: str) -> bool:
    """Whether a response is valid under the report JSON recovery policy."""
    _, is_valid, _ = decode_json_payload(value)
    return is_valid


def decode_json_payload(value: str) -> tuple[object, bool, bool]:
    """Decode JSON, tolerating only unescaped control characters in strings."""
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    candidates = [text]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        extracted = text[start : end + 1]
        if extracted != text:
            candidates.append(extracted)
    for candidate in candidates:
        try:
            return json.loads(candidate), True, False
        except json.JSONDecodeError as exc:
            if not exc.msg.startswith("Invalid control character"):
                continue
            try:
                return json.loads(candidate, strict=False), True, True
            except json.JSONDecodeError:
                continue
    return {}, False, False


def _safe_label(label: str) -> str:
    return (
        re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", label).strip("-")
        or "json"
    )
