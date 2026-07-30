"""Fast, durable submission endpoint for long-running source checks."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from routers.tasks import TaskResponse, _to_response
from services.task_manager import task_manager


router = APIRouter()


class SourceSyncTaskRequest(BaseModel):
    kind: Literal[
        "creator_new",
        "creator_saved",
        "campus",
        "wechat_subscription",
        "wechat_bulk",
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
    request = req.model_dump(exclude_none=True)
    if req.source_url_input:
        request["source_url"] = req.source_url_input
    task = task_manager.create_source_sync(
        request,
        source_title=req.source_title,
        source_url=req.source_url,
    )
    return _to_response(task)
