import json
from datetime import datetime
from queue import Empty, Queue
from threading import Thread
from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from services.wechat_reports import (
    create_group,
    delete_group,
    generate_report,
    preflight_report,
    list_groups,
    update_report_schedule,
    list_report_prompts,
    update_report_prompt,
    reset_report_prompt as restore_report_prompt,
)

router = APIRouter()

class GroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)

class ReportRequest(BaseModel):
    report_type: str = Field(pattern="^(daily|weekly|range)$")
    window_start: datetime | None = None
    window_end: datetime | None = None
    include_history_context: bool = True
    include_external_imports: bool = False
    file_name: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_window(self):
        if self.report_type == "range" and self.window_start is None and self.window_end is None:
            raise ValueError("区间汇总必须提供开始时间和结束时间")
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("指定范围必须同时提供开始时间和结束时间")
        if self.window_start is None or self.window_end is None:
            return self
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("指定范围的时间必须包含时区")
        if self.window_end <= self.window_start:
            raise ValueError("结束时间必须晚于开始时间")
        return self


class ReportScheduleRequest(BaseModel):
    enabled: bool = False
    report_type: str = Field(pattern="^(daily|weekly)$")
    weekdays: list[int] = Field(min_length=1, max_length=7)
    time_of_day: str = Field(min_length=5, max_length=5)


class ReportPromptRequest(BaseModel):
    template: str | None = Field(default=None, min_length=1, max_length=20000)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_update(self):
        if self.template is None and self.display_name is None:
            raise ValueError("提示词内容或名称至少填写一项")
        return self

@router.get("/wechat-report-groups")
async def groups(): return list_groups()

@router.post("/wechat-report-groups")
async def add_group(req: GroupRequest):
    try: return create_group(req.name, req.description)
    except Exception as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/wechat-report-groups/{group_id}")
async def remove_group(group_id: str):
    try:
        return delete_group(group_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/wechat-report-groups/{group_id}/schedule")
def save_report_schedule(group_id: str, req: ReportScheduleRequest):
    try:
        return update_report_schedule(
            group_id,
            enabled=req.enabled,
            report_type=req.report_type,
            weekdays=req.weekdays,
            time_of_day=req.time_of_day,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/wechat-report-groups/{group_id}/generate")
def create_report(group_id: str, req: ReportRequest):
    try:
        return generate_report(
            group_id,
            req.report_type,
            window_start=req.window_start,
            window_end=req.window_end,
            include_history_context=req.include_history_context,
            include_external_imports=req.include_external_imports,
            file_name=req.file_name,
        )
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wechat-report-groups/{group_id}/preflight")
def inspect_report_generation(group_id: str, req: ReportRequest):
    try:
        return preflight_report(
            group_id,
            req.report_type,
            window_start=req.window_start,
            window_end=req.window_end,
            include_external_imports=req.include_external_imports,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wechat-report-groups/{group_id}/generate-stream")
def create_report_stream(group_id: str, req: ReportRequest):
    """Stream long-running campus report progress to the global process log."""
    return StreamingResponse(
        _report_event_stream(
            group_id,
            req.report_type,
            window_start=req.window_start,
            window_end=req.window_end,
            include_history_context=req.include_history_context,
            include_external_imports=req.include_external_imports,
            file_name=req.file_name,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _report_event_stream(
    group_id: str,
    report_type: str,
    *,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    include_history_context: bool = True,
    include_external_imports: bool = False,
    file_name: str | None = None,
) -> Iterator[str]:
    events: Queue[dict[str, object] | None] = Queue()

    def on_progress(event: dict[str, object]) -> None:
        events.put({"event": "progress", **event})

    def worker() -> None:
        try:
            result = generate_report(
                group_id,
                report_type,
                window_start=window_start,
                window_end=window_end,
                include_history_context=include_history_context,
                include_external_imports=include_external_imports,
                file_name=file_name,
                progress_callback=on_progress,
            )
            events.put({"event": "complete", "result": result})
        except Exception as exc:
            events.put({
                "event": "error",
                "message": str(exc) or exc.__class__.__name__,
            })
        finally:
            events.put(None)

    Thread(target=worker, name=f"wechat-{report_type}-stream", daemon=True).start()
    while True:
        try:
            event = events.get(timeout=15)
        except Empty:
            yield ": keep-alive\n\n"
            continue
        if event is None:
            return
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

@router.get("/wechat-report-prompts")
async def report_prompts():
    return list_report_prompts()


@router.put("/wechat-report-groups/{group_id}/prompts/{report_type}")
async def save_report_prompt(group_id: str, report_type: str, req: ReportPromptRequest):
    try:
        return update_report_prompt(group_id, report_type, req.template, display_name=req.display_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/wechat-report-groups/{group_id}/prompts/{report_type}/reset")
async def reset_report_prompt(group_id: str, report_type: str):
    try:
        return restore_report_prompt(group_id, report_type)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
