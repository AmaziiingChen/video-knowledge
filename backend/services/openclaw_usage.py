"""Read aggregate OpenClaw usage without exposing transcripts or credentials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _number(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _cost(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _session_label(session_key: str) -> str:
    if "openclaw-weixin" in session_key:
        return "微信"
    if session_key.endswith(":main"):
        return "主会话"
    return "其他会话"


def _empty_usage(*, reason: str | None = None) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "session_count": 0,
        "model_response_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "sessions": [],
    }


def _usage_from_file(path: Path) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "model_response_count": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
    }
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                usage = (record.get("message") or {}).get("usage") if isinstance(record, dict) else None
                if not isinstance(usage, dict):
                    continue
                totals["model_response_count"] = int(totals["model_response_count"]) + 1
                totals["input_tokens"] = int(totals["input_tokens"]) + _number(usage.get("input"))
                totals["output_tokens"] = int(totals["output_tokens"]) + _number(usage.get("output"))
                totals["cache_read_tokens"] = int(totals["cache_read_tokens"]) + _number(usage.get("cacheRead"))
                totals["cache_write_tokens"] = int(totals["cache_write_tokens"]) + _number(usage.get("cacheWrite"))
                totals["total_tokens"] = int(totals["total_tokens"]) + _number(usage.get("totalTokens"))
                totals["estimated_cost_usd"] = float(totals["estimated_cost_usd"]) + _cost((usage.get("cost") or {}).get("total"))
    except OSError:
        return totals
    return totals


def get_openclaw_usage(sessions_dir: Path | None = None) -> dict[str, Any]:
    """Return cumulative usage for OpenClaw's currently indexed sessions.

    The session index contains only the current session file per conversation.
    We aggregate its usage metadata, never return any transcript fields, and
    intentionally omit authentication settings and session peer identifiers.
    """
    root = sessions_dir or (Path.home() / ".openclaw" / "agents" / "main" / "sessions")
    index_path = root / "sessions.json"
    try:
        raw_index = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_usage(reason="OpenClaw 尚未创建会话记录。")
    except (OSError, json.JSONDecodeError):
        return _empty_usage(reason="无法读取 OpenClaw 会话用量。")
    if not isinstance(raw_index, dict):
        return _empty_usage(reason="OpenClaw 会话索引格式无效。")

    result = _empty_usage()
    result["available"] = True
    for session_key, metadata in raw_index.items():
        if not isinstance(session_key, str) or not isinstance(metadata, dict):
            continue
        session_file = metadata.get("sessionFile")
        if not isinstance(session_file, str) or not session_file:
            continue
        usage = _usage_from_file(Path(session_file))
        session = {
            "label": _session_label(session_key),
            "provider": str(metadata.get("modelProvider") or ""),
            "model": str(metadata.get("model") or ""),
            **usage,
        }
        result["sessions"].append(session)
        result["session_count"] += 1
        for field in (
            "model_response_count",
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "total_tokens",
        ):
            result[field] += int(usage[field])
        result["estimated_cost_usd"] += float(usage["estimated_cost_usd"])
    return result
