"""Durable, token-independent history for hosted image OCR requests."""

from __future__ import annotations

import sqlite3

from services.database import connect, initialize_database, utc_now_iso
from services.repository import new_id


def record_ocr_call(
    *,
    content_item_id: str | None,
    image_url: str,
    image_bytes: int,
    model: str,
    status: str,
    cloud_submitted: bool,
    retry_count: int,
    elapsed_seconds: float,
    error: str = "",
) -> None:
    """Persist one OCR attempt without affecting LLM Token accounting."""
    try:
        initialize_database()
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO ocr_calls (
                    id, content_item_id, image_url, image_bytes, model, status,
                    cloud_submitted, retry_count, elapsed_seconds, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    content_item_id,
                    image_url[:2000],
                    max(0, image_bytes),
                    model,
                    status,
                    int(cloud_submitted),
                    max(0, retry_count),
                    round(max(0.0, elapsed_seconds), 3),
                    error[:500],
                    utc_now_iso(),
                ),
            )
            connection.commit()
    except sqlite3.Error:
        # Observability must never make article capture or OCR unavailable.
        return
