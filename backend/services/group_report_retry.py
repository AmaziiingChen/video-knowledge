"""Transient-error policy for report source-summary requests."""

from __future__ import annotations


def is_retryable_summary_error(exc: Exception) -> bool:
    """Retry only transient transport, throttling, and upstream failures."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        normalized_status = int(status_code)
    except (TypeError, ValueError):
        normalized_status = None
    if normalized_status is not None:
        return normalized_status in {408, 429} or 500 <= normalized_status < 600
    if exc.__class__.__name__.lower() in {
        "apiconnectionerror",
        "apitimeouterror",
        "ratelimiterror",
        "internalservererror",
    }:
        return True
    message = (str(exc) or "").lower()
    return any(
        marker in message
        for marker in (
            "network error",
            "connection error",
            "connection reset",
            "connection refused",
            "temporarily unavailable",
            "timed out",
            "timeout",
            "rate limit",
        )
    )
