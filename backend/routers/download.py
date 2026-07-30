from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from pathlib import Path
import uuid
from services.downloader import download_video, get_video_info
from config import settings

router = APIRouter()

class DownloadRequest(BaseModel):
    url: str
    platform: str

class DownloadResponse(BaseModel):
    success: bool
    video_path: str | None = None
    video_info: dict | None = None
    logs: list[str] = Field(default_factory=list)
    error: str | None = None

@router.post("/download", response_model=DownloadResponse)
def download(req: DownloadRequest):
    task_id = str(uuid.uuid4())[:8]
    output_dir = settings.data_dir / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    
    video_info = get_video_info(req.url, req.platform)
    
    result = download_video(req.url, req.platform, output_dir)
    if result.success:
        return DownloadResponse(
            success=True,
            video_path=str(result.video_path),
            video_info={**result.video_info, "platform": req.platform},
            logs=result.logs
        )
    raise HTTPException(
        status_code=500,
        detail={"error": result.error, "logs": result.logs}
    )
