from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.creator_sync import (
    CreatorSyncError,
    creator_capture_status,
    delete_creator_source,
    get_creator_source,
    list_creator_sync_runs,
    list_creator_sources,
    preview_creator_source,
    sync_saved_creator_source,
    sync_creator_source,
    update_creator_source,
)
from services.bilibili_auth import get_bilibili_cookie_status
from services.douyin_cookie_status import get_douyin_cookie_status


router = APIRouter()


class CreatorSourceRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)
    # Initial import only. Scheduled checks use persisted source membership as
    # their boundary rather than a user-entered item cap.
    limit: int = Field(default=1, ge=1, le=500)
    published_after: str | None = Field(default=None, max_length=32)
    published_before: str | None = Field(default=None, max_length=32)
    auto_process: bool = True
    sync_interval_minutes: int = Field(default=360, ge=30, le=1440)
    processing_mode: str = Field(default="full", pattern="^(metadata|transcript|full)$")
    selected_video_ids: list[str] | None = Field(default=None, max_length=500)
    allow_personal_sources: bool = False


class CreatorSourceSettingsRequest(BaseModel):
    enabled: bool | None = None
    auto_process: bool | None = None
    processing_mode: str | None = Field(default=None, pattern="^(metadata|transcript|full)$")
    sync_interval_minutes: int | None = Field(default=None, ge=30, le=1440)


class CreatorVideoResponse(BaseModel):
    provider: str
    canonical_id: str
    source_url: str
    title: str
    cover_url: str = ""
    duration_seconds: float | None = None
    published_at: str | None = None
    description: str = ""
    author_name: str = ""
    tags: list[str] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)


class CreatorPreviewResponse(BaseModel):
    provider: str
    source_kind: str
    source_url: str
    creator_key: str
    creator_name: str
    videos: list[CreatorVideoResponse]
    creator_avatar_url: str = ""
    creator_description: str = ""
    collection_id: str = ""
    collection_name: str = ""


class CreatorSyncResponse(BaseModel):
    source_id: str
    provider: str
    creator_name: str
    folder_id: str
    discovered_count: int
    created_count: int
    duplicate_count: int
    queued_count: int
    inbox_count: int
    task_ids: list[str]
    content_item_ids: list[str]


def _preview_response(preview) -> CreatorPreviewResponse:
    return CreatorPreviewResponse(
        provider=preview.provider,
        source_kind=preview.source_kind,
        source_url=preview.source_url,
        creator_key=preview.creator_key,
        creator_name=preview.creator_name,
        creator_avatar_url=preview.creator_avatar_url,
        creator_description=preview.creator_description,
        collection_id=preview.collection_id,
        collection_name=preview.collection_name,
        videos=[
            CreatorVideoResponse(
                **{
                    **video.__dict__,
                    "tags": list(video.tags),
                    "stats": video.stats or {},
                }
            )
            for video in preview.videos
        ],
    )


@router.get("/creator-sources", response_model=list[dict])
async def get_creator_sources():
    return list_creator_sources()


@router.get("/creator-sources/health", response_model=dict)
async def get_creator_source_health(
    refresh: bool = Query(default=False),
    probe_douyin: bool = Query(default=True),
):
    return {
        "capture": creator_capture_status(),
        "cookies": {
            "douyin": get_douyin_cookie_status(force=refresh, probe=probe_douyin),
            "bilibili": get_bilibili_cookie_status(force=refresh),
        },
    }


@router.get("/creator-sources/{source_id}/history", response_model=list[dict])
async def get_creator_source_history(source_id: str):
    try:
        get_creator_source(source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="创作者订阅不存在") from exc
    return list_creator_sync_runs(source_id)


@router.post("/creator-sources/preview", response_model=CreatorPreviewResponse)
async def preview_creator_source_endpoint(req: CreatorSourceRequest):
    try:
        # The collector uses Playwright's synchronous API. Run it outside
        # FastAPI's asyncio loop so Playwright can own its worker thread and
        # other API requests remain responsive while a creator page loads.
        preview = await asyncio.to_thread(
            preview_creator_source,
            source_url=req.source_url,
            limit=req.limit,
            published_after=req.published_after,
            published_before=req.published_before,
            allow_personal_sources=req.allow_personal_sources,
        )
    except CreatorSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _preview_response(preview)


@router.post("/creator-sources/sync", response_model=CreatorSyncResponse)
async def sync_creator_source_endpoint(req: CreatorSourceRequest):
    try:
        result = await asyncio.to_thread(sync_creator_source, **req.model_dump())
    except CreatorSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreatorSyncResponse(**result.__dict__)


@router.post("/creator-sources/{source_id}/sync", response_model=CreatorSyncResponse)
async def sync_saved_creator_source_endpoint(source_id: str):
    try:
        # This endpoint is the ordinary update check. Historical failures are
        # retried only through the explicit retry action/task payload.
        result = await asyncio.to_thread(sync_saved_creator_source, source_id, retry_existing_items=False)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="创作者订阅不存在") from exc
    except CreatorSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CreatorSyncResponse(**result.__dict__)


@router.patch("/creator-sources/{source_id}", response_model=dict)
async def update_creator_source_endpoint(source_id: str, req: CreatorSourceSettingsRequest):
    try:
        return await asyncio.to_thread(update_creator_source, source_id, **req.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="创作者订阅不存在") from exc
    except CreatorSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/creator-sources/{source_id}", status_code=204)
async def delete_creator_source_endpoint(source_id: str):
    try:
        await asyncio.to_thread(delete_creator_source, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="创作者订阅不存在") from exc
