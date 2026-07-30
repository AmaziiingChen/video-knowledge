"""Persistence for platform-specific creator work metadata."""
from __future__ import annotations

import json
from typing import Any

from services.database import utc_now_iso


def save_creator_work_metadata(
    connection,
    *,
    content_item_id: str,
    provider: str,
    creator_key: str,
    creator_name: str,
    creator_avatar_url: str,
    creator_description: str,
    collection_id: str,
    collection_name: str,
    work_description: str,
    author_name: str,
    tags: list[str],
    stats: dict[str, int],
) -> None:
    """Upsert normalized, bounded metadata from an untrusted platform payload."""
    clean_tags = [str(tag).strip()[:120] for tag in tags if str(tag).strip()][:40]
    clean_stats = {
        str(key)[:40]: parsed
        for key, value in stats.items()
        if str(key).strip() and (parsed := _integer(value)) is not None
    }
    connection.execute(
        """
        INSERT INTO creator_work_metadata (
            content_item_id, provider, creator_key, creator_name, creator_avatar_url,
            creator_description, collection_id, collection_name, work_description,
            author_name, tags_json, stats_json, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(content_item_id) DO UPDATE SET
            creator_name=excluded.creator_name,
            creator_avatar_url=excluded.creator_avatar_url,
            creator_description=excluded.creator_description,
            collection_id=excluded.collection_id,
            collection_name=excluded.collection_name,
            work_description=excluded.work_description,
            author_name=excluded.author_name,
            tags_json=excluded.tags_json,
            stats_json=excluded.stats_json,
            captured_at=excluded.captured_at
        """,
        (
            content_item_id, provider[:32], creator_key[:256], creator_name[:500], creator_avatar_url[:2000],
            creator_description[:4000], collection_id[:256], collection_name[:500], work_description[:8000],
            author_name[:500], json.dumps(clean_tags, ensure_ascii=False),
            json.dumps(clean_stats, ensure_ascii=False, sort_keys=True), utc_now_iso(),
        ),
    )


def _integer(value: Any) -> int | None:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
