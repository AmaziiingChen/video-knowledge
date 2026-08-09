"""Pure timing, progress and log-level rules for pipeline updates."""

from __future__ import annotations

import time


def elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 2)


def clamp_percent(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 1)))


def level_from_message(message: str) -> str:
    if any(token in message for token in ["失败", "错误", "异常", "ERROR"]):
        return "error"
    if any(token in message for token in ["警告", "注意", "WARNING"]):
        return "warn"
    if any(token in message for token in ["完成", "成功"]):
        return "success"
    return "info"
