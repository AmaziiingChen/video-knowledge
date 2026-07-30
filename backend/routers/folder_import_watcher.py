from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.folder_import_settings import save_folder_import_watcher_settings
from services.folder_import_watcher import folder_import_watcher


router = APIRouter()


class FolderImportWatcherRequest(BaseModel):
    folder_path: str = Field(min_length=1, max_length=4096)
    poll_interval: float = Field(default=15.0, ge=10.0, le=600.0)


class FolderImportWatcherResponse(BaseModel):
    running: bool
    folder_path: str = ""
    poll_interval: float = 15.0
    last_error: str | None = None
    last_checked_at: str | None = None
    started_at: str | None = None
    events: list[dict] = []


@router.get("/folder-import-watcher", response_model=FolderImportWatcherResponse)
async def get_folder_import_watcher_status():
    return FolderImportWatcherResponse(**folder_import_watcher.status())


@router.post("/folder-import-watcher/start", response_model=FolderImportWatcherResponse)
async def start_folder_import_watcher(req: FolderImportWatcherRequest):
    try:
        saved = save_folder_import_watcher_settings({"enabled": True, **req.model_dump()})
        folder_import_watcher.start(
            folder_path=str(saved["folder_path"]),
            poll_interval=float(saved["poll_interval"]),
            skip_existing=True,
        )
        return FolderImportWatcherResponse(**folder_import_watcher.status())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/folder-import-watcher/stop", response_model=FolderImportWatcherResponse)
async def stop_folder_import_watcher():
    folder_import_watcher.stop()
    save_folder_import_watcher_settings({"enabled": False})
    return FolderImportWatcherResponse(**folder_import_watcher.status())
