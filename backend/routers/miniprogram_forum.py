from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from config import settings
from services.forum_capture_repository import ForumCaptureRepository
from services.macos_miniprogram import DEFAULT_WINDOW_PATTERN
from services.miniprogram_forum_collector import miniprogram_forum_collector
from services.miniprogram_forum_settings import (
    ALLOWED_INTERVALS,
    load_miniprogram_forum_settings,
    update_miniprogram_forum_settings,
)


def require_forum_capture_enabled() -> None:
    """Keep the unfinished visual collector unavailable in public releases."""

    if not settings.miniprogram_forum_capture_enabled:
        raise HTTPException(status_code=404, detail="微信小程序视觉采集当前未开放")


router = APIRouter(dependencies=[Depends(require_forum_capture_enabled)])
repository = ForumCaptureRepository()


class CaptureStartRequest(BaseModel):
    source_key: str = Field(default="campus_forum", pattern=r"^[a-z0-9_-]{2,64}$")
    mode: Literal["incremental", "backfill"] = "incremental"
    window_pattern: str = Field(default=DEFAULT_WINDOW_PATTERN, min_length=1, max_length=120)
    max_posts: int = Field(default=300, ge=1, le=5000)
    max_feed_scrolls: int = Field(default=500, ge=1, le=5000)
    max_detail_scrolls: int = Field(default=120, ge=1, le=1000)
    known_post_stop: int = Field(default=20, ge=1, le=200)
    page_wait_seconds: float = Field(default=1.2, ge=0.4, le=8.0)
    prompt_permissions: bool = True


class PermissionRequest(BaseModel):
    window_pattern: str = Field(default=DEFAULT_WINDOW_PATTERN, min_length=1, max_length=120)
    prompt: bool = True


class CaptureSettingsRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None
    idle_seconds_required: int | None = Field(default=None, ge=30, le=3600)
    window_pattern: str | None = Field(default=None, min_length=1, max_length=120)
    max_posts: int | None = Field(default=None, ge=1, le=5000)
    max_feed_scrolls: int | None = Field(default=None, ge=1, le=5000)
    max_detail_scrolls: int | None = Field(default=None, ge=1, le=1000)
    known_post_stop: int | None = Field(default=None, ge=1, le=200)
    page_wait_seconds: float | None = Field(default=None, ge=0.4, le=8.0)


@router.get("/miniprogram-forum/status")
def capture_status(window_pattern: str = Query(default=DEFAULT_WINDOW_PATTERN, min_length=1, max_length=120)):
    try:
        return miniprogram_forum_collector.current_status(window_pattern)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/miniprogram-forum/settings")
def get_capture_settings():
    return load_miniprogram_forum_settings()


@router.patch("/miniprogram-forum/settings")
def patch_capture_settings(req: CaptureSettingsRequest):
    values = req.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="至少提供一个需要更新的设置")
    if "interval_minutes" in values and values["interval_minutes"] not in ALLOWED_INTERVALS:
        raise HTTPException(status_code=400, detail="不支持的自动采集频率")
    try:
        return update_miniprogram_forum_settings(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/miniprogram-forum/permissions")
def request_permissions(req: PermissionRequest):
    try:
        return miniprogram_forum_collector.permission_status(req.window_pattern, prompt=req.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/miniprogram-forum/start")
def start_capture(req: CaptureStartRequest):
    try:
        return miniprogram_forum_collector.start(req.model_dump())
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/miniprogram-forum/pause")
def pause_capture():
    try:
        return miniprogram_forum_collector.pause()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/miniprogram-forum/resume")
def resume_capture():
    try:
        return miniprogram_forum_collector.resume()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/miniprogram-forum/stop")
def stop_capture():
    try:
        return miniprogram_forum_collector.stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/miniprogram-forum/runs")
def list_capture_runs(limit: int = Query(default=20, ge=1, le=100)):
    return repository.list_runs(limit=limit)


@router.get("/miniprogram-forum/posts")
def list_forum_posts(
    source_key: str | None = Query(default=None, min_length=2, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
):
    return repository.list_posts(source_key=source_key, limit=limit)


@router.get("/miniprogram-forum/posts/{post_id}")
def get_forum_post(post_id: str):
    try:
        return repository.get_post(post_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
