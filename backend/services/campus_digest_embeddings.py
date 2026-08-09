"""Embedding selection and deterministic fallback for campus event retrieval."""

from __future__ import annotations

from threading import Lock
from time import perf_counter
from typing import Any

import hashlib
import math

from config import settings
from services.ai_call_logger import record_ai_call
from services.campus_digest_identity import normalize_identity
from services.campus_digest_progress import DigestProgressCallback, emit_progress
from services.llm_provider import LLMResponse, LLMUsage
from services.llm_settings import campus_embedding_enabled


class CampusEventEmbedder:
    """Prefer a configured hosted embedding API, then a local model, then fallback."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._load_attempted = False
        self._lock = Lock()
        self.model_name = "hash-char-ngram-v1"

    def encode(
        self,
        texts: list[str],
        *,
        progress_callback: DigestProgressCallback | None = None,
        tracking_task_id: str | None = None,
    ) -> tuple[list[list[float]], str]:
        if not texts:
            return [], self.model_name
        if not campus_embedding_enabled():
            emit_progress(
                progress_callback,
                "report_embeddings",
                "语义向量功能目前暂停，已使用离线字符向量完成本次候选召回",
                42,
                level="warn",
            )
            return [hashed_embedding(text) for text in texts], self.model_name
        if settings.campus_embedding_api_key:
            try:
                vectors = self._encode_api(texts, tracking_task_id=tracking_task_id)
                model = embedding_cache_model_name()
                emit_progress(
                    progress_callback,
                    "report_embeddings",
                    f"已调用语义向量 API {settings.campus_embedding_api_model}",
                    42,
                )
                return vectors, model
            except Exception as exc:
                emit_progress(
                    progress_callback,
                    "report_embeddings",
                    f"语义向量 API 暂不可用，已改用本地/离线候选召回：{exc}",
                    42,
                    level="warn",
                )
        model = self._load_model(progress_callback=progress_callback)
        if model is None:
            emit_progress(
                progress_callback,
                "report_embeddings",
                "本机未缓存 Qwen3-Embedding-0.6B，已改用离线字符向量完成本次候选召回",
                42,
                level="warn",
            )
            return [hashed_embedding(text) for text in texts], self.model_name
        instruction = "判断两条深圳技术大学校园资讯是否描述同一具体事件、转载或同一事件的后续阶段。"
        values = model.encode(
            [f"任务：{instruction}\n文本：{text}" for text in texts],
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in row] for row in values], self.model_name

    def _encode_api(self, texts: list[str], *, tracking_task_id: str | None = None) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.campus_embedding_api_key,
            base_url=settings.campus_embedding_api_base_url,
            timeout=max(10.0, float(settings.llm_request_timeout_seconds)),
            max_retries=0,
        )
        vectors: list[list[float]] = []
        # text-embedding-v4 accepts up to ten texts per synchronous request.
        for start in range(0, len(texts), 10):
            batch = texts[start : start + 10]
            started_at = perf_counter()
            try:
                response = client.embeddings.create(
                    model=settings.campus_embedding_api_model,
                    input=batch,
                    dimensions=int(settings.campus_embedding_api_dimensions),
                    encoding_format="float",
                )
            except Exception as exc:
                if tracking_task_id:
                    record_ai_call(
                        call_type="campus_embedding",
                        provider_response=None,
                        input_chars=sum(len(text) for text in batch),
                        elapsed_seconds=perf_counter() - started_at,
                        task_id=tracking_task_id,
                        error=str(exc),
                    )
                raise
            if tracking_task_id:
                api_usage = getattr(response, "usage", None)
                prompt_tokens = getattr(api_usage, "prompt_tokens", None)
                total_tokens = getattr(api_usage, "total_tokens", None)
                if prompt_tokens is None and total_tokens is not None:
                    prompt_tokens = total_tokens
                completion_tokens = None
                if prompt_tokens is not None:
                    completion_tokens = 0 if total_tokens is None else max(0, int(total_tokens) - int(prompt_tokens))
                record_ai_call(
                    call_type="campus_embedding",
                    provider_response=LLMResponse(
                        content="",
                        provider="campus_embedding_api",
                        model=settings.campus_embedding_api_model,
                        usage=LLMUsage(
                            prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
                            completion_tokens=completion_tokens,
                            total_tokens=int(total_tokens) if total_tokens is not None else None,
                        ) if api_usage is not None else None,
                    ),
                    input_chars=sum(len(text) for text in batch),
                    elapsed_seconds=perf_counter() - started_at,
                    task_id=tracking_task_id,
                )
            rows = sorted(response.data, key=lambda item: item.index)
            if len(rows) != len(batch):
                raise ValueError("语义向量 API 返回数量与输入不一致")
            vectors.extend(normalize_vector([float(value) for value in item.embedding]) for item in rows)
        return vectors

    def _load_model(
        self,
        *,
        progress_callback: DigestProgressCallback | None = None,
    ) -> Any | None:
        if not campus_embedding_enabled():
            return None
        with self._lock:
            if self._load_attempted:
                return self._model
            self._load_attempted = True
            try:
                from sentence_transformers import SentenceTransformer

                # Report generation must never turn into an invisible model
                # download. Runtime/model management can populate the cache
                # explicitly; until then the deterministic fallback remains
                # available and is surfaced in the report log.
                self._model = SentenceTransformer(
                    settings.campus_embedding_model,
                    local_files_only=True,
                )
                self.model_name = settings.campus_embedding_model
                emit_progress(
                    progress_callback,
                    "report_embeddings",
                    f"已载入语义向量模型 {settings.campus_embedding_model}",
                    42,
                )
            except Exception:
                # Reports must remain available before the optional model has
                # downloaded or when the Mac is temporarily offline.
                self._model = None
                self.model_name = "hash-char-ngram-v1"
            return self._model


def embedding_cache_model_name() -> str:
    if campus_embedding_enabled() and settings.campus_embedding_api_key:
        return (
            f"api:{settings.campus_embedding_api_model}:"
            f"{int(settings.campus_embedding_api_dimensions)}"
        )
    return settings.campus_embedding_model if campus_embedding_enabled() else "hash-char-ngram-v1"


def normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right, strict=True))))


def hashed_embedding(text: str, dimensions: int = 384) -> list[float]:
    normalized = normalize_identity(text)
    vector = [0.0] * dimensions
    if not normalized:
        return vector
    for size in (2, 3, 4):
        for index in range(max(1, len(normalized) - size + 1)):
            token = normalized[index : index + size]
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
    return normalize_vector(vector)


campus_event_embedder = CampusEventEmbedder()
