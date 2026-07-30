from fastapi import APIRouter
from pydantic import BaseModel

from services.video_download_settings import load_video_download_settings, save_video_download_settings


router = APIRouter()


class VideoDownloadSettingsRequest(BaseModel):
    auto_download_bilibili_video: bool = False
    douyin_video_quality: str = "standard"


@router.get("/video-download-settings", response_model=dict)
def get_video_download_settings():
    return load_video_download_settings()


@router.put("/video-download-settings", response_model=dict)
def update_video_download_settings(req: VideoDownloadSettingsRequest):
    return save_video_download_settings(
        auto_download_bilibili_video=req.auto_download_bilibili_video,
        douyin_video_quality=req.douyin_video_quality,
    )
