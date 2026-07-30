from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from time import perf_counter
from zoneinfo import ZoneInfo

from config import settings
from services.database import connect, ensure_database_initialized, utc_now_iso
from services.llm_provider import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    ResponseFormat,
)
from services.repository import new_id


_BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _is_deepseek_peak_pricing_time(value: str | None = None) -> bool:
    """Whether an instant falls in DeepSeek's published Beijing peak window."""
    try:
        instant = datetime.fromisoformat(value) if value else datetime.now(timezone.utc)
    except (TypeError, ValueError):
        instant = datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local = instant.astimezone(_BEIJING_TIMEZONE)
    return 9 <= local.hour < 12 or 14 <= local.hour < 18


@dataclass(frozen=True)
class AICallRecord:
    call_type: str
    provider: str
    model: str
    input_chars: int
    output_chars: int
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    prompt_cache_hit_tokens: int | None
    prompt_cache_miss_tokens: int | None
    estimated_cost: float | None
    elapsed_seconds: float
    finish_reason: str | None = None


@dataclass(frozen=True)
class ImageGenerationCallRecord:
    call_type: str
    provider: str
    model: str
    image_count: int
    unit_price_cny: float | None
    estimated_cost: float | None
    billing_region: str
    request_id: str | None
    image_width: int | None
    image_height: int | None
    elapsed_seconds: float


class TrackedLLMProvider:
    """Record every call made through a provider without changing report code."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        call_type: str,
        task_id: str | None = None,
        content_item_id: str | None = None,
        callback: Callable[[AICallRecord], None] | None = None,
    ) -> None:
        self._provider = provider
        self.name = provider.name
        self.model = provider.model
        self.thinking_type = getattr(provider, "thinking_type", "enabled")
        self.call_type = call_type
        self.task_id = task_id
        self.content_item_id = content_item_id
        self.callback = callback

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        started_at = perf_counter()
        billed_at = utc_now_iso()
        input_chars = sum(len(message.content) for message in messages)
        try:
            if response_format is None and max_tokens is None:
                response = self._provider.chat(messages, temperature=temperature)
            else:
                try:
                    response = self._provider.chat(
                        messages,
                        temperature=temperature,
                        response_format=response_format,
                        max_tokens=max_tokens,
                    )
                except TypeError:
                    response = self._provider.chat(messages, temperature=temperature)
        except Exception as exc:
            self._record(
                None,
                input_chars=input_chars,
                elapsed_seconds=perf_counter() - started_at,
                error=str(exc),
                billed_at=billed_at,
            )
            raise
        self._record(
            response,
            input_chars=input_chars,
            output_chars=len(response.content),
            elapsed_seconds=perf_counter() - started_at,
            billed_at=billed_at,
        )
        return response

    def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        on_usage: Callable[[LLMUsage], None] | None = None,
    ) -> Iterator[str]:
        started_at = perf_counter()
        billed_at = utc_now_iso()
        input_chars = sum(len(message.content) for message in messages)
        chunks: list[str] = []
        usage: LLMUsage | None = None

        def remember_usage(value: LLMUsage) -> None:
            nonlocal usage
            usage = value
            if on_usage:
                on_usage(value)

        try:
            for chunk in self._provider.chat_stream(
                messages,
                temperature=temperature,
                on_usage=remember_usage,
            ):
                chunks.append(chunk)
                yield chunk
        except Exception as exc:
            self._record(
                None,
                input_chars=input_chars,
                elapsed_seconds=perf_counter() - started_at,
                error=str(exc),
                billed_at=billed_at,
            )
            raise
        response = LLMResponse(
            content="".join(chunks),
            provider=self.name,
            model=self.model,
            usage=usage,
        )
        self._record(
            response,
            input_chars=input_chars,
            output_chars=len(response.content),
            elapsed_seconds=perf_counter() - started_at,
            billed_at=billed_at,
        )

    def chat_stream_events(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        response_format: ResponseFormat = None,
        max_tokens: int | None = None,
    ) -> Iterator[LLMStreamChunk]:
        started_at = perf_counter()
        billed_at = utc_now_iso()
        input_chars = sum(len(message.content) for message in messages)
        content_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        usage: LLMUsage | None = None
        finish_reason: str | None = None

        try:
            event_stream = getattr(self._provider, "chat_stream_events", None)
            if callable(event_stream):
                events = event_stream(
                    messages,
                    temperature=temperature,
                    response_format=response_format,
                    max_tokens=max_tokens,
                )
            else:
                try:
                    response = self._provider.chat(
                        messages,
                        temperature=temperature,
                        response_format=response_format,
                        max_tokens=max_tokens,
                    )
                except TypeError:
                    response = self._provider.chat(
                        messages,
                        temperature=temperature,
                    )
                events = iter([
                    LLMStreamChunk(
                        content=response.content,
                        reasoning_content=response.reasoning_content,
                        usage=response.usage,
                        finish_reason=response.finish_reason,
                    )
                ])
            for chunk in events:
                if chunk.content:
                    content_chunks.append(chunk.content)
                if chunk.reasoning_content:
                    reasoning_chunks.append(chunk.reasoning_content)
                if chunk.usage:
                    usage = chunk.usage
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                yield chunk
        except Exception as exc:
            self._record(
                None,
                input_chars=input_chars,
                elapsed_seconds=perf_counter() - started_at,
                error=str(exc),
                billed_at=billed_at,
            )
            raise
        response = LLMResponse(
            content="".join(content_chunks),
            provider=self.name,
            model=self.model,
            usage=usage,
            finish_reason=finish_reason,
            reasoning_content="".join(reasoning_chunks),
        )
        self._record(
            response,
            input_chars=input_chars,
            output_chars=len(response.content) + len(response.reasoning_content),
            elapsed_seconds=perf_counter() - started_at,
            billed_at=billed_at,
        )

    def _record(
        self,
        response: LLMResponse | None,
        *,
        input_chars: int,
        elapsed_seconds: float,
        output_chars: int = 0,
        error: str | None = None,
        billed_at: str | None = None,
    ) -> None:
        record = record_ai_call(
            call_type=self.call_type,
            provider_response=response,
            input_chars=input_chars,
            output_chars=output_chars,
            elapsed_seconds=elapsed_seconds,
            task_id=self.task_id,
            content_item_id=self.content_item_id,
            error=error,
            billed_at=billed_at,
        )
        if record and self.callback:
            self.callback(record)


def tracked_llm_provider(
    provider: LLMProvider,
    *,
    call_type: str,
    task_id: str | None = None,
    content_item_id: str | None = None,
    callback: Callable[[AICallRecord], None] | None = None,
) -> LLMProvider:
    if isinstance(provider, TrackedLLMProvider):
        if (
            provider.call_type == call_type
            and provider.task_id == task_id
            and provider.content_item_id == content_item_id
        ):
            return provider
    return TrackedLLMProvider(
        provider,
        call_type=call_type,
        task_id=task_id,
        content_item_id=content_item_id,
        callback=callback,
    )


def attach_ai_calls_to_content(task_id: str, content_item_id: str) -> None:
    if not task_id or not content_item_id:
        return
    ensure_database_initialized()
    with connect() as connection:
        connection.execute(
            "UPDATE ai_calls SET content_item_id=? WHERE task_id=? AND content_item_id IS NULL",
            (content_item_id, task_id),
        )
        connection.commit()


def ai_call_usage_for_task(task_id: str) -> dict[str, int]:
    usage = ai_call_usage_detail_for_task(task_id)
    return {
        "call_count": usage["call_count"],
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": usage["completion_tokens"],
        "total_tokens": usage["total_tokens"],
        "unreported_count": usage["unreported_count"],
    }


def ai_call_usage_detail_for_task(task_id: str) -> dict[str, int | float]:
    """Return a complete, persisted token-cost summary for one logical task.

    Knowledge-library conversations use their conversation ID as ``task_id`` so
    their query rewrite, answer, and repair calls can be presented as one cost
    without adding another persistence table.
    """
    if not task_id:
        return {
            "call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "estimated_cost": 0.0,
            "unreported_count": 0,
        }
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(prompt_cache_hit_tokens), 0) AS prompt_cache_hit_tokens,
                   COALESCE(SUM(prompt_cache_miss_tokens), 0) AS prompt_cache_miss_tokens,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   SUM(CASE WHEN prompt_tokens IS NULL OR completion_tokens IS NULL THEN 1 ELSE 0 END) AS unreported_count
            FROM ai_calls
            WHERE task_id=? AND error IS NULL AND usage_unit='tokens'
            """,
            (task_id,),
        ).fetchone()
    prompt_tokens = int(row["prompt_tokens"] or 0)
    completion_tokens = int(row["completion_tokens"] or 0)
    return {
        "call_count": int(row["call_count"] or 0),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_cache_hit_tokens": int(row["prompt_cache_hit_tokens"] or 0),
        "prompt_cache_miss_tokens": int(row["prompt_cache_miss_tokens"] or 0),
        "estimated_cost": float(row["estimated_cost"] or 0),
        "unreported_count": int(row["unreported_count"] or 0),
    }


def estimate_cost(
    prompt_tokens: int | None,
    completion_tokens: int | None,
    *,
    provider: str = "",
    model: str = "",
    prompt_cache_hit_tokens: int | None = None,
    prompt_cache_miss_tokens: int | None = None,
    billed_at: str | None = None,
) -> float | None:
    """Estimate cost from API-reported usage using the applicable rate card.

    A cache hit is dramatically cheaper than a cache miss. If an upstream
    compatible API omits the cache split, bill the unknown prompt portion at
    the cache-miss rate rather than pretending it was a hit.
    """
    price_card = settings.deepseek_pricing.get(model) if provider == "deepseek" else None
    if isinstance(price_card, dict):
        try:
            hit_price = max(0.0, float(price_card.get("input_cache_hit", 0)))
            miss_price = max(0.0, float(price_card.get("input_cache_miss", 0)))
            output_price = max(0.0, float(price_card.get("output", 0)))
        except (TypeError, ValueError):
            price_card = None
        else:
            prompt = max(0, int(prompt_tokens or 0))
            cache_hit = min(prompt, max(0, int(prompt_cache_hit_tokens or 0)))
            # Missing or incomplete cache detail is treated as uncached so the
            # displayed number remains a conservative estimate.
            cache_miss = max(0, int(prompt_cache_miss_tokens or 0), prompt - cache_hit)
            cost = (
                (cache_hit / 1_000_000 * hit_price)
                + (cache_miss / 1_000_000 * miss_price)
                + (max(0, int(completion_tokens or 0)) / 1_000_000 * output_price)
            )
            if _is_deepseek_peak_pricing_time(billed_at):
                cost *= max(0.0, float(settings.deepseek_peak_pricing_multiplier or 0))
            return round(cost, 8)

    # Compatibility fallback for existing environment configuration and
    # generic OpenAI-compatible providers which do not have a price card.
    input_price = float(settings.llm_input_cost_per_million_tokens or 0)
    output_price = float(settings.llm_output_cost_per_million_tokens or 0)
    if input_price <= 0 and output_price <= 0:
        return None
    cost = ((prompt_tokens or 0) / 1_000_000 * input_price) + (
        (completion_tokens or 0) / 1_000_000 * output_price
    )
    return round(cost, 8)


def backfill_missing_deepseek_costs() -> int:
    """Price legacy DeepSeek records that predate the cache-aware rate card.

    Existing non-null values are intentionally immutable: they are snapshots
    made under the rate card that was active at the time of that call.
    """
    ensure_database_initialized()
    updated = 0
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, provider, model, prompt_tokens, completion_tokens,
                   prompt_cache_hit_tokens, prompt_cache_miss_tokens, created_at
            FROM ai_calls
            WHERE provider='deepseek' AND estimated_cost IS NULL AND error IS NULL
            """
        ).fetchall()
        for row in rows:
            estimated_cost = estimate_cost(
                row["prompt_tokens"],
                row["completion_tokens"],
                provider=str(row["provider"] or ""),
                model=str(row["model"] or ""),
                prompt_cache_hit_tokens=row["prompt_cache_hit_tokens"],
                prompt_cache_miss_tokens=row["prompt_cache_miss_tokens"],
                billed_at=row["created_at"],
            )
            if estimated_cost is None:
                continue
            connection.execute("UPDATE ai_calls SET estimated_cost=? WHERE id=?", (estimated_cost, row["id"]))
            updated += 1
        connection.commit()
    return updated


def record_ai_call(
    *,
    call_type: str,
    provider_response: LLMResponse | None,
    input_chars: int,
    output_chars: int = 0,
    elapsed_seconds: float,
    task_id: str | None = None,
    content_item_id: str | None = None,
    series_id: str | None = None,
    error: str | None = None,
    billed_at: str | None = None,
) -> AICallRecord | None:
    usage = provider_response.usage if provider_response else None
    prompt_tokens = usage.prompt_tokens if usage else None
    completion_tokens = usage.completion_tokens if usage else None
    total_tokens = usage.total_tokens if usage else None
    prompt_cache_hit_tokens = usage.prompt_cache_hit_tokens if usage else None
    prompt_cache_miss_tokens = usage.prompt_cache_miss_tokens if usage else None
    provider = provider_response.provider if provider_response else "unknown"
    model = provider_response.model if provider_response else "unknown"
    created_at = utc_now_iso()
    estimated_cost = estimate_cost(
        prompt_tokens,
        completion_tokens,
        provider=provider,
        model=model,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
        billed_at=billed_at or created_at,
    )
    record = AICallRecord(
        call_type=call_type,
        provider=provider,
        model=model,
        input_chars=input_chars,
        output_chars=output_chars,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
        estimated_cost=estimated_cost,
        elapsed_seconds=round(elapsed_seconds, 2),
        finish_reason=provider_response.finish_reason if provider_response else None,
    )

    try:
        ensure_database_initialized()
        with connect() as connection:
            _insert_ai_call(
                connection,
                call_type=call_type,
                provider=provider,
                model=model,
                input_chars=input_chars,
                output_chars=output_chars,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                prompt_cache_hit_tokens=prompt_cache_hit_tokens,
                prompt_cache_miss_tokens=prompt_cache_miss_tokens,
                estimated_cost=estimated_cost,
                elapsed_seconds=record.elapsed_seconds,
                task_id=task_id,
                content_item_id=content_item_id,
                series_id=series_id,
                error=error,
                finish_reason=record.finish_reason,
                created_at=created_at,
            )
            connection.commit()
    except Exception:
        return record
    return record


def image_catalog_price(
    *,
    model: str,
    endpoint: str,
) -> tuple[str, float | None]:
    """Return the public Qwen Image list price used for a local estimate."""
    normalized_model = str(model or "").strip().lower()
    normalized_endpoint = str(endpoint or "").strip().lower()
    international = "intl" in normalized_endpoint or "ap-southeast" in normalized_endpoint
    region = "international" if international else "cn-mainland"
    if normalized_model.startswith("qwen-image-2.0-pro"):
        return region, 0.550443 if international else 0.5
    if normalized_model.startswith("qwen-image-2.0"):
        return region, 0.256873 if international else 0.2
    return region, None


def record_image_generation_call(
    *,
    call_type: str,
    provider: str,
    model: str,
    endpoint: str,
    image_count: int,
    input_chars: int,
    elapsed_seconds: float,
    task_id: str | None = None,
    content_item_id: str | None = None,
    request_id: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    created_at: str | None = None,
) -> ImageGenerationCallRecord:
    bounded_count = max(1, int(image_count or 1))
    billing_region, unit_price_cny = image_catalog_price(model=model, endpoint=endpoint)
    estimated_cost = unit_price_cny * bounded_count if unit_price_cny is not None else None
    record = ImageGenerationCallRecord(
        call_type=call_type,
        provider=provider,
        model=model,
        image_count=bounded_count,
        unit_price_cny=unit_price_cny,
        estimated_cost=estimated_cost,
        billing_region=billing_region,
        request_id=str(request_id or "").strip() or None,
        image_width=image_width,
        image_height=image_height,
        elapsed_seconds=round(elapsed_seconds, 2),
    )
    try:
        ensure_database_initialized()
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_calls (
                    id, task_id, content_item_id, call_type, provider, model,
                    input_chars, output_chars, prompt_tokens, completion_tokens,
                    estimated_cost, elapsed_seconds, error, created_at,
                    usage_unit, image_count, unit_price_cny, billing_region,
                    request_id, image_width, image_height
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, ?, NULL, ?,
                          'images', ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    task_id,
                    content_item_id,
                    call_type,
                    provider,
                    model,
                    max(0, int(input_chars or 0)),
                    estimated_cost,
                    record.elapsed_seconds,
                    created_at or utc_now_iso(),
                    bounded_count,
                    unit_price_cny,
                    billing_region,
                    record.request_id,
                    image_width,
                    image_height,
                ),
            )
            connection.commit()
    except Exception:
        # Usage recording must never turn a successfully billed provider call
        # into a failed cover task.
        pass
    return record


def _insert_ai_call(
    connection: sqlite3.Connection,
    *,
    call_type: str,
    provider: str,
    model: str,
    input_chars: int,
    output_chars: int,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    prompt_cache_hit_tokens: int | None,
    prompt_cache_miss_tokens: int | None,
    estimated_cost: float | None,
    elapsed_seconds: float,
    task_id: str | None,
    content_item_id: str | None,
    series_id: str | None,
    error: str | None,
    finish_reason: str | None,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO ai_calls (
            id, task_id, content_item_id, series_id, call_type, provider, model,
            input_chars, output_chars, prompt_tokens, completion_tokens,
            prompt_cache_hit_tokens, prompt_cache_miss_tokens,
            estimated_cost, elapsed_seconds, error, finish_reason, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            task_id,
            content_item_id,
            series_id,
            call_type,
            provider,
            model,
            input_chars,
            output_chars,
            prompt_tokens,
            completion_tokens,
            prompt_cache_hit_tokens,
            prompt_cache_miss_tokens,
            estimated_cost,
            elapsed_seconds,
            error,
            finish_reason,
            created_at,
        ),
    )
