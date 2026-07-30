from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import settings
from services.database import connect, initialize_database
from services.knowledge_library import attachments_root
from services.transcriber import extract_audio_with_details, transcribe_with_details

router = APIRouter()

class TranscribeRequest(BaseModel):
    video_path: str

class TranscribeResponse(BaseModel):
    success: bool
    transcript: str | None = None
    error: str | None = None


def _is_managed_media_path(path: Path) -> bool:
    """Permit private data media and originals explicitly owned by the library."""
    try:
        path.relative_to(settings.data_dir.expanduser().resolve())
        return True
    except ValueError:
        pass
    try:
        path.relative_to(attachments_root().resolve())
        return True
    except ValueError:
        pass
    try:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM media_assets WHERE asset_type='original_file' AND path=? LIMIT 1",
                (str(path),),
            ).fetchone()
        return row is not None
    except Exception:
        return False

@router.post("/transcribe", response_model=TranscribeResponse)
def transcribe_video(req: TranscribeRequest):
    video_path = Path(req.video_path).expanduser().resolve()
    if not _is_managed_media_path(video_path):
        raise HTTPException(status_code=400, detail="只能转写应用管理的媒体文件")

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    
    audio_path = video_path.with_suffix(".wav")
    
    audio_result = extract_audio_with_details(video_path, audio_path)
    if not audio_result.success:
        raise HTTPException(status_code=500, detail=audio_result.error or "音频提取失败")
    
    transcribe_result = transcribe_with_details(audio_path)
    audio_path.unlink(missing_ok=True)
    if transcribe_result.success:
        transcript = transcribe_result.transcript
        audio_path.unlink(missing_ok=True)
        return TranscribeResponse(success=True, transcript=transcript)
    raise HTTPException(status_code=500, detail=transcribe_result.error or "转写失败")
