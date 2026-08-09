"""Stable progress-event contract for the campus report pipeline."""

from __future__ import annotations

from collections.abc import Callable


DigestProgressCallback = Callable[[dict[str, object]], None]


def emit_progress(
    callback: DigestProgressCallback | None,
    stage: str,
    message: str,
    progress: float,
    *,
    level: str = "info",
    elapsed_seconds: float | None = None,
    model: str | None = None,
    output_chars: int | None = None,
) -> None:
    if callback is None:
        return
    event: dict[str, object] = {
        "stage": stage,
        "message": message,
        "progress": max(0.0, min(100.0, float(progress))),
        "level": level,
    }
    if elapsed_seconds is not None:
        event["elapsed_seconds"] = round(float(elapsed_seconds), 3)
    if model:
        event["model"] = model
    if output_chars is not None:
        event["output_chars"] = int(output_chars)
    callback(event)
