from pathlib import Path
import re
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config import settings
from routers.tasks import TaskResponse, _to_response
from services.pipeline_runner import PipelineRequest, WHISPER_MODELS
from services.manual_collection_settings import manual_collection_settings
from services.subtitles import SUBTITLE_EXTENSIONS
from services.task_manager import task_manager


router = APIRouter()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".flv", ".avi"}


class UploadTasksResponse(BaseModel):
    tasks: list[TaskResponse] = Field(default_factory=list)


def _safe_filename(filename: str) -> str:
    name = Path(filename or "video.mp4").name
    stem = Path(name).stem.strip() or "video"
    suffix = Path(name).suffix.lower()
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff -]+", "_", stem)[:80].strip(" ._")
    return f"{safe_stem or 'video'}{suffix}"


@router.post("/upload-tasks", response_model=UploadTasksResponse)
async def create_upload_tasks(
    files: list[UploadFile] = File(...),
    whisper_model: str | None = Form(None),
    asr_backend: str | None = Form(None),
    asr_model_strategy: str | None = Form(None),
    asr_short_video_model: str | None = Form(None),
    asr_long_video_model: str | None = Form(None),
    asr_beam_size: int | None = Form(None),
    asr_vad_filter: bool | None = Form(None),
    asr_fallback_enabled: bool | None = Form(None),
    ai_model: str | None = Form(None),
):
    if whisper_model and whisper_model not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的 Whisper 模型: {whisper_model}")
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的视频")

    batch_dir = settings.data_dir / "uploads" / str(uuid.uuid4())[:8]
    batch_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for upload in files:
        safe_name = _safe_filename(upload.filename or "")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的视频格式: {safe_name}")

        target = batch_dir / f"{str(uuid.uuid4())[:8]}_{safe_name}"
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)

        if target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"上传文件为空: {safe_name}")

        request = PipelineRequest(
            local_video_path=str(target),
            source_title=Path(safe_name).stem,
            source_url=f"local://{safe_name}",
            whisper_model=whisper_model,
            asr_backend=asr_backend,
            asr_model_strategy=asr_model_strategy,
            asr_short_video_model=asr_short_video_model,
            asr_long_video_model=asr_long_video_model,
            asr_beam_size=asr_beam_size,
            asr_vad_filter=asr_vad_filter,
            asr_fallback_enabled=asr_fallback_enabled,
            ai_model=ai_model,
            use_cache=False,
            processing_mode="full" if manual_collection_settings()["auto_summarize"] else "transcript",
            manual_collection=True,
        )
        records.append(task_manager.create(request))

    return UploadTasksResponse(tasks=[_to_response(record) for record in records])


@router.post("/upload-subtitle-tasks", response_model=UploadTasksResponse)
async def create_upload_subtitle_tasks(
    files: list[UploadFile] = File(...),
    whisper_model: str | None = Form(None),
    asr_backend: str | None = Form(None),
    asr_model_strategy: str | None = Form(None),
    asr_short_video_model: str | None = Form(None),
    asr_long_video_model: str | None = Form(None),
    asr_beam_size: int | None = Form(None),
    asr_vad_filter: bool | None = Form(None),
    asr_fallback_enabled: bool | None = Form(None),
    ai_model: str | None = Form(None),
):
    if whisper_model and whisper_model not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"不支持的 Whisper 模型: {whisper_model}")
    if not files:
        raise HTTPException(status_code=400, detail="请选择要上传的字幕")

    batch_dir = settings.data_dir / "uploads" / "subtitles" / str(uuid.uuid4())[:8]
    batch_dir.mkdir(parents=True, exist_ok=True)

    records = []
    for upload in files:
        safe_name = _safe_filename(upload.filename or "subtitle.vtt")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in SUBTITLE_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的字幕格式: {safe_name}")

        target = batch_dir / f"{str(uuid.uuid4())[:8]}_{safe_name}"
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)

        if target.stat().st_size == 0:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"上传文件为空: {safe_name}")

        request = PipelineRequest(
            local_subtitle_path=str(target),
            source_title=Path(safe_name).stem,
            source_url=f"local://{safe_name}",
            whisper_model=whisper_model,
            asr_backend=asr_backend,
            asr_model_strategy=asr_model_strategy,
            asr_short_video_model=asr_short_video_model,
            asr_long_video_model=asr_long_video_model,
            asr_beam_size=asr_beam_size,
            asr_vad_filter=asr_vad_filter,
            asr_fallback_enabled=asr_fallback_enabled,
            ai_model=ai_model,
            use_cache=False,
            processing_mode="full" if manual_collection_settings()["auto_summarize"] else "transcript",
            manual_collection=True,
        )
        records.append(task_manager.create(request))

    return UploadTasksResponse(tasks=[_to_response(record) for record in records])
