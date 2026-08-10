"""SQLite persistence for cached campus-digest fact cards."""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from services.database import connect, initialize_database, utc_now_iso


FactCardParser = Callable[[str | dict[str, Any]], dict[str, Any]]


def load_cached_facts(
    sources: Iterable[object],
    hashes: dict[str, str],
    model: str,
    *,
    prompt_version: str,
    parse_card: FactCardParser,
) -> dict[str, dict[str, Any]]:
    """Return only hash- and schema-valid cards for the requested model."""
    ids = [str(source.content_item_id) for source in sources]
    if not ids:
        return {}
    initialize_database()
    placeholders = ",".join("?" for _ in ids)
    with connect() as connection:
        rows = connection.execute(
            f"""SELECT content_item_id, source_hash, fact_json
                FROM campus_report_facts
                WHERE content_item_id IN ({placeholders}) AND prompt_version=? AND model=?""",
            (*ids, prompt_version, model),
        ).fetchall()
    cached: dict[str, dict[str, Any]] = {}
    for row in rows:
        content_id = str(row["content_item_id"])
        if str(row["source_hash"]) != hashes.get(content_id):
            continue
        try:
            cached[content_id] = parse_card(json.loads(str(row["fact_json"])))
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return cached


def save_fact_cards(
    records: Iterable[tuple[object, dict[str, Any], str]],
    hashes: dict[str, str],
    *,
    prompt_version: str,
) -> None:
    """Atomically replace fact-card projections and invalidate stale embeddings."""
    now = utc_now_iso()
    payload = [
        (
            source.content_item_id,
            hashes[source.content_item_id],
            prompt_version,
            model,
            json.dumps(card, ensure_ascii=False, separators=(",", ":")),
            card["content_decision"],
            card["decision_reason"],
            now,
            now,
        )
        for source, card, model in records
    ]
    with connect() as connection:
        connection.executemany(
            """INSERT INTO campus_report_facts
               (content_item_id, source_hash, prompt_version, model, fact_json,
                filter_status, filter_reason, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(content_item_id) DO UPDATE SET
                 source_hash=excluded.source_hash,
                 prompt_version=excluded.prompt_version,
                 model=excluded.model,
                 fact_json=excluded.fact_json,
                 filter_status=excluded.filter_status,
                 filter_reason=excluded.filter_reason,
                 embedding_model='', embedding_json='[]', updated_at=excluded.updated_at""",
            payload,
        )
        connection.commit()
