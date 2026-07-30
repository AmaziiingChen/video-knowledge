from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.rss_sync import (
    RssSyncError,
    create_rss_source,
    delete_rss_source,
    get_rss_source,
    list_rss_sources,
    list_rss_sync_runs,
    preview_rss_source,
    sync_saved_rss_source,
    update_rss_source,
)


router = APIRouter()


class RssSourceRequest(BaseModel):
    feed_url: str = Field(min_length=1, max_length=2000)
    sync_interval_minutes: int = Field(default=180, ge=30, le=1440)
    auto_analyze: bool = False
    notify_on_new: bool = False


class RssSourceUpdateRequest(BaseModel):
    enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=30, le=1440)
    group_ids: list[str] | None = Field(default=None, max_length=3)
    auto_analyze: bool | None = None
    notify_on_new: bool | None = None


@router.get("/rss-sources", response_model=list[dict])
async def get_rss_sources():
    return list_rss_sources()


@router.get("/rss-sources/{source_id}/history", response_model=list[dict])
async def get_rss_source_history(source_id: str):
    try:
        get_rss_source(source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="RSS 订阅不存在") from exc
    return list_rss_sync_runs(source_id)


@router.post("/rss-sources/preview", response_model=dict)
async def preview_rss_source_endpoint(req: RssSourceRequest):
    try:
        preview = await asyncio.to_thread(preview_rss_source, feed_url=req.feed_url)
    except RssSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "feed_url": preview.feed_url,
        "title": preview.title,
        "description": preview.description,
        "site_url": preview.site_url,
        "entries": [
            {"title": entry.title, "url": entry.url, "published_at": entry.published_at}
            for entry in preview.entries
        ],
    }


@router.post("/rss-sources", response_model=dict)
async def create_rss_source_endpoint(req: RssSourceRequest):
    try:
        return await asyncio.to_thread(
            create_rss_source,
            feed_url=req.feed_url,
            sync_interval_minutes=req.sync_interval_minutes,
            auto_analyze=req.auto_analyze,
            notify_on_new=req.notify_on_new,
        )
    except RssSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rss-sources/{source_id}/sync", response_model=dict)
async def sync_rss_source_endpoint(source_id: str):
    try:
        return await asyncio.to_thread(sync_saved_rss_source, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="RSS 订阅不存在") from exc
    except RssSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/rss-sources/{source_id}", response_model=dict)
async def update_rss_source_endpoint(source_id: str, req: RssSourceUpdateRequest):
    try:
        return await asyncio.to_thread(update_rss_source, source_id, **req.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="RSS 订阅不存在") from exc
    except RssSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/rss-sources/{source_id}", status_code=204)
async def delete_rss_source_endpoint(source_id: str):
    try:
        await asyncio.to_thread(delete_rss_source, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="RSS 订阅不存在") from exc
