"""Cloud embedding transport and persistence for the V2 knowledge index."""
from __future__ import annotations

import json
import math
from time import perf_counter

from config import settings

from services.ai_call_logger import record_ai_call
from services.database import connect, utc_now_iso
from services.llm_provider import LLMResponse, LLMUsage


EMBEDDING_REQUEST_TIMEOUT_SECONDS = 45.0


def embedding_text(row) -> str:
    """Build the stable, source-visible text sent to the embedding provider."""
    return f"标题：{row['title'] or '未命名内容'}\n章节：{row['heading_path'] or '正文'}\n内容：{row['text']}"


def embed(texts: list[str]) -> list[list[float]]:
    """Request normalized embeddings and retain the existing local call audit."""
    from openai import OpenAI

    timeout = max(10.0, min(EMBEDDING_REQUEST_TIMEOUT_SECONDS, float(settings.llm_request_timeout_seconds)))
    client = OpenAI(api_key=settings.campus_embedding_api_key, base_url=settings.campus_embedding_api_base_url, timeout=timeout, max_retries=0)
    started = perf_counter()
    try:
        response = client.embeddings.create(
            model=settings.campus_embedding_api_model,
            input=texts,
            dimensions=int(settings.campus_embedding_api_dimensions),
            encoding_format="float",
        )
    except Exception as exc:
        record_ai_call(call_type="knowledge_v2_embedding", provider_response=None, input_chars=sum(map(len, texts)), elapsed_seconds=perf_counter() - started, error=str(exc))
        raise RuntimeError(f"Embedding API 调用失败: {exc}") from exc
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    record_ai_call(
        call_type="knowledge_v2_embedding",
        provider_response=LLMResponse(content="", provider="qwen_embedding", model=settings.campus_embedding_api_model, usage=LLMUsage(prompt_tokens=int(prompt_tokens), completion_tokens=0, total_tokens=int(total_tokens or prompt_tokens)) if prompt_tokens is not None else None),
        input_chars=sum(map(len, texts)),
        elapsed_seconds=perf_counter() - started,
    )
    rows = sorted(response.data, key=lambda item: item.index)
    if len(rows) != len(texts):
        raise ValueError("Embedding API 返回数量与输入不一致")
    return [normalize([float(value) for value in row.embedding]) for row in rows]


def save_embedding_batch(rows, vectors: list[list[float]]) -> None:
    """Persist only vectors whose indexed source has not changed in transit."""
    now = utc_now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for row, vector in zip(rows, vectors, strict=True):
            current = db.execute("SELECT source_hash FROM knowledge_v2_chunks WHERE id=?", (row["id"],)).fetchone()
            if not current or current["source_hash"] != row["source_hash"]:
                continue
            db.execute(
                """INSERT INTO knowledge_v2_embeddings
                   (chunk_id,embedding_model,dimensions,vector_json,source_hash,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(chunk_id) DO UPDATE SET
                     embedding_model=excluded.embedding_model, dimensions=excluded.dimensions,
                     vector_json=excluded.vector_json, source_hash=excluded.source_hash,
                     updated_at=excluded.updated_at""",
                (row["id"], settings.campus_embedding_api_model, len(vector), json.dumps(vector, separators=(",", ":")), row["source_hash"], now, now),
            )
        db.commit()


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
