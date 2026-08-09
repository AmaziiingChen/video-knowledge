from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.database import connect, initialize_database
from services.repository import ContentRepository


router = APIRouter()


class AICallUsageResponse(BaseModel):
    call_type: str
    provider: str = ""
    model: str = ""
    usage_unit: str = "tokens"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    estimated_cost: float | None = None
    elapsed_seconds: float | None = None
    image_count: int = 0
    unit_price_cny: float | None = None
    billing_region: str | None = None
    request_id: str | None = None
    image_width: int | None = None
    image_height: int | None = None


class AICallSummaryItem(BaseModel):
    call_type: str
    call_count: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    unreported_count: int


class AICallModelSummaryItem(BaseModel):
    provider: str
    model: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    estimated_cost: float = 0
    unreported_count: int


class ImageCallModelSummaryItem(BaseModel):
    provider: str
    model: str
    call_count: int
    image_count: int
    estimated_cost: float = 0
    unit_price_cny: float | None = None
    billing_region: str | None = None


class AICallSummaryResponse(BaseModel):
    period_start: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    estimated_cost: float = 0
    unreported_count: int
    by_type: list[AICallSummaryItem] = Field(default_factory=list)
    by_model: list[AICallModelSummaryItem] = Field(default_factory=list)
    image_call_count: int = 0
    image_count: int = 0
    image_estimated_cost: float = 0
    by_image_model: list[ImageCallModelSummaryItem] = Field(default_factory=list)


class OcrCallResponse(BaseModel):
    content_item_id: str | None = None
    image_url: str
    image_bytes: int
    model: str
    status: str
    cloud_submitted: bool
    retry_count: int
    elapsed_seconds: float
    error: str = ""
    created_at: str


@router.get("/content/{item_id}/ai-calls", response_model=list[AICallUsageResponse])
async def get_content_ai_calls(item_id: str):
    initialize_database()
    with connect() as connection:
        try:
            ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        rows = connection.execute(
            """
            SELECT call_type, provider, model, usage_unit,
                   prompt_tokens, completion_tokens, prompt_cache_hit_tokens,
                   prompt_cache_miss_tokens, estimated_cost, elapsed_seconds,
                   image_count, unit_price_cny, billing_region, request_id,
                   image_width, image_height
            FROM ai_calls
            WHERE content_item_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (item_id,),
        ).fetchall()
    return [
        AICallUsageResponse(
            call_type=row["call_type"],
            provider=row["provider"],
            model=row["model"],
            usage_unit=str(row["usage_unit"] or "tokens"),
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=(row["prompt_tokens"] + row["completion_tokens"])
            if row["prompt_tokens"] is not None and row["completion_tokens"] is not None
            else None,
            prompt_cache_hit_tokens=row["prompt_cache_hit_tokens"],
            prompt_cache_miss_tokens=row["prompt_cache_miss_tokens"],
            estimated_cost=row["estimated_cost"],
            elapsed_seconds=row["elapsed_seconds"],
            image_count=int(row["image_count"] or 0),
            unit_price_cny=row["unit_price_cny"],
            billing_region=row["billing_region"],
            request_id=row["request_id"],
            image_width=row["image_width"],
            image_height=row["image_height"],
        )
        for row in rows
    ]


@router.get("/ai-calls/summary", response_model=AICallSummaryResponse)
async def get_ai_call_summary():
    initialize_database()
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = local_midnight.astimezone(timezone.utc).isoformat()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT call_type, COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(prompt_cache_hit_tokens), 0) AS prompt_cache_hit_tokens,
                   COALESCE(SUM(prompt_cache_miss_tokens), 0) AS prompt_cache_miss_tokens,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   SUM(CASE WHEN prompt_tokens IS NULL OR completion_tokens IS NULL THEN 1 ELSE 0 END) AS unreported_count
            FROM ai_calls WHERE created_at >= ? AND error IS NULL AND usage_unit='tokens'
            GROUP BY call_type ORDER BY call_count DESC, call_type ASC
            """,
            (period_start,),
        ).fetchall()
        model_rows = connection.execute(
            """
            SELECT provider, model, COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(prompt_cache_hit_tokens), 0) AS prompt_cache_hit_tokens,
                   COALESCE(SUM(prompt_cache_miss_tokens), 0) AS prompt_cache_miss_tokens,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   SUM(CASE WHEN prompt_tokens IS NULL OR completion_tokens IS NULL THEN 1 ELSE 0 END) AS unreported_count
            FROM ai_calls WHERE created_at >= ? AND error IS NULL AND usage_unit='tokens'
            GROUP BY provider, model ORDER BY call_count DESC, provider ASC, model ASC
            """,
            (period_start,),
        ).fetchall()
        image_model_rows = connection.execute(
            """
            SELECT provider, model, COUNT(*) AS call_count,
                   COALESCE(SUM(image_count), 0) AS image_count,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   MAX(unit_price_cny) AS unit_price_cny, MAX(billing_region) AS billing_region
            FROM ai_calls WHERE created_at >= ? AND error IS NULL AND usage_unit='images'
            GROUP BY provider, model ORDER BY image_count DESC, provider ASC, model ASC
            """,
            (period_start,),
        ).fetchall()
    by_type = []
    prompt_tokens = completion_tokens = prompt_cache_hit_tokens = prompt_cache_miss_tokens = call_count = unreported_count = 0
    estimated_cost = 0.0
    for row in rows:
        row_prompt = int(row["prompt_tokens"] or 0)
        row_completion = int(row["completion_tokens"] or 0)
        row_cache_hit = int(row["prompt_cache_hit_tokens"] or 0)
        row_cache_miss = int(row["prompt_cache_miss_tokens"] or 0)
        row_calls = int(row["call_count"] or 0)
        row_unreported = int(row["unreported_count"] or 0)
        prompt_tokens += row_prompt
        completion_tokens += row_completion
        prompt_cache_hit_tokens += row_cache_hit
        prompt_cache_miss_tokens += row_cache_miss
        call_count += row_calls
        unreported_count += row_unreported
        estimated_cost += float(row["estimated_cost"] or 0)
        by_type.append(AICallSummaryItem(call_type=str(row["call_type"] or "unknown"), call_count=row_calls, total_tokens=row_prompt + row_completion, prompt_cache_hit_tokens=row_cache_hit, prompt_cache_miss_tokens=row_cache_miss, unreported_count=row_unreported))
    by_model = [AICallModelSummaryItem(provider=str(row["provider"] or "unknown"), model=str(row["model"] or "unknown"), call_count=int(row["call_count"] or 0), prompt_tokens=int(row["prompt_tokens"] or 0), completion_tokens=int(row["completion_tokens"] or 0), total_tokens=int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0), prompt_cache_hit_tokens=int(row["prompt_cache_hit_tokens"] or 0), prompt_cache_miss_tokens=int(row["prompt_cache_miss_tokens"] or 0), estimated_cost=round(float(row["estimated_cost"] or 0), 8), unreported_count=int(row["unreported_count"] or 0)) for row in model_rows]
    by_image_model = [ImageCallModelSummaryItem(provider=str(row["provider"] or "unknown"), model=str(row["model"] or "unknown"), call_count=int(row["call_count"] or 0), image_count=int(row["image_count"] or 0), estimated_cost=round(float(row["estimated_cost"] or 0), 8), unit_price_cny=float(row["unit_price_cny"]) if row["unit_price_cny"] is not None else None, billing_region=str(row["billing_region"] or "") or None) for row in image_model_rows]
    image_call_count = sum(item.call_count for item in by_image_model)
    image_count = sum(item.image_count for item in by_image_model)
    image_estimated_cost = sum(item.estimated_cost for item in by_image_model)
    return AICallSummaryResponse(period_start=period_start, call_count=call_count, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, total_tokens=prompt_tokens + completion_tokens, prompt_cache_hit_tokens=prompt_cache_hit_tokens, prompt_cache_miss_tokens=prompt_cache_miss_tokens, estimated_cost=round(estimated_cost, 8), unreported_count=unreported_count, by_type=by_type, by_model=by_model, image_call_count=image_call_count, image_count=image_count, image_estimated_cost=round(image_estimated_cost, 8), by_image_model=by_image_model)


@router.get("/ocr-calls", response_model=list[OcrCallResponse])
async def list_ocr_calls(limit: int = 100, content_item_id: str | None = None):
    initialize_database()
    bounded_limit = max(1, min(limit, 500))
    with connect() as connection:
        statement = """SELECT content_item_id, image_url, image_bytes, model, status, cloud_submitted, retry_count, elapsed_seconds, error, created_at FROM ocr_calls {} ORDER BY created_at DESC, id DESC LIMIT ?"""
        if content_item_id:
            rows = connection.execute(statement.format("WHERE content_item_id = ?"), (content_item_id, bounded_limit)).fetchall()
        else:
            rows = connection.execute(statement.format(""), (bounded_limit,)).fetchall()
    return [OcrCallResponse(content_item_id=row["content_item_id"], image_url=str(row["image_url"]), image_bytes=int(row["image_bytes"] or 0), model=str(row["model"]), status=str(row["status"]), cloud_submitted=bool(row["cloud_submitted"]), retry_count=int(row["retry_count"] or 0), elapsed_seconds=float(row["elapsed_seconds"] or 0), error=str(row["error"] or ""), created_at=str(row["created_at"])) for row in rows]
