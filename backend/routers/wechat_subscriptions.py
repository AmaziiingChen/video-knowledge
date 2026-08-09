from __future__ import annotations

from datetime import date
import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config import settings
from services.database import connect, initialize_database
from presentation.task_responses import TaskResponse, to_task_response
from services.task_manager import task_manager
from services.wechat_subscription import (
    WeChatAuthorizationError,
    WeChatSubscriptionError,
    wechat_initial_sync_queue,
    wechat_qr_auth_service,
    wechat_subscription_service,
)


router = APIRouter()


class ConnectAccountRequest(BaseModel):
    """Advanced fallback for a valid, user-provided public-platform session."""

    display_name: str = Field(default="微信公众平台账号", min_length=1, max_length=120)
    token: str = Field(min_length=1)
    cookie: str = Field(min_length=1)


class StartQrLoginRequest(BaseModel):
    display_name: str = Field(default="微信公众平台账号", min_length=1, max_length=120)
    reauthorize_account_id: str | None = None


class PollQrLoginRequest(BaseModel):
    display_name: str = Field(default="微信公众平台账号", min_length=1, max_length=120)
    reauthorize_account_id: str | None = None


class TransferSubscriptionsRequest(BaseModel):
    target_account_id: str = Field(min_length=1)


class CreateSubscriptionRequest(BaseModel):
    account_id: str = Field(min_length=1)
    fakeid: str = Field(min_length=1)
    mp_name: str = Field(min_length=1, max_length=255)
    biz: str = ""
    avatar_url: str = ""
    description: str = ""
    sync_interval_minutes: int | None = Field(default=None, ge=360, le=1440)
    auto_process: bool = False
    notify_on_new: bool = False
    initial_sync: bool = True
    initial_limit: int = Field(
        default=settings.wechat_subscription_default_initial_limit,
        ge=1,
        le=10,
    )


class UpdateSubscriptionRequest(BaseModel):
    enabled: bool | None = None
    auto_process: bool | None = None
    notify_on_new: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=360, le=1440)
    group_id: str | None = None
    group_ids: list[str] | None = Field(default=None, max_length=3)


class SyncSubscriptionRequest(BaseModel):
    mode: Literal["latest", "catch_up", "count", "date_range", "all"] = "latest"
    max_items: int | None = Field(default=10, ge=1, le=1000)
    published_after: date | None = None
    published_before: date | None = None


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, WeChatAuthorizationError):
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if isinstance(exc, WeChatSubscriptionError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="微信公众号订阅服务异常") from exc


@router.get("/wechat-subscriptions/accounts", response_model=list[dict[str, Any]])
async def list_accounts():
    return wechat_subscription_service.list_accounts()


@router.post("/wechat-subscriptions/accounts", response_model=dict[str, Any])
def connect_account(req: ConnectAccountRequest):
    try:
        return wechat_subscription_service.connect_account(
            display_name=req.display_name,
            token=req.token,
            cookie=req.cookie,
        )
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/wechat-subscriptions/accounts/qr-login", response_model=dict[str, Any])
def start_qr_login(req: StartQrLoginRequest):
    try:
        if req.reauthorize_account_id:
            # Fail before opening a QR-login session if the original account
            # was removed in another settings window.
            wechat_subscription_service.get_account(req.reauthorize_account_id)
        result = wechat_qr_auth_service.start()
        return {
            "login_id": result.login_id,
            "status": result.status,
            "message": result.message,
            "qr_image_data_url": result.qr_image_data_url,
            "display_name": req.display_name,
            "reauthorize_account_id": req.reauthorize_account_id,
        }
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/wechat-subscriptions/accounts/qr-login/{login_id}/poll", response_model=dict[str, Any])
def poll_qr_login(login_id: str, req: PollQrLoginRequest):
    try:
        result = wechat_qr_auth_service.poll(login_id)
        response: dict[str, Any] = {
            "login_id": result.login_id,
            "status": result.status,
            "message": result.message,
            "qr_image_data_url": result.qr_image_data_url,
            "reauthorize_account_id": req.reauthorize_account_id,
        }
        if result.status == "confirmed":
            response["account"] = (
                wechat_subscription_service.complete_qr_reauthorization(req.reauthorize_account_id, result)
                if req.reauthorize_account_id
                else wechat_subscription_service.complete_qr_login(result, req.display_name)
            )
        return response
    except Exception as exc:
        _raise_http_error(exc)


@router.delete("/wechat-subscriptions/accounts/{account_id}", response_model=dict[str, bool])
async def delete_account(account_id: str):
    try:
        wechat_subscription_service.delete_account(account_id)
        return {"success": True}
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/wechat-subscriptions/accounts/{account_id}/transfer-subscriptions", response_model=dict[str, Any])
async def transfer_account_subscriptions(account_id: str, req: TransferSubscriptionsRequest):
    try:
        return wechat_subscription_service.transfer_subscriptions(account_id, req.target_account_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/wechat-subscriptions/accounts/{account_id}/search", response_model=list[dict[str, str]])
def search_accounts(account_id: str, q: str = Query("", min_length=0), limit: int = Query(10, ge=1, le=20)):
    try:
        results = wechat_subscription_service.search_accounts(account_id, q, limit)
        return [
            {
                "fakeid": item.fakeid,
                "name": item.name,
                "avatar_url": item.avatar_url,
                "biz": item.biz,
                "description": item.description,
            }
            for item in results
        ]
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/wechat-subscriptions", response_model=list[dict[str, Any]])
async def list_subscriptions(account_id: str | None = Query(default=None)):
    return wechat_subscription_service.list_subscriptions(account_id)


@router.post("/wechat-subscriptions/sync-all", response_model=TaskResponse, status_code=202)
def sync_all_subscriptions():
    """Durably queue a serial catch-up check for all enabled subscriptions."""
    try:
        return to_task_response(task_manager.create_source_sync(
            {"kind": "wechat_bulk"},
            source_title="检查全部公众号",
        ))
    except Exception as exc:
        _raise_http_error(exc)



@router.post("/wechat-subscriptions", response_model=dict[str, Any])
async def create_subscription(req: CreateSubscriptionRequest):
    try:
        subscription = wechat_subscription_service.create_subscription(
            account_id=req.account_id,
            fakeid=req.fakeid,
            mp_name=req.mp_name,
            biz=req.biz,
            avatar_url=req.avatar_url,
            description=req.description,
            sync_interval_minutes=req.sync_interval_minutes,
            auto_process=req.auto_process,
            notify_on_new=req.notify_on_new,
        )
        response: dict[str, Any] = {"subscription": subscription}
        if req.initial_sync:
            response["sync"] = to_task_response(task_manager.create_source_sync(
                {
                    "kind": "wechat_subscription",
                    "subscription_id": subscription["id"],
                    "mode": "latest",
                    "max_items": req.initial_limit,
                },
                source_title=f"首次检查：{subscription['mp_name']}",
            )).model_dump()
        return response
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/wechat-subscriptions/{subscription_id}/initial-sync", response_model=dict[str, Any])
async def get_initial_sync_status(subscription_id: str):
    try:
        # Clients created before the task API still call this endpoint. Bridge
        # it to the durable task record instead of reporting the old in-memory
        # queue as idle while the first check is actually running.
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                "SELECT id, request_json FROM tasks WHERE task_type='source_sync' ORDER BY created_at DESC LIMIT 200"
            ).fetchall()
        for row in rows:
            try:
                request = json.loads(str(row["request_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            source_request = request.get("source_sync_request") or {}
            if (
                source_request.get("kind") == "wechat_subscription"
                and str(source_request.get("subscription_id") or "") == subscription_id
            ):
                task = task_manager.get(str(row["id"]))
                if task:
                    result = task.result.source_sync_result if task.result else {}
                    return {
                        "status": task.status,
                        "task_id": task.task_id,
                        "subscription_id": subscription_id,
                        "found_count": int((result or {}).get("found_count") or 0),
                        "eligible_count": int((result or {}).get("eligible_count") or 0),
                        "imported_count": int((result or {}).get("imported_count") or 0),
                        "error": task.result.error if task.result else None,
                    }
        return wechat_initial_sync_queue.status(subscription_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/wechat-subscriptions/{subscription_id}", response_model=dict[str, Any])
async def get_subscription(subscription_id: str):
    try:
        return wechat_subscription_service.get_subscription(subscription_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.patch("/wechat-subscriptions/{subscription_id}", response_model=dict[str, Any])
async def update_subscription(subscription_id: str, req: UpdateSubscriptionRequest):
    try:
        fields = req.model_fields_set
        updates: dict[str, Any] = {}
        for field in ("enabled", "auto_process", "notify_on_new", "sync_interval_minutes", "group_id", "group_ids"):
            if field in fields:
                updates[field] = getattr(req, field)
        return wechat_subscription_service.update_subscription(subscription_id, **updates)
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/wechat-subscriptions/{subscription_id}/profile", response_model=dict[str, Any])
def refresh_subscription_profile(subscription_id: str):
    try:
        return wechat_subscription_service.refresh_subscription_profile(subscription_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.delete("/wechat-subscriptions/{subscription_id}", response_model=dict[str, bool])
async def delete_subscription(subscription_id: str):
    try:
        wechat_subscription_service.delete_subscription(subscription_id)
        return {"success": True}
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/wechat-subscriptions/{subscription_id}/sync", response_model=TaskResponse, status_code=202)
def sync_subscription(subscription_id: str, req: SyncSubscriptionRequest):
    try:
        if req.mode == "date_range" and (not req.published_after or not req.published_before):
            raise ValueError("请选择完整的发布日期范围")
        if req.published_after and req.published_before and req.published_after > req.published_before:
            raise ValueError("开始日期不能晚于结束日期")
        subscription = wechat_subscription_service.get_subscription(subscription_id)
        return to_task_response(task_manager.create_source_sync(
            {
                "kind": "wechat_subscription",
                "subscription_id": subscription_id,
                "max_items": req.max_items,
                "mode": req.mode,
                "published_after": req.published_after.isoformat() if req.published_after else None,
                "published_before": req.published_before.isoformat() if req.published_before else None,
            },
            source_title=f"检查公众号：{subscription['mp_name']}",
        ))
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/wechat-subscriptions/{subscription_id}/runs", response_model=list[dict[str, Any]])
async def list_sync_runs(subscription_id: str, limit: int = Query(30, ge=1, le=100)):
    try:
        return wechat_subscription_service.list_sync_runs(subscription_id, limit)
    except Exception as exc:
        _raise_http_error(exc)
