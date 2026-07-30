from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services import wechat_content_filters as filters


router = APIRouter()


class FilterRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    subscription_id: str | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    enabled: bool = True
    selectors: list[str] = Field(default_factory=list)
    text_patterns: list[str] = Field(default_factory=list)


@router.get("/wechat-content-filters", response_model=list[dict[str, Any]])
async def list_wechat_content_filters(subscription_id: str | None = Query(default=None)):
    return filters.list_filter_rules(subscription_id)


@router.post("/wechat-content-filters", response_model=dict[str, Any])
async def create_wechat_content_filter(req: FilterRuleRequest):
    try:
        return filters.create_filter_rule(**req.model_dump())
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/wechat-content-filters/{rule_id}", response_model=dict[str, bool])
async def delete_wechat_content_filter(rule_id: str):
    try:
        filters.delete_filter_rule(rule_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"success": True}
