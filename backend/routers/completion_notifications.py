from fastapi import APIRouter
from pydantic import BaseModel, Field

from services.completion_notifications import list_pending_notifications, mark_notifications_seen, record_completion_notification

router = APIRouter()

class NotificationCreateRequest(BaseModel):
    event_key: str = Field(min_length=1, max_length=300)
    event_type: str = Field(default="assistant_response", max_length=40)
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(default="", max_length=800)
    content_item_id: str | None = Field(default=None, max_length=100)
    target_view: str = Field(default="library", max_length=40)

class NotificationSeenRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)

@router.get("/completion-notifications", response_model=list[dict])
async def get_completion_notifications(limit: int = 20):
    return list_pending_notifications(limit)

@router.post("/completion-notifications", response_model=dict)
async def create_completion_notification(req: NotificationCreateRequest):
    return {"created": record_completion_notification(**req.model_dump())}

@router.post("/completion-notifications/seen", response_model=dict)
async def see_completion_notifications(req: NotificationSeenRequest):
    return {"updated": mark_notifications_seen(req.ids)}
