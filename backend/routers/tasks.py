import json
from datetime import datetime
from pathlib import Path
from fastapi.responses import StreamingResponse

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from config import settings
from services.database import connect, initialize_database
from presentation.task_responses import TaskResponse, to_task_response
from services.pipeline_runner import PipelineRequest
from services.cache import cache_entry_for_url
from services.local_file_imports import original_attachment_path
from services.repository import ContentRepository
from services.source_context_store import (
    SUPPORTED_SOURCE_CONTEXT_PROVIDERS,
    get_source_context_record,
    load_source_context,
)
from services.task_manager import task_manager


router = APIRouter()




class CancelActiveTasksResponse(BaseModel):
    cancelled_count: int
    tasks: list[TaskResponse]


class SourceContextStatusResponse(BaseModel):
    content_item_id: str
    provider: str
    status: str
    context: dict = Field(default_factory=dict)
    comment_sample_count: int = 0
    comment_total: int | None = None
    comments_complete: bool = False
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error: str = ""
    updated_at: str = ""




@router.post("/tasks", response_model=TaskResponse)
async def create_task(req: PipelineRequest):
    return to_task_response(task_manager.create(req))


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    updated_after: datetime | None = None,
    task_ids: str | None = Query(default=None, max_length=10_000),
):
    records = task_manager.list()
    requested_ids = {
        task_id.strip()
        for task_id in (task_ids or "").split(",")
        if task_id.strip()
    }
    if len(requested_ids) > 200:
        raise HTTPException(status_code=400, detail="单次最多查询 200 个任务")
    if requested_ids:
        records = [record for record in records if record.task_id in requested_ids]
    elif updated_after is not None:
        cutoff = updated_after.timestamp()
        records = [
            record
            for record in records
            if record.status in {"queued", "running", "paused"}
            or _task_timestamp(record.updated_at) >= cutoff
        ]
    return [to_task_response(record, include_heavy_payload=False) for record in records]


def _task_timestamp(value: str | None) -> float:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


@router.post("/content/{item_id}/retry-processing", response_model=TaskResponse)
async def retry_latest_content_task(item_id: str):
    """Retry the latest failed processing task for one existing library item."""
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id FROM tasks
            WHERE content_item_id = ? AND status IN ('failed', 'cancelled')
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="该内容没有可重试的处理任务")
    record = task_manager.retry(str(row["id"]))
    if record is None:
        raise HTTPException(status_code=404, detail="处理任务不存在")
    return to_task_response(record)


@router.get("/content/{item_id}/source-context", response_model=SourceContextStatusResponse)
async def get_content_source_context(item_id: str):
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
    if item.source_provider not in SUPPORTED_SOURCE_CONTEXT_PROVIDERS or not item.source_url:
        raise HTTPException(status_code=400, detail="该内容来源不支持互动数据采集")
    record = get_source_context_record(item_id)
    if record is None:
        return SourceContextStatusResponse(
            content_item_id=item.id,
            provider=item.source_provider,
            status="pending",
            context=load_source_context(item.id),
        )
    return SourceContextStatusResponse(**record.__dict__)


@router.post("/content/{item_id}/refresh-source-context", response_model=TaskResponse)
async def refresh_content_source_context(item_id: str):
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
    if item.source_provider not in SUPPORTED_SOURCE_CONTEXT_PROVIDERS or not item.source_url:
        raise HTTPException(status_code=400, detail="该内容来源不支持互动数据采集")
    record = task_manager.create_source_sync(
        {
            "kind": "source_context_refresh",
            "source_id": item.id,
            "comment_limit": 60,
            "comment_pages": 3,
        },
        source_title=f"补采互动数据：{item.title or item.source_provider}",
        execution_mode="foreground",
    )
    return to_task_response(record)


@router.post("/content/source-context/backfill", response_model=TaskResponse)
async def backfill_content_source_context(
    limit: int = Query(default=50, ge=1, le=200),
    include_ready: bool = False,
):
    record = task_manager.create_source_sync(
        {
            "kind": "source_context_backfill",
            "limit": limit,
            "include_ready": include_ready,
        },
        source_title="批量补采互动数据",
        execution_mode="background",
    )
    return to_task_response(record)


@router.post("/content/{item_id}/retranscribe", response_model=TaskResponse)
async def retranscribe_downloaded_media(item_id: str):
    """Start a fresh transcription from retained audio or video, never re-download it."""
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        try:
            item = repository.get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        if item.content_type not in {"audio", "video"}:
            raise HTTPException(status_code=400, detail="只有音频或视频可以重新转写")
        active = connection.execute(
            """SELECT 1 FROM tasks
               WHERE content_item_id=? AND status IN ('queued', 'running', 'paused')
               LIMIT 1""",
            (item_id,),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail="该媒体已有正在处理的任务")
        latest_task = connection.execute(
            """SELECT request_json, result_json FROM tasks
               WHERE content_item_id=?
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (item_id,),
        ).fetchone()

    media_path = original_attachment_path(item.id) if item.source_provider == "local_file" else None
    if media_path is None:
        media_path = _retained_video_path(item.source_url, latest_task["result_json"] if latest_task else None)
    if media_path is None:
        raise HTTPException(status_code=409, detail="本地音视频文件不存在，无法重新转写")

    previous_request = _previous_pipeline_request(latest_task["request_json"] if latest_task else None)
    request_payload = previous_request.model_dump() if previous_request else {}
    request_payload.update({
        "content_item_id": item.id,
        "share_text": item.source_url,
        "source_title": item.title,
        "source_url": item.source_url,
        "local_video_path": str(media_path),
        "local_subtitle_path": None,
        # local_video_path bypasses all cached transcripts; keep this explicit
        # so future pipeline changes cannot accidentally re-enable reuse.
        "use_cache": False,
        "priority": 100,
        "execution_mode": "foreground",
    })
    record = task_manager.create(PipelineRequest.model_validate(request_payload))
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    return to_task_response(record)


@router.post("/content/{item_id}/fetch-external-subtitle", response_model=TaskResponse)
async def fetch_bilibili_external_subtitle(item_id: str):
    """Fetch a verified Bilibili player subtitle and summarize it without media download."""
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        try:
            item = repository.get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        if item.content_type != "video" or item.source_provider != "bilibili" or not item.source_url:
            raise HTTPException(status_code=400, detail="仅支持尝试获取 B站视频的外挂字幕")
        active = connection.execute(
            """SELECT 1 FROM tasks
               WHERE content_item_id=? AND status IN ('queued', 'running', 'paused')
               LIMIT 1""",
            (item_id,),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail="该视频已有正在处理的任务")
        latest_task = connection.execute(
            """SELECT request_json FROM tasks
               WHERE content_item_id=?
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (item_id,),
        ).fetchone()

    previous_request = _previous_pipeline_request(latest_task["request_json"] if latest_task else None)
    request_payload = previous_request.model_dump() if previous_request else {}
    request_payload.update({
        "content_item_id": item.id,
        "share_text": item.source_url,
        "source_title": item.title,
        "source_url": item.source_url,
        "local_video_path": None,
        "local_subtitle_path": None,
        "use_cache": True,
        "processing_mode": "full",
        "subtitle_only": True,
        "priority": 100,
        "execution_mode": "foreground",
    })
    record = task_manager.create(PipelineRequest.model_validate(request_payload))
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    return to_task_response(record)


@router.post("/content/{item_id}/redownload-video", response_model=TaskResponse)
async def redownload_expired_video(item_id: str):
    """Restore a preview; Bilibili keeps its subtitle-first analysis path."""
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        try:
            item = repository.get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        if item.content_type != "video" or not item.source_url:
            raise HTTPException(status_code=400, detail="该内容没有可重新下载的视频来源")
        active = connection.execute(
            """SELECT 1 FROM tasks
               WHERE content_item_id=? AND status IN ('queued', 'running', 'paused')
               LIMIT 1""",
            (item_id,),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail="该视频已有正在处理的任务")
        latest_task = connection.execute(
            """SELECT request_json, result_json FROM tasks
               WHERE content_item_id=?
               ORDER BY updated_at DESC, id DESC LIMIT 1""",
            (item_id,),
        ).fetchone()

    if _retained_video_path(item.source_url, latest_task["result_json"] if latest_task else None):
        raise HTTPException(status_code=409, detail="本地视频仍可用，无需重新下载")
    previous_request = _previous_pipeline_request(latest_task["request_json"] if latest_task else None)
    request_payload = previous_request.model_dump() if previous_request else {}
    is_bilibili = item.source_provider == "bilibili"
    request_payload.update({
        "content_item_id": item.id,
        "share_text": item.source_url,
        "source_title": item.title,
        "source_url": item.source_url,
        "local_video_path": None,
        "local_subtitle_path": None,
        "use_cache": True,
        # For Bilibili, a manually requested preview must not bypass player
        # subtitles and the short AI-summary path.  Other sources retain the
        # established preview-only recovery behavior.
        "processing_mode": "full" if is_bilibili else "download_only",
        "download_video_preview": is_bilibili,
        "subtitle_only": False,
        "priority": 100,
        "execution_mode": "foreground",
    })
    record = task_manager.create(PipelineRequest.model_validate(request_payload))
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    return to_task_response(record)


def _previous_pipeline_request(request_json: str | None) -> PipelineRequest | None:
    if not request_json:
        return None
    try:
        return PipelineRequest.model_validate(json.loads(request_json))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _retained_video_path(source_url: str | None, result_json: str | None) -> Path | None:
    candidates: list[str] = []
    if source_url:
        cache_entry = cache_entry_for_url(source_url, include_size=False) or {}
        if cache_entry.get("video_path"):
            candidates.append(str(cache_entry["video_path"]))
    if result_json:
        try:
            result_path = json.loads(result_json).get("video_path")
        except (TypeError, ValueError, json.JSONDecodeError):
            result_path = None
        if result_path:
            candidates.append(str(result_path))

    data_dir = Path(settings.data_dir).resolve()
    for value in candidates:
        try:
            path = Path(value).expanduser().resolve()
            path.relative_to(data_dir)
        except (OSError, ValueError):
            continue
        if path.is_file() and path.stat().st_size > 10_000:
            return path
    return None


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    record = task_manager.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return to_task_response(record)


@router.get("/tasks/{task_id}/events")
def stream_task_updates(task_id: str):
    """Stream live in-memory snapshots for the opened task detail.

    The regular task endpoints stay durable polling APIs for the dock and
    history.  This narrow SSE channel avoids making an LLM's token stream wait
    for SQLite writes and repeated full-detail requests.
    """
    if task_manager.get(task_id) is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    def event_stream():
        for record in task_manager.subscribe_updates(task_id):
            if record is None:
                yield ": keepalive\n\n"
                continue
            payload = to_task_response(record).model_dump(mode="json")
            yield f"event: task\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: str):
    record = task_manager.cancel(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return to_task_response(record)


@router.post("/tasks/cancel-active", response_model=CancelActiveTasksResponse)
async def cancel_active_tasks():
    records = task_manager.cancel_active()
    return CancelActiveTasksResponse(
        cancelled_count=len(records),
        tasks=[to_task_response(record, include_heavy_payload=False) for record in records],
    )


@router.post("/tasks/{task_id}/pause", response_model=TaskResponse)
async def pause_task(task_id: str):
    record = task_manager.pause(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return to_task_response(record)


@router.post("/tasks/{task_id}/resume", response_model=TaskResponse)
async def resume_task(task_id: str):
    record = task_manager.resume(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return to_task_response(record)


@router.post("/tasks/{task_id}/prioritize", response_model=TaskResponse)
async def prioritize_task(task_id: str):
    record = task_manager.reprioritize(task_id, 10)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return to_task_response(record)


@router.post("/tasks/{task_id}/retry", response_model=TaskResponse)
async def retry_task(task_id: str):
    record = task_manager.retry(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="任务不存在")
    return to_task_response(record)
