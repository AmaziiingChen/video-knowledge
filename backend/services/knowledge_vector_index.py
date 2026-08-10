"""Process-local dense-vector index for scoped knowledge retrieval."""
from __future__ import annotations

import json
from threading import Lock

from config import settings

from services.database import connect


_VECTOR_CACHE_LOCK = Lock()
_VECTOR_CACHE: dict[str, object] = {}


def invalidate_vector_cache() -> None:
    with _VECTOR_CACHE_LOCK:
        _VECTOR_CACHE.clear()


def dense_ranks(query_vector: list[float], scoped_rows: list[dict[str, object]], limit: int) -> dict[str, int]:
    """Rank only the already scope-filtered rows against the cached corpus."""
    import numpy as np

    index = global_vector_index()
    positions = [index["positions"].get(str(row["id"])) for row in scoped_rows]
    positions = [position for position in positions if position is not None]
    if not positions:
        return {}
    vectors = index["vectors"][positions]
    scores = vectors @ np.asarray(query_vector, dtype=np.float32)
    count = min(max(1, limit), len(positions))
    selected = np.argsort(scores)[::-1][:count]
    return {str(index["ids"][positions[int(relative_index)]]): rank for rank, relative_index in enumerate(selected, 1)}


def global_vector_index() -> dict[str, object]:
    """Load the one current-model vector corpus once per process revision."""
    import numpy as np

    model = settings.campus_embedding_api_model
    dimensions = int(settings.campus_embedding_api_dimensions)
    with connect() as db:
        marker = db.execute(
            """SELECT COUNT(*) AS count, COALESCE(MAX(updated_at),'') AS latest
               FROM knowledge_v2_embeddings
               WHERE embedding_model=? AND dimensions=?""",
            (model, dimensions),
        ).fetchone()
    signature = (model, dimensions, int(marker["count"] or 0), str(marker["latest"] or ""))
    with _VECTOR_CACHE_LOCK:
        if _VECTOR_CACHE.get("signature") == signature:
            return _VECTOR_CACHE
    with connect() as db:
        rows = db.execute(
            """SELECT embedding.chunk_id,embedding.vector_json
               FROM knowledge_v2_embeddings AS embedding
               JOIN knowledge_v2_chunks AS chunk ON chunk.id=embedding.chunk_id
               WHERE embedding.embedding_model=? AND embedding.dimensions=? AND chunk.chunk_kind='child'
               ORDER BY embedding.chunk_id""",
            (model, dimensions),
        ).fetchall()
    ids: list[str] = []
    vectors: list[list[float]] = []
    for row in rows:
        try:
            vector = [float(value) for value in json.loads(row["vector_json"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if len(vector) != dimensions:
            continue
        ids.append(str(row["chunk_id"]))
        vectors.append(vector)
    matrix = np.asarray(vectors, dtype=np.float32) if vectors else np.empty((0, dimensions), dtype=np.float32)
    index: dict[str, object] = {"signature": signature, "ids": ids, "positions": {chunk_id: position for position, chunk_id in enumerate(ids)}, "vectors": matrix}
    with _VECTOR_CACHE_LOCK:
        _VECTOR_CACHE.clear()
        _VECTOR_CACHE.update(index)
        return _VECTOR_CACHE
