"""OpenClaw-facing endpoints for asynchronous WeChat group reports."""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from services.openclaw_conversations import bind_task
from services.openclaw_report_tasks import openclaw_report_task_manager


router = APIRouter()


class CreateOpenClawReportTaskRequest(BaseModel):
    group_id: str = Field(min_length=1)
    report_type: str = Field(pattern="^(daily|weekly|range)$")
    window_start: datetime | None = None
    window_end: datetime | None = None
    include_history_context: bool = True
    file_name: str | None = Field(default=None, max_length=120)
    conversation_key: str = Field(min_length=1, max_length=512)
    conversation_label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_window(self):
        if self.report_type == "range" and (self.window_start is None or self.window_end is None):
            raise ValueError("区间汇总必须提供开始时间和结束时间")
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("指定范围必须同时提供开始时间和结束时间")
        if self.window_start is not None and self.window_end is not None:
            if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
                raise ValueError("指定范围的时间必须包含时区")
            if self.window_end <= self.window_start:
                raise ValueError("结束时间必须晚于开始时间")
        return self


class CreateOpenClawReportDraftRequest(BaseModel):
    user_confirmed: bool = Field(description="Only true when the user explicitly asked to create a WeChat Official Account draft.")
    title: str = Field(default="", max_length=64)
    digest: str = Field(default="", max_length=120)
    author: str = Field(default="", max_length=64)


@router.post("/openclaw/report-tasks")
def create_openclaw_report_task(req: CreateOpenClawReportTaskRequest):
    try:
        task = openclaw_report_task_manager.create(
            group_id=req.group_id,
            report_type=req.report_type,
            window_start=req.window_start,
            window_end=req.window_end,
            include_history_context=req.include_history_context,
            file_name=req.file_name,
        )
        bind_task(
            session_key=req.conversation_key,
            task_id=str(task["task_id"]),
            channel="weixin",
            display_name=req.conversation_label,
        )
        return task
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/openclaw/report-tasks/{task_id}")
def get_openclaw_report_task(task_id: str):
    try:
        return openclaw_report_task_manager.get(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/openclaw/report-tasks/{task_id}/draft")
def create_openclaw_report_draft(task_id: str, req: CreateOpenClawReportDraftRequest):
    if not req.user_confirmed:
        raise HTTPException(status_code=400, detail="只有用户明确要求创建草稿后才能执行此操作")
    try:
        return openclaw_report_task_manager.create_draft(
            task_id=task_id,
            title=req.title,
            digest=req.digest,
            author=req.author,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
