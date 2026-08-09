from pathlib import Path
import re
import shutil
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config import settings
from presentation.task_responses import TaskResponse, to_task_response
from services.pipeline_runner import PipelineRequest, WHISPER_MODELS
from services.manual_collection_settings import manual_collection_settings
from services.subtitles import SUBTITLE_EXTENSIONS
from services.task_manager import task_manager


router = APIRouter()

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".flv", ".avi"}
UPLOAD_CHUNK_BYTES = 1024 * 1024


class UploadTasksResponse(BaseModel):
    tasks: list[TaskResponse] = Field(default_factory=list)


def _safe_filename(filename: str) -> str:
    name = Path(filename or "video.mp4").name
    stem = Path(name).stem.strip() or "video"
    suffix = Path(name).suffix.lower()
    safe_stem = re.sub(r"[^\w\u4e00-\u9fff -]+", "_", stem)[:80].strip(" ._")
    return f"{safe_stem or 'video'}{suffix}"


async def _copy_upload(upload: UploadFile, target: Path, *, batch_bytes: int) -> int:
    """Write an upload in bounded chunks and remove partial output on failure."""
    written = 0
    try:
        with target.open("wb") as output:
            while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
                written += len(chunk)
                if written > settings.upload_max_file_bytes:
                    raise HTTPException(status_code=413, detail="单个上传文件超过本机允许的大小")
                if batch_bytes + written > settings.upload_max_batch_bytes:
                    raise HTTPException(status_code=413, detail="本次批量上传超过本机允许的总大小")
                output.write(chunk)
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except OSError as error:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=507, detail="本机存储空间不足或无法写入上传文件") from error

    if written == 0:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"上传文件为空: {_safe_filename(upload.filename or '')}")
    return written


async def _persist_uploads(
    files: list[UploadFile],
    *,
    batch_dir: Path,
    extensions: set[str],
    fallback_name: str,
    content_label: str,
) -> list[tuple[str, Path]]:
    if len(files) > settings.upload_max_files:
        raise HTTPException(status_code=413, detail=f"一次最多上传 {settings.upload_max_files} 个{content_label}")

    batch_dir.mkdir(parents=True, exist_ok=True)
    records: list[tuple[str, Path]] = []
    batch_bytes = 0
    try:
        for upload in files:
            safe_name = _safe_filename(upload.filename or fallback_name)
            if Path(safe_name).suffix.lower() not in extensions:
                raise HTTPException(status_code=400, detail=f"不支持的{content_label}格式: {safe_name}")
            target = batch_dir / f"{str(uuid.uuid4())[:8]}_{safe_name}"
            batch_bytes += await _copy_upload(upload, target, batch_bytes=batch_bytes)
            records.append((safe_name, target))
        return records
    except Exception:
        # A rejected batch must not leave earlier files occupying local storage.
        shutil.rmtree(batch_dir, ignore_errors=True)
        parent = batch_dir.parent
        while parent != settings.data_dir:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        raise


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
    uploaded_files = await _persist_uploads(
        files,
        batch_dir=batch_dir,
        extensions=VIDEO_EXTENSIONS,
        fallback_name="video.mp4",
        content_label="视频",
    )

    records = []
    for safe_name, target in uploaded_files:
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

    return UploadTasksResponse(tasks=[to_task_response(record) for record in records])


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
    uploaded_files = await _persist_uploads(
        files,
        batch_dir=batch_dir,
        extensions=SUBTITLE_EXTENSIONS,
        fallback_name="subtitle.vtt",
        content_label="字幕",
    )

    records = []
    for safe_name, target in uploaded_files:
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

    return UploadTasksResponse(tasks=[to_task_response(record) for record in records])
