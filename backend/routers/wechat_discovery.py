from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from routers.tasks import TaskResponse, _to_response
from services.task_manager import task_manager
from services.wechat_discovery import (
    WeChatDiscoveryError,
    bind_discovery_task,
    bind_review_import_task,
    create_album_sync_run,
    create_discovery_run,
    fail_discovery_submission,
    fail_review_import_submission,
    get_discovery_run,
    get_public_album_source,
    list_public_album_sources,
    list_discovery_candidates,
    list_discovery_runs,
    mark_discovery_cancelled,
    update_public_album_source,
    validate_review_candidate_selection,
)


router = APIRouter()


class StartWeChatDiscoveryRequest(BaseModel):
    input_text: str = Field(min_length=1, max_length=100_000)
    auto_analyze: bool = False
    strategy: Literal["direct", "seed"] = "direct"
    subscribe_album: bool = False
    sync_interval_minutes: int = Field(default=720, ge=360, le=1440)


class ImportReviewedCandidatesRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=500)
    auto_analyze: bool = False


class UpdatePublicAlbumSourceRequest(BaseModel):
    enabled: bool | None = None
    auto_analyze: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=360, le=1440)


class StartWeChatDiscoveryResponse(BaseModel):
    run: dict[str, Any]
    task: TaskResponse


@router.get("/wechat-discovery/sources", response_model=list[dict[str, Any]])
async def get_wechat_public_album_sources():
    return list_public_album_sources()


@router.patch("/wechat-discovery/sources/{source_id}", response_model=dict[str, Any])
async def update_wechat_public_album_source(
    source_id: str,
    req: UpdatePublicAlbumSourceRequest,
):
    try:
        return update_public_album_source(
            source_id,
            enabled=req.enabled,
            auto_analyze=req.auto_analyze,
            sync_interval_minutes=req.sync_interval_minutes,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WeChatDiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/wechat-discovery/sources/{source_id}/sync",
    response_model=StartWeChatDiscoveryResponse,
    status_code=202,
)
async def sync_wechat_public_album_source(source_id: str):
    try:
        source = get_public_album_source(source_id)
        run = create_album_sync_run(source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WeChatDiscoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        task = task_manager.create_source_sync(
            {
                "kind": "wechat_public_discovery",
                "source_id": source_id,
                "payload": {"run_id": run["id"]},
            },
            source_title=f"检查合集：{source.get('title') or '公众号合集'}",
            source_url=source.get("source_url"),
            execution_mode="background",
        )
        run = bind_discovery_task(run["id"], task.task_id)
    except Exception as exc:
        fail_discovery_submission(run["id"], str(exc))
        raise HTTPException(status_code=500, detail="合集检查任务创建失败") from exc
    return StartWeChatDiscoveryResponse(run=run, task=_to_response(task))


@router.get("/wechat-discovery/runs", response_model=list[dict[str, Any]])
async def get_wechat_discovery_runs(limit: int = Query(default=30, ge=1, le=100)):
    return list_discovery_runs(limit=limit)


@router.get("/wechat-discovery/runs/{run_id}", response_model=dict[str, Any])
async def get_wechat_discovery_run(run_id: str):
    try:
        return get_discovery_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/wechat-discovery/runs/{run_id}/candidates", response_model=list[dict[str, Any]])
async def get_wechat_discovery_candidates(
    run_id: str,
    limit: int = Query(default=500, ge=1, le=500),
):
    try:
        get_discovery_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list_discovery_candidates(run_id, limit=limit)


@router.post("/wechat-discovery/runs/{run_id}/cancel", response_model=dict[str, Any])
async def cancel_wechat_discovery_run(run_id: str):
    try:
        run = get_discovery_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not run.get("task_id"):
        raise HTTPException(status_code=409, detail="该批次没有可取消的任务")
    task = task_manager.cancel(str(run["task_id"]))
    if task is None:
        raise HTTPException(status_code=404, detail="关联任务不存在")
    return mark_discovery_cancelled(run_id)


@router.post(
    "/wechat-discovery/runs",
    response_model=StartWeChatDiscoveryResponse,
    status_code=202,
)
async def start_wechat_discovery(req: StartWeChatDiscoveryRequest):
    try:
        run = create_discovery_run(
            req.input_text,
            auto_analyze=req.auto_analyze,
            strategy=req.strategy,
            subscribe_album=req.subscribe_album,
            sync_interval_minutes=req.sync_interval_minutes,
        )
    except WeChatDiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        task = task_manager.create_source_sync(
            {
                "kind": "wechat_public_discovery",
                "source_id": run["id"],
                "payload": {"run_id": run["id"]},
            },
            source_title=run.get("source_title") or "公众号公开导入",
            source_url=run.get("source_url"),
        )
        run = bind_discovery_task(run["id"], task.task_id)
    except Exception as exc:
        fail_discovery_submission(run["id"], str(exc))
        raise HTTPException(status_code=500, detail="公众号导入任务创建失败") from exc
    return StartWeChatDiscoveryResponse(run=run, task=_to_response(task))


@router.post(
    "/wechat-discovery/runs/{run_id}/import",
    response_model=StartWeChatDiscoveryResponse,
    status_code=202,
)
async def import_reviewed_wechat_candidates(
    run_id: str,
    req: ImportReviewedCandidatesRequest,
):
    try:
        run = get_discovery_run(run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.get("review_import_status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="该批次已有确认导入任务正在执行")
    try:
        validate_review_candidate_selection(run_id, req.candidate_ids)
    except WeChatDiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        task = task_manager.create_source_sync(
            {
                "kind": "wechat_public_import",
                "source_id": run_id,
                "payload": {
                    "run_id": run_id,
                    "candidate_ids": req.candidate_ids,
                    "auto_analyze": req.auto_analyze,
                },
            },
            source_title=run.get("source_title") or "公众号候选导入",
            source_url=run.get("source_url"),
        )
        run = bind_review_import_task(run_id, task.task_id)
    except Exception as exc:
        fail_review_import_submission(run_id)
        if isinstance(exc, WeChatDiscoveryError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="公众号候选导入任务创建失败") from exc
    return StartWeChatDiscoveryResponse(run=run, task=_to_response(task))
