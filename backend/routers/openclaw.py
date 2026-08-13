from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from services.openclaw_conversations import (
    bind_task,
    claim_terminal_notification,
    get_conversation_settings,
    list_conversation_tasks,
    list_conversations,
    record_conversation_turn,
    update_conversation_settings,
)
from services.openclaw_gateway import (
    OpenClawGatewayError,
    get_openclaw_status,
    repair_openclaw_mcp,
    start_openclaw_gateway,
)
from services.openclaw_usage import get_openclaw_usage

router = APIRouter()


class OpenClawConversationSettingsRequest(BaseModel):
    transcript_mirror_enabled: bool = False
    transcript_retention_days: int = Field(default=30, ge=1, le=365)


class OpenClawConversationTaskRequest(BaseModel):
    conversation_key: str = Field(min_length=1, max_length=512)
    task_id: str = Field(min_length=1)
    channel: str = Field(default="weixin", max_length=40)
    display_name: str | None = Field(default=None, max_length=120)


class OpenClawConversationNotificationRequest(BaseModel):
    conversation_key: str = Field(min_length=1, max_length=512)
    task_id: str = Field(min_length=1)


class OpenClawConversationTurnRequest(BaseModel):
    conversation_key: str = Field(min_length=1, max_length=512)
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(min_length=1, max_length=12000)
    turn_id: str | None = Field(default=None, max_length=160)
    channel: str = Field(default="weixin", max_length=40)
    display_name: str | None = Field(default=None, max_length=120)


@router.get("/openclaw-gateway")
async def get_gateway_status(refresh: bool = Query(default=False)):
    return get_openclaw_status(force_refresh=refresh)


@router.post("/openclaw-gateway/start")
async def start_gateway():
    try:
        return start_openclaw_gateway()
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/openclaw-gateway/repair-mcp")
async def repair_gateway_mcp():
    try:
        return repair_openclaw_mcp()
    except OpenClawGatewayError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/openclaw/usage")
async def get_openclaw_token_usage():
    """Expose only aggregate token metadata for the local OpenClaw sessions."""
    return get_openclaw_usage()


@router.get("/openclaw/conversation-settings")
async def get_openclaw_conversation_settings():
    return get_conversation_settings()


@router.put("/openclaw/conversation-settings")
async def save_openclaw_conversation_settings(req: OpenClawConversationSettingsRequest):
    try:
        return update_conversation_settings(
            transcript_mirror_enabled=req.transcript_mirror_enabled,
            transcript_retention_days=req.transcript_retention_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/openclaw/conversations")
async def get_openclaw_conversations(limit: int = Query(default=20, ge=1, le=100)):
    return list_conversations(limit=limit)


@router.get("/openclaw/conversation-tasks")
async def get_openclaw_conversation_tasks(
    conversation_key: str = Query(min_length=1, max_length=512),
    limit: int = Query(default=8, ge=1, le=50),
):
    try:
        return list_conversation_tasks(session_key=conversation_key, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/openclaw/conversation-tasks")
async def create_openclaw_conversation_task(req: OpenClawConversationTaskRequest):
    try:
        return bind_task(
            session_key=req.conversation_key,
            task_id=req.task_id,
            channel=req.channel,
            display_name=req.display_name,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/openclaw/conversation-tasks/claim-notification")
async def claim_openclaw_conversation_notification(req: OpenClawConversationNotificationRequest):
    try:
        return claim_terminal_notification(session_key=req.conversation_key, task_id=req.task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/openclaw/conversation-turns")
async def create_openclaw_conversation_turn(req: OpenClawConversationTurnRequest):
    try:
        return record_conversation_turn(
            session_key=req.conversation_key,
            role=req.role,
            text=req.text,
            turn_id=req.turn_id,
            channel=req.channel,
            display_name=req.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
