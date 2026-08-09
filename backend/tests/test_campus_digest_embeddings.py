from __future__ import annotations

import math

from services import campus_digest_embeddings as embeddings
from services import campus_digest_progress as progress


def test_disabled_embeddings_use_the_deterministic_local_fallback(monkeypatch):
    monkeypatch.setattr(embeddings, "campus_embedding_enabled", lambda: False)
    events: list[dict[str, object]] = []

    vectors, model = embeddings.CampusEventEmbedder().encode(
        ["校园文化节"],
        progress_callback=events.append,
    )

    assert model == "hash-char-ngram-v1"
    assert vectors == [embeddings.hashed_embedding("校园文化节")]
    assert math.isclose(sum(value * value for value in vectors[0]), 1.0)
    assert events == [{
        "stage": "report_embeddings",
        "message": "语义向量功能目前暂停，已使用离线字符向量完成本次候选召回",
        "progress": 42.0,
        "level": "warn",
    }]


def test_progress_and_similarity_keep_their_bounded_public_contract():
    events: list[dict[str, object]] = []
    progress.emit_progress(events.append, "report_embeddings", "已完成", 120, output_chars=7)

    assert events == [{
        "stage": "report_embeddings",
        "message": "已完成",
        "progress": 100.0,
        "level": "info",
        "output_chars": 7,
    }]
    assert embeddings.cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert embeddings.cosine_similarity([1.0], [1.0, 0.0]) == 0.0
