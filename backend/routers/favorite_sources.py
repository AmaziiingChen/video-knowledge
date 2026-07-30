from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.favorite_sync import (
    FavoriteSyncError,
    add_bilibili_favorite,
    delete_favorite_source,
    enable_douyin_favorites,
    get_favorite_source,
    list_favorite_sources,
    list_favorite_sync_runs,
    process_pending_favorite_items,
    sync_saved_favorite,
    update_favorite_source,
)
from services.xiaohongshu_ingest import (
    get_xiaohongshu_favorite_source,
    sync_xiaohongshu_favorites,
    update_xiaohongshu_favorite_source,
)


router = APIRouter()


class BilibiliFavoriteRequest(BaseModel):
    source_url: str = Field(min_length=1, max_length=2000)
    auto_analyze: bool = True


class DouyinFavoriteRequest(BaseModel):
    auto_analyze: bool = True


class XiaohongshuFavoriteRequest(BaseModel):
    auto_analyze: bool = True


class FavoriteSourceUpdateRequest(BaseModel):
    enabled: bool | None = None
    auto_analyze: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=30, le=1440)


@router.get("/favorite-sources", response_model=list[dict])
async def get_favorite_sources():
    return list_favorite_sources()


@router.get("/favorite-sources/{source_id}/history", response_model=list[dict])
async def get_favorite_source_history(source_id: str):
    try:
        get_favorite_source(source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="个人收藏不存在") from exc
    return list_favorite_sync_runs(source_id)


@router.post("/favorite-sources/douyin", response_model=dict)
async def enable_douyin_favorite_endpoint(req: DouyinFavoriteRequest):
    try:
        return await asyncio.to_thread(enable_douyin_favorites, auto_analyze=req.auto_analyze)
    except FavoriteSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/favorite-sources/bilibili", response_model=dict)
async def add_bilibili_favorite_endpoint(req: BilibiliFavoriteRequest):
    try:
        return await asyncio.to_thread(add_bilibili_favorite, source_url=req.source_url, auto_analyze=req.auto_analyze)
    except FavoriteSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/favorite-sources/xiaohongshu", response_model=dict)
async def sync_xiaohongshu_favorite_endpoint(req: XiaohongshuFavoriteRequest):
    try:
        return await asyncio.to_thread(sync_xiaohongshu_favorites, auto_analyze=req.auto_analyze)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/favorite-sources/xiaohongshu", response_model=dict | None)
async def get_xiaohongshu_favorite_endpoint():
    return await asyncio.to_thread(get_xiaohongshu_favorite_source)


@router.patch("/favorite-sources/xiaohongshu", response_model=dict)
async def update_xiaohongshu_favorite_endpoint(req: FavoriteSourceUpdateRequest):
    try:
        return await asyncio.to_thread(
            update_xiaohongshu_favorite_source,
            enabled=req.enabled,
            auto_analyze=req.auto_analyze,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="小红书个人收藏尚未启用") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/favorite-sources/{source_id}/sync", response_model=dict)
async def sync_favorite_source_endpoint(source_id: str):
    try:
        return await asyncio.to_thread(sync_saved_favorite, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="个人收藏不存在") from exc
    except FavoriteSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/favorite-sources/{source_id}/process-pending", response_model=dict)
async def process_pending_favorite_items_endpoint(source_id: str):
    try:
        return await asyncio.to_thread(process_pending_favorite_items, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="个人收藏不存在") from exc
    except FavoriteSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/favorite-sources/{source_id}", response_model=dict)
async def update_favorite_source_endpoint(source_id: str, req: FavoriteSourceUpdateRequest):
    try:
        return await asyncio.to_thread(update_favorite_source, source_id, **req.model_dump())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="个人收藏不存在") from exc
    except FavoriteSyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/favorite-sources/{source_id}", status_code=204)
async def delete_favorite_source_endpoint(source_id: str):
    try:
        await asyncio.to_thread(delete_favorite_source, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="个人收藏不存在") from exc
