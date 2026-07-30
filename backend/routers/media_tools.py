from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.media_tools import media_tool_status, save_media_tools

router = APIRouter()

class MediaToolsRequest(BaseModel):
    ffmpeg_path: str = ""
    yt_dlp_path: str = ""

@router.get("/media-tools")
async def get_media_tools():
    return media_tool_status()

@router.put("/media-tools")
async def update_media_tools(req: MediaToolsRequest):
    try:
        return save_media_tools(**req.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
