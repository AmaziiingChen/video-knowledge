from __future__ import annotations

import json
from types import SimpleNamespace

from services import campus_digest_fact_cache as cache


def test_load_cached_facts_uses_bound_ids_and_skips_stale_or_invalid_cards(monkeypatch):
    captured: dict[str, object] = {}
    content_id = "item' OR 1=1 --"

    class FakeDatabase:
        def execute(self, query, params):
            captured["query"] = query
            captured["params"] = params
            return self

        def fetchall(self):
            return [
                {"content_item_id": content_id, "source_hash": "current", "fact_json": json.dumps({"summary": "ok"})},
                {"content_item_id": "stale", "source_hash": "old", "fact_json": json.dumps({"summary": "old"})},
                {"content_item_id": "broken", "source_hash": "current", "fact_json": "{"},
            ]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(cache, "initialize_database", lambda: None)
    monkeypatch.setattr(cache, "connect", lambda: FakeDatabase())

    result = cache.load_cached_facts(
        [SimpleNamespace(content_item_id=content_id)],
        {content_id: "current", "stale": "current", "broken": "current"},
        "model",
        prompt_version="v1",
        parse_card=lambda value: value,
    )

    assert result == {content_id: {"summary": "ok"}}
    assert content_id not in captured["query"]
    assert captured["params"] == (content_id, "v1", "model")


def test_save_fact_cards_serializes_projection_and_invalidates_embedding(monkeypatch):
    captured: dict[str, object] = {}
    source = SimpleNamespace(content_item_id="item-1")

    class FakeDatabase:
        def executemany(self, query, payload):
            captured["query"] = query
            captured["payload"] = payload

        def commit(self):
            captured["committed"] = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(cache, "connect", lambda: FakeDatabase())
    monkeypatch.setattr(cache, "utc_now_iso", lambda: "2026-08-10T00:00:00+00:00")

    cache.save_fact_cards(
        [(source, {"content_decision": "include", "decision_reason": "可核验"}, "model")],
        {"item-1": "hash"},
        prompt_version="v1",
    )

    assert "embedding_model='', embedding_json='[]'" in captured["query"]
    assert captured["payload"] == [(
        "item-1", "hash", "v1", "model", '{"content_decision":"include","decision_reason":"可核验"}',
        "include", "可核验", "2026-08-10T00:00:00+00:00", "2026-08-10T00:00:00+00:00",
    )]
    assert captured["committed"] is True
