"""Durable cache for generic group-report source summaries."""

from __future__ import annotations

import hashlib

from services.database import connect, ensure_database_initialized, utc_now_iso
from services.group_report_models import GroupReportSource


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_hash(source: GroupReportSource) -> str:
    return _sha256(source.material)


def load_cached_summaries(
    sources: list[GroupReportSource], prompt_hash: str, model: str | None = None
) -> dict[str, str]:
    """Load by source content and generic prompt identity; model is metadata only."""
    del model
    ensure_database_initialized()
    by_item = {source.content_item_id: source for source in sources if source.content_item_id}
    if not by_item:
        return {}
    placeholders = ",".join("?" for _ in by_item)
    with connect() as connection:
        rows = connection.execute(
            f"""SELECT content_item_id, source_hash, summary
                FROM group_report_source_summaries
                WHERE prompt_hash=? AND content_item_id IN ({placeholders})
                ORDER BY updated_at DESC""",
            (prompt_hash, *by_item),
        ).fetchall()
    result: dict[str, str] = {}
    for row in rows:
        source = by_item.get(str(row["content_item_id"]))
        if source and source.citation_id not in result and str(row["source_hash"]) == _source_hash(source):
            result[source.citation_id] = str(row["summary"])
    return result


def store_cached_summaries(
    sources: list[GroupReportSource], summaries: dict[str, str], prompt_hash: str, model: str
) -> None:
    now = utc_now_iso()
    rows = [
        (source.content_item_id, _source_hash(source), prompt_hash, model, summaries[source.citation_id], now, now)
        for source in sources
        if source.content_item_id and source.citation_id in summaries
    ]
    if not rows:
        return
    with connect() as connection:
        # Keep historical prompt revisions for auditability. Cache lookup is
        # independent of model choice, while the model column records which
        # provider produced this particular summary.
        connection.executemany(
            """INSERT INTO group_report_source_summaries
               (content_item_id, source_hash, prompt_hash, model, summary, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(content_item_id, prompt_hash, model) DO UPDATE SET
                 source_hash=excluded.source_hash, summary=excluded.summary, updated_at=excluded.updated_at""",
            rows,
        )
        connection.commit()
