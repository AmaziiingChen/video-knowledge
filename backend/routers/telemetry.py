from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services import telemetry
from services.telemetry_uploader import telemetry_uploader

router = APIRouter()


class TelemetrySettingsRequest(BaseModel):
    enabled: bool
    privacy_notice_version: str = ""


class TelemetryEventRequest(BaseModel):
    event_name: Literal[
        "app_started", "workspace_opened", "import_started", "import_completed", "task_enqueued",
        "pipeline_stage_reached", "pipeline_stage_failed", "task_finished", "task_control_used",
        "paddle_ocr_completed", "obsidian_sync_completed", "search_completed", "clipboard_listener_changed",
        "update_check_completed", "telemetry_consent_changed", "update_download_page_opened",
        "export_completed",
    ]
    properties: dict[str, str] = {}


@router.get("/telemetry")
def telemetry_status() -> dict[str, object]:
    return {**telemetry.status(), **telemetry_uploader.status()}


@router.put("/telemetry")
def save_telemetry_settings(request: TelemetrySettingsRequest) -> dict[str, object]:
    try:
        return telemetry.set_enabled(request.enabled, notice_version=request.privacy_notice_version)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/telemetry/upload")
def upload_telemetry_now() -> dict[str, object]:
    return telemetry_uploader.upload_now()


@router.post("/telemetry/events", status_code=204)
def record_telemetry_event(request: TelemetryEventRequest) -> None:
    telemetry.record(request.event_name, request.properties)
