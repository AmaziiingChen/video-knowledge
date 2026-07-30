from datetime import date

from fastapi import APIRouter, HTTPException, Query

from services.agent_workspace import workspace_overview


router = APIRouter()


@router.get("/agent/workspace-overview")
async def get_agent_workspace_overview(
    for_date: date | None = Query(default=None),
    conversation_key: str | None = Query(default=None, min_length=1, max_length=512),
    content_limit: int = Query(default=12, ge=1, le=50),
    task_limit: int = Query(default=12, ge=1, le=50),
):
    try:
        return workspace_overview(
            for_date=for_date,
            conversation_key=conversation_key,
            content_limit=content_limit,
            task_limit=task_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
