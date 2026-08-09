"""Read-model mapping shared by content-library API boundaries."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from config import settings
from services.content_source_text import ContentTextReadiness, inspect_content_text_readiness
from services.database import connect
from services.local_file_imports import local_file_metadata, original_attachment_path
from services.knowledge_library import markdown_document_path
from services.repository import ContentItemRecord
from services.cache import read_cached_transcript_segments


class ContentTextReadinessResponse(BaseModel):
    status: str
    label: str
    detail: str
    source_kind: str | None = None
    can_ask_ai: bool
    retryable: bool = False


class ContentItemResponse(BaseModel):
    id: str
    content_type: str
    source_provider: str
    source_url: str | None = None
    canonical_source_id: str | None = None
    title: str
    cover_url: str | None = None
    video_path: str | None = None
    original_file_path: str | None = None
    source_metadata: dict[str, object] = Field(default_factory=dict)
    video_cache_status: str = "missing"
    video_cache_expires_at: str | None = None
    video_cache_expired_at: str | None = None
    thumbnail_vtt_url: str | None = None
    cache_size_bytes: int = 0
    markdown_draft_path: str | None = None
    markdown_size_bytes: int = 0
    duration_seconds: float | None = None
    transcript_segments: list[dict] = Field(default_factory=list)
    text_readiness: ContentTextReadinessResponse
    status: str
    series_id: str | None = None
    library_folder_id: str | None = None
    sort_order: float = 0
    created_at: str
    updated_at: str
    published_at: str | None = None
    source_name: str | None = None
    source_section: str | None = None


def content_item_response(
    item: ContentItemRecord,
    cache_entry: dict | None = None,
    *,
    include_runtime_details: bool = True,
) -> ContentItemResponse:
    cache_entry = cache_entry or {}
    imported_original = original_attachment_path(item.id) if item.source_provider == "local_file" else None
    imported_video = imported_original if item.content_type in {"video", "audio"} else None
    source_metadata = local_file_metadata(imported_original) if imported_original and include_runtime_details else {}
    markdown_draft_path, markdown_size_bytes = content_markdown_metadata(item.id) if include_runtime_details else (None, 0)
    duration = item.duration_seconds
    if duration is None and include_runtime_details:
        cache_duration = cache_entry.get("duration")
        duration = float(cache_duration) if cache_duration else None
    if duration is None:
        metadata_duration = source_metadata.get("duration_seconds")
        try:
            duration = float(metadata_duration) if metadata_duration else None
        except (TypeError, ValueError):
            duration = None
    return ContentItemResponse(
        id=item.id,
        content_type=item.content_type,
        source_provider=item.source_provider,
        source_url=item.source_url,
        canonical_source_id=item.canonical_source_id,
        title=item.title,
        cover_url=item.cover_url,
        video_path=cache_entry.get("video_path") or (str(imported_video) if imported_video else None),
        original_file_path=str(imported_original) if imported_original else None,
        source_metadata=source_metadata,
        video_cache_status=("available" if imported_video else str(cache_entry.get("video_cache_status") or "missing")),
        video_cache_expires_at=cache_entry.get("video_cache_expires_at"),
        video_cache_expired_at=cache_entry.get("video_cache_expired_at"),
        thumbnail_vtt_url=cache_entry.get("thumbnail_vtt_url"),
        cache_size_bytes=int(cache_entry.get("size_bytes") or (imported_video.stat().st_size if imported_video else 0)),
        markdown_draft_path=markdown_draft_path,
        markdown_size_bytes=markdown_size_bytes,
        duration_seconds=duration,
        transcript_segments=segments_for_cache_entry(cache_entry, duration) if include_runtime_details else [],
        text_readiness=(
            readiness_response(inspect_content_text_readiness(item))
            if include_runtime_details
            else listing_text_readiness()
        ),
        status=item.status,
        series_id=item.series_id,
        library_folder_id=item.library_folder_id,
        sort_order=item.sort_order,
        created_at=item.created_at,
        updated_at=item.updated_at,
        published_at=item.published_at,
        source_name=item.source_name,
        source_section=item.source_section,
    )


def content_markdown_metadata(content_item_id: str) -> tuple[str | None, int]:
    """Return the canonical Markdown path and its actual on-disk byte size."""
    canonical_path = markdown_document_path(content_item_id)
    candidates = [canonical_path] if canonical_path is not None else []
    with connect() as connection:
        row = connection.execute(
            """SELECT markdown_draft_path FROM obsidian_sync
               WHERE content_item_id = ?
               ORDER BY rowid DESC LIMIT 1""",
            (content_item_id,),
        ).fetchone()
    if row and row["markdown_draft_path"]:
        candidates.append(Path(str(row["markdown_draft_path"])))
    for path in candidates:
        try:
            if path.is_file():
                return str(path), path.stat().st_size
        except OSError:
            continue
    return None, 0


def readiness_response(readiness: ContentTextReadiness) -> ContentTextReadinessResponse:
    return ContentTextReadinessResponse(
        status=readiness.status,
        label=readiness.label,
        detail=readiness.detail,
        source_kind=readiness.source_kind,
        can_ask_ai=readiness.can_ask_ai,
        retryable=readiness.retryable,
    )


def listing_text_readiness() -> ContentTextReadinessResponse:
    """Return a cheap placeholder for rows whose detail has not been opened."""
    return ContentTextReadinessResponse(
        status="pending",
        label="打开后检查",
        detail="打开内容后加载正文、字幕和转写状态。",
        source_kind=None,
        can_ask_ai=False,
    )


def segments_for_cache_entry(cache_entry: dict, duration: float | None) -> list[dict]:
    cache_key = cache_entry.get("cache_key")
    if not cache_key:
        return []
    cache_dir = settings.data_dir / "cache" / str(cache_key)
    if not cache_dir.exists():
        return []
    transcripts = cache_entry.get("transcripts") or []
    return read_cached_transcript_segments(
        Path(cache_dir),
        preferred_model=transcripts[-1] if transcripts else None,
        duration=duration,
    )
