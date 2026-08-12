"""Fast, durable submission endpoint for long-running source checks."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from presentation.task_responses import TaskResponse, to_task_response
from services.task_manager import task_manager
from services.xiaohongshu_capability import XiaohongshuCollectorUnavailable, require_xiaohongshu_collector


router = APIRouter()


class SourceSyncTaskRequest(BaseModel):
    kind: Literal[
        "creator_new",
        "creator_saved",
        "campus",
        "wechat_subscription",
        "wechat_bulk",
        "wechat_public_discovery",
        "wechat_public_import",
        "favorite_douyin",
        "favorite_bilibili",
        "favorite_xiaohongshu",
        "favorite_saved",
        "rss_saved",
        "rss_create",
    ]
    source_title: str = Field(default="来源同步", min_length=1, max_length=300)
    source_url: str | None = Field(default=None, max_length=2000)
    source_id: str | None = Field(default=None, max_length=100)
    subscription_id: str | None = Field(default=None, max_length=100)
    source_slug: str | None = Field(default=None, max_length=100)
    source_url_input: str | None = Field(default=None, max_length=2000)
    auto_analyze: bool = True
    retry_existing_items: bool = True
    mode: str = Field(default="latest", max_length=32)
    max_items: int | None = Field(default=None, ge=1, le=500)
    limit: int | None = Field(default=None, ge=1, le=500)
    section: str | None = Field(default=None, max_length=200)
    published_after: str | None = Field(default=None, max_length=32)
    published_before: str | None = Field(default=None, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/source-sync-tasks", response_model=TaskResponse, status_code=202)
async def create_source_sync_task(req: SourceSyncTaskRequest):
    if req.kind == "favorite_xiaohongshu":
        try:
            require_xiaohongshu_collector()
        except XiaohongshuCollectorUnavailable as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    request = req.model_dump(exclude_none=True)
    if req.source_url_input:
        request["source_url"] = req.source_url_input
    try:
        task = task_manager.create_source_sync(
            request,
            source_title=req.source_title,
            source_url=req.source_url,
        )
    except XiaohongshuCollectorUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return to_task_response(task)
