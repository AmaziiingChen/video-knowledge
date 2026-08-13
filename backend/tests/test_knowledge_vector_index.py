import numpy as np

from services import knowledge_v2
from services import knowledge_vector_index as vector_index


def test_dense_ranks_only_considers_scope_rows_and_keeps_score_order(monkeypatch):
    monkeypatch.setattr(
        vector_index,
        "global_vector_index",
        lambda: {
            "ids": ["chunk-a", "chunk-b", "outside-scope"],
            "positions": {"chunk-a": 0, "chunk-b": 1, "outside-scope": 2},
            "vectors": np.asarray([[0.2, 0.8], [0.9, 0.1], [1.0, 0.0]], dtype=np.float32),
        },
    )

    ranks = vector_index.dense_ranks([1.0, 0.0], [{"id": "chunk-a"}, {"id": "chunk-b"}], limit=2)

    assert ranks == {"chunk-b": 1, "chunk-a": 2}
    assert "outside-scope" not in ranks


def test_invalidate_vector_cache_clears_only_the_process_local_index():
    vector_index._VECTOR_CACHE.update({"signature": ("model", 1, 1, "now"), "ids": ["chunk"]})

    vector_index.invalidate_vector_cache()

    assert vector_index._VECTOR_CACHE == {}


def test_knowledge_v2_keeps_vector_cache_invalidator_compatibility_entry():
    assert knowledge_v2.invalidate_vector_cache is vector_index.invalidate_vector_cache
