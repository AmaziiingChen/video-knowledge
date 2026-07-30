from __future__ import annotations

import sqlite3
import html
import re
import hashlib
import shutil
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from services.database import connect, initialize_database
from services.content_index import ensure_content_index_ready, ensure_external_markdown_folder
from services.library_source_groups import list_library_source_groups, remove_library_source_group_member
from services.content_source_text import (
    ContentTextReadiness,
    inspect_content_text_readiness,
    load_content_source_text,
)
from services.article_ingest_preparation import (
    article_image_ocr_status,
    article_source_preparation_status,
    prioritize_article_image_ocr,
)
from services.article_preview import (
    ARTICLE_NORMALIZER_VERSION,
    build_local_article_html as _local_article_html,
    build_local_html_source_preview,
)
from services.xiaohongshu_ingest import render_xiaohongshu_description_html
from services.campus_sources import is_campus_attachment_blacklisted, render_document_markdown_html
from services.document_formatter import request_document_formatting
from services.published_at import PUBLISHED_AT_PARSER_VERSION

from config import settings
from services.cache import (
    cache_dir_for_url,
    cache_entry_for_url,
    delete_cache_entry,
    read_cache_meta,
    read_cached_transcript_segments,
)
from services.database import utc_now_iso
from services.repository import new_id
from services.repository import ContentItemRecord, ContentRepository
from services.markdown_sync import save_markdown_draft_and_sync
from services.local_file_imports import (
    extract_document_text,
    extract_html_document,
    import_kind_for_filename,
    imported_html_needs_refresh,
    persist_original_attachment,
    persist_original_attachment_from_file,
    original_attachment_path,
    local_file_metadata,
    safe_import_filename,
    save_imported_document,
    validate_import_upload,
)
from services.pipeline_runner import PipelineRequest
from services.task_manager import task_manager
from services.obsidian_settings import is_managed_obsidian_note_path
from services.search_index import upsert_source_text_document
from services.knowledge_library import (
    ensure_library_folder_directory,
    markdown_document_path,
    relocate_managed_documents,
    remove_empty_library_folder_directory,
)


router = APIRouter()
logger = logging.getLogger(__name__)

CONTENT_STATUSES = {"inbox", "processing", "to_read", "distilled", "archived", "failed"}

class ContentTextReadinessResponse(BaseModel):
    status: str
    label: str
    detail: str
    source_kind: str | None = None
    can_ask_ai: bool
    retryable: bool = False


@router.get("/content/article-preparation-status", response_model=dict)
async def get_article_preparation_status():
    """Expose the real background body-capture/OCR queue to the desktop UI."""
    return article_source_preparation_status()


@router.get("/content/{content_item_id}/article-ocr-status", response_model=dict)
async def get_article_ocr_status(content_item_id: str):
    """Report whether this article's image text is ready for later AI requests."""
    return article_image_ocr_status(content_item_id)


@router.post("/content/{content_item_id}/prioritize-article-ocr", response_model=dict)
async def prioritize_article_ocr(content_item_id: str):
    """Promote one article's pending image OCR without issuing duplicate jobs."""
    status = prioritize_article_image_ocr(content_item_id)
    if status["status"] == "unavailable":
        raise HTTPException(status_code=404, detail="未找到可识别图片的文章")
    return status


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


class ContentPageResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool
    recent_after: str | None = None


class LocalFileImportResponse(BaseModel):
    item: ContentItemResponse
    task_id: str | None = None
    processing: bool = False


class ContentItemsResolveRequest(BaseModel):
    content_item_ids: list[str] = Field(min_length=1, max_length=300)


class FolderHistoryPageResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool
    history_before: str


class FolderContentPageResponse(BaseModel):
    """A lightweight, explicit-folder page for the lazy library tree."""

    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool


class ArticlePreviewResponse(BaseModel):
    content_item_id: str
    title: str
    author: str = ""
    published_at: str = ""
    html: str
    source_html: str = ""
    gallery: list[dict[str, object]] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)
    formatting_status: str = "not_applicable"
    formatting_detail: str = ""


class AICallUsageResponse(BaseModel):
    call_type: str
    provider: str = ""
    model: str = ""
    usage_unit: str = "tokens"
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    prompt_cache_hit_tokens: int | None = None
    prompt_cache_miss_tokens: int | None = None
    estimated_cost: float | None = None
    elapsed_seconds: float | None = None
    image_count: int = 0
    unit_price_cny: float | None = None
    billing_region: str | None = None
    request_id: str | None = None
    image_width: int | None = None
    image_height: int | None = None


class AICallSummaryItem(BaseModel):
    call_type: str
    call_count: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    unreported_count: int


class AICallModelSummaryItem(BaseModel):
    provider: str
    model: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    estimated_cost: float = 0
    unreported_count: int


class ImageCallModelSummaryItem(BaseModel):
    provider: str
    model: str
    call_count: int
    image_count: int
    estimated_cost: float = 0
    unit_price_cny: float | None = None
    billing_region: str | None = None


class AICallSummaryResponse(BaseModel):
    period_start: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    estimated_cost: float = 0
    unreported_count: int
    by_type: list[AICallSummaryItem] = Field(default_factory=list)
    by_model: list[AICallModelSummaryItem] = Field(default_factory=list)
    image_call_count: int = 0
    image_count: int = 0
    image_estimated_cost: float = 0
    by_image_model: list[ImageCallModelSummaryItem] = Field(default_factory=list)


class OcrCallResponse(BaseModel):
    content_item_id: str | None = None
    image_url: str
    image_bytes: int
    model: str
    status: str
    cloud_submitted: bool
    retry_count: int
    elapsed_seconds: float
    error: str = ""
    created_at: str


class LibraryFolderResponse(BaseModel):
    id: str
    name: str
    parent_folder_id: str | None = None
    sort_order: float = 0
    is_pinned: bool = False
    presentation_group: str | None = None
    content_count: int = 0
    created_at: str
    updated_at: str


class LibraryFolderLocationResponse(BaseModel):
    path: str


class ContentStatusRequest(BaseModel):
    status: str = Field(min_length=1)


class ContentUpdateRequest(BaseModel):
    title: str | None = None
    library_folder_id: str | None = None
    sort_order: float | None = None


class FolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_folder_id: str | None = None
    sort_order: float = 0


class FolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_folder_id: str | None = None
    sort_order: float | None = None
    is_pinned: bool | None = None


class TrashEntryResponse(BaseModel):
    id: str
    entry_type: str
    name: str
    deleted_at: str
    content_type: str | None = None
    source_provider: str | None = None


def _item_to_response(
    item: ContentItemRecord,
    cache_entry: dict | None = None,
    *,
    include_runtime_details: bool = True,
) -> ContentItemResponse:
    cache_entry = cache_entry or {}
    imported_original = original_attachment_path(item.id) if item.source_provider == "local_file" else None
    imported_video = imported_original if item.content_type in {"video", "audio"} else None
    source_metadata = local_file_metadata(imported_original) if imported_original and include_runtime_details else {}
    markdown_draft_path, markdown_size_bytes = _content_markdown_metadata(item.id) if include_runtime_details else (None, 0)
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
        transcript_segments=(
            _segments_for_cache_entry(cache_entry, duration)
            if include_runtime_details
            else []
        ),
        text_readiness=(
            _readiness_response(inspect_content_text_readiness(item))
            if include_runtime_details
            else _listing_text_readiness()
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


def _content_markdown_metadata(content_item_id: str) -> tuple[str | None, int]:
    """Return the canonical Markdown path and its actual on-disk byte size.

    The file is the source of truth here: file length must not be inferred
    from an HTML preview, a summary, or a stale database hash.  Canonical
    source documents cover WeChat article body text and OCR, while the legacy
    sync path remains a fallback for older content that has not migrated yet.
    """
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


def _readiness_response(readiness: ContentTextReadiness) -> ContentTextReadinessResponse:
    return ContentTextReadinessResponse(
        status=readiness.status,
        label=readiness.label,
        detail=readiness.detail,
        source_kind=readiness.source_kind,
        can_ask_ai=readiness.can_ask_ai,
        retryable=readiness.retryable,
    )


def _listing_text_readiness() -> ContentTextReadinessResponse:
    """Return a cheap placeholder for the library tree.

    Reading readiness for a video can involve opening cache metadata and its
    transcript; doing that for every row makes the first library paint scale
    with the entire local archive.  The client fetches the exact state once a
    user opens a specific item.
    """
    return ContentTextReadinessResponse(
        status="pending",
        label="打开后检查",
        detail="打开内容后加载正文、字幕和转写状态。",
        source_kind=None,
        can_ask_ai=False,
    )


@router.get("/content", response_model=list[ContentItemResponse])
def list_content(
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    if status and status not in CONTENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的内容状态: {status}")
    initialize_database()
    ensure_content_index_ready()
    with connect() as connection:
        items = ContentRepository(connection).list_content_items(status=status, limit=limit)
    cache_entries = _cache_entries_by_source_url(item.source_url for item in items)
    return [
        _item_to_response(
            item,
            cache_entries.get(item.source_url or ""),
        )
        for item in items
    ]


@router.get("/content/page", response_model=ContentPageResponse)
def list_content_page(
    status: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    include_history: bool = False,
    recent_after: str | None = None,
):
    if status and status not in CONTENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的内容状态: {status}")
    initialize_database()
    ensure_content_index_ready()
    cutoff = _library_recent_cutoff(
        include_history=include_history,
        recent_after=recent_after,
    )
    with connect() as connection:
        repository = ContentRepository(connection)
        items = repository.list_content_items(
            status=status,
            limit=limit,
            offset=offset,
            published_after=cutoff,
        )
        total = repository.count_content_items(status=status, published_after=cutoff)
    # The tree only needs durable database fields.  Cache inspection and
    # transcript parsing are per-item work and belong to the detail request
    # below, not to the first visible page of the library.
    responses = [_item_to_response(item, include_runtime_details=False) for item in items]
    return ContentPageResponse(
        items=responses,
        total=total,
        offset=offset,
        has_more=offset + len(responses) < total,
        recent_after=cutoff,
    )


@router.get("/content/item/{item_id}", response_model=ContentItemResponse)
def get_content_item(item_id: str):
    """Load one item's runtime details after it is opened in the workbench."""
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
    cache_entry = cache_entry_for_url(item.source_url or "", include_size=False)
    return _item_to_response(item, cache_entry)


@router.post("/content/items/resolve", response_model=list[ContentItemResponse])
def resolve_content_items(req: ContentItemsResolveRequest):
    """Hydrate a bounded set of explicit library records for the tree.

    This is intentionally separate from the 30-day startup listing: callers
    use it only after a user action (for example, a completed history sync).
    """
    initialize_database()
    with connect() as connection:
        items = ContentRepository(connection).list_content_items_by_ids(req.content_item_ids)
    return [_item_to_response(item, include_runtime_details=False) for item in items]


def _library_recent_cutoff(*, include_history: bool, recent_after: str | None) -> str | None:
    """Keep the startup library bounded without deleting older documents.

    The first page returns an exact cutoff that the client passes on all later
    pages, so a long scroll cannot shift its result set while new items arrive.
    Historical documents stay available to explicit archive/search endpoints;
    they are simply excluded from the default workbench memory footprint.
    """
    if include_history:
        return None
    if recent_after:
        try:
            parsed = datetime.fromisoformat(recent_after.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="recent_after 必须是 ISO 时间") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


@router.get("/content/{item_id}/article-preview", response_model=ArticlePreviewResponse)
def get_article_preview(
    item_id: str,
    request: Request,
):
    """Return the captured article body as safe, locally styled reading HTML."""
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc

    if item.content_type == "forum_post" and item.source_provider == "wechat_miniprogram":
        try:
            source = load_content_source_text(item.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with connect() as connection:
            post = connection.execute(
                "SELECT author_label, display_time FROM forum_posts WHERE content_item_id = ?",
                (item.id,),
            ).fetchone()
        body_html = "".join(
            f"<p>{html.escape(paragraph)}</p>"
            for paragraph in source.text.splitlines()
            if paragraph.strip()
        )
        return ArticlePreviewResponse(
            content_item_id=item.id,
            title=item.title or "校园论坛帖子",
            author=str(post["author_label"] or "") if post else "",
            published_at=str(post["display_time"] or "") if post else "",
            html=_local_article_html(body_html, media_base_url=f"{str(request.base_url).rstrip('/')}/api/media"),
            attachments=[],
        )

    if item.source_provider == "local_file" and item.content_type == "document":
        original = original_attachment_path(item.id)
        if not original:
            raise HTTPException(status_code=404, detail="找不到保留的原始 HTML 文件")
        try:
            kind = import_kind_for_filename(original.name.removeprefix("original--"))
            if kind != "html":
                raise HTTPException(status_code=404, detail="该本地文档没有可用的 HTML 预览")
            extraction = extract_html_document(original.read_bytes(), original.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=404, detail="读取原始 HTML 文件失败") from exc
        if imported_html_needs_refresh(item.id):
            # Existing imports stored only flattened text. Upgrade the source
            # once on first open, while save_imported_document keeps any AI
            # summary and Q&A sections the user already has.
            save_imported_document(
                item,
                body=extraction.text,
                kind="html",
                original_filename=original.name.removeprefix("original--"),
            )
        media_base_url = f"{str(request.base_url).rstrip('/')}/api/media"
        return ArticlePreviewResponse(
            content_item_id=item.id,
            title=extraction.title or item.title or "未命名 HTML 文档",
            html=_local_article_html(extraction.body_html, media_base_url=media_base_url),
            source_html=build_local_html_source_preview(
                extraction.raw_html,
                source_url=extraction.source_url,
            ),
        )

    if item.source_provider == "xiaohongshu" and item.content_type == "article" and item.source_url:
        article_info = read_cache_meta(cache_dir_for_url(item.source_url)).get("article_info") or {}
        if not article_info:
            raise HTTPException(status_code=404, detail="小红书图文尚未采集完成")
        media_base_url = f"{str(request.base_url).rstrip('/')}/api/media"
        gallery = []
        for entry in list(article_info.get("xhs_gallery") or []):
            if not isinstance(entry, dict):
                continue
            local_path = str(entry.get("cached_path") or "")
            gallery.append({
                "index": int(entry.get("index") or len(gallery) + 1),
                "url": f"{media_base_url}?path={quote(local_path, safe='')}" if local_path else str(entry.get("source_url") or ""),
                "ocr_status": str(entry.get("ocr_status") or ""),
                "ocr_text": str(entry.get("ocr_text") or ""),
            })
        body_html = str(article_info.get("body_html") or "").strip()
        # Tags are a presentation aid for the author-written note description
        # only.  Re-render from the stored description when available; the
        # fallback keeps existing local captures compatible without applying
        # badges to OCR text or image annotations.
        description = str(article_info.get("description") or _xiaohongshu_description_from_html(body_html)).strip()
        body_html = render_xiaohongshu_description_html(description)
        return ArticlePreviewResponse(
            content_item_id=item.id,
            title=str(article_info.get("title") or item.title or "小红书图文"),
            author=str(article_info.get("author") or item.source_name or ""),
            published_at=str(article_info.get("published_at") or item.published_at or ""),
            html=_local_article_html(body_html or "<p>这篇笔记未提供文字描述。</p>", media_base_url=media_base_url),
            gallery=gallery,
            stats={key: int(value or 0) for key, value in dict(article_info.get("stats") or {}).items()},
            tags=[str(tag) for tag in list(article_info.get("tags") or []) if str(tag).strip()],
        )

    if item.content_type != "article" or item.source_provider not in {"wechat", "campus", "rss"} or not item.source_url:
        raise HTTPException(status_code=404, detail="该内容没有可用的文章预览")

    cache_dir = cache_dir_for_url(item.source_url)
    article_info = read_cache_meta(cache_dir).get("article_info") or {}
    body_html = str(article_info.get("body_html") or "").strip()
    normalized_html = str(article_info.get("normalized_html") or "").strip()
    readiness = inspect_content_text_readiness(item)
    needs_capture = not body_html and not normalized_html
    needs_document_refresh = readiness.label in {"正文待更新", "正文待优化"}
    if needs_capture or needs_document_refresh:
        try:
            # Opening an imported article is a direct user action. Fetching
            # its body here is safe and avoids requiring a full AI pipeline first.
            # This also upgrades legacy procurement placeholders and OCR
            # snapshots that did not retain structured document Markdown.
            load_content_source_text(item.id)
        except ValueError as exc:
            # Image- or attachment-only notices are still valid previews even
            # though they do not contain enough text for AI analysis. The
            # capture service writes their HTML before reporting that state.
            article_info = read_cache_meta(cache_dir).get("article_info") or {}
            has_captured_html = any(
                str(article_info.get(key) or "").strip()
                for key in ("body_html", "normalized_html")
            )
            if not has_captured_html:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        article_info = read_cache_meta(cache_dir).get("article_info") or {}
        body_html = str(article_info.get("body_html") or "").strip()
        normalized_html = str(article_info.get("normalized_html") or "").strip()

    body_text = str(article_info.get("body_text") or "").strip()
    document_markdown = str(article_info.get("document_markdown") or "").strip()
    formatting_status = "not_applicable"
    formatting_detail = ""
    normalized_version = article_info.get("normalized_html_version")
    if document_markdown:
        formatting = request_document_formatting(item.id, item.source_url, document_markdown)
        formatting_status = str(formatting.get("status") or "not_applicable")
        formatting_detail = str(formatting.get("detail") or "")
        preview_markdown = str(formatting.get("formatted_markdown") or document_markdown)
        preview_html = render_document_markdown_html(preview_markdown)
    elif _is_legacy_document_markdown_preview(article_info, body_html):
        # Older procurement captures escaped PaddleOCR's Markdown line by
        # line. Re-rendering their cached source text makes headings and
        # embedded HTML tables usable immediately, without another OCR call.
        preview_html = render_document_markdown_html(body_text)
    elif body_html and normalized_version != ARTICLE_NORMALIZER_VERSION:
        # Old captures are normalized by the renderer on demand. Avoid writing
        # from this GET endpoint because OCR or a refresh may update the same
        # article metadata concurrently.
        preview_html = body_html
    else:
        preview_html = normalized_html or body_html

    if not preview_html:
        if not body_text:
            raise HTTPException(status_code=404, detail="未找到可预览的文章正文")
        preview_html = "".join(
            f"<p>{html.escape(paragraph)}</p>"
            for paragraph in body_text.splitlines()
            if paragraph.strip()
        )

    published_at = str(article_info.get("published_at") or "")
    if (
        item.source_provider == "wechat"
        and article_info.get("published_at_parser_version") != PUBLISHED_AT_PARSER_VERSION
        and re.fullmatch(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", published_at)
    ):
        # Older WeChat captures always preferred the hidden epoch timestamp,
        # even though the article UI only exposed minute precision.
        published_at = published_at[:16]

    return ArticlePreviewResponse(
        content_item_id=item.id,
        title=str(article_info.get("title") or item.title or "未命名文章"),
        author=str(article_info.get("author") or ""),
        published_at=published_at,
        html=_local_article_html(
            preview_html,
            media_base_url=f"{str(request.base_url).rstrip('/')}/api/media",
        ),
        attachments=_safe_article_attachments(
            article_info.get("attachments"),
            filter_campus_navigation=item.source_provider == "campus",
        ),
        formatting_status=formatting_status,
        formatting_detail=formatting_detail,
    )


def _xiaohongshu_description_from_html(body_html: str) -> str:
    """Recover legacy XHS descriptions without ever reading OCR sidecars."""
    paragraphs = re.sub(r"</(?:p|div|section)\s*>", "\n", str(body_html or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", paragraphs)
    return html.unescape(text).strip()


def _is_legacy_document_markdown_preview(article_info: dict, body_html: str) -> bool:
    """Identify OCR captures made before Markdown was rendered as HTML."""
    document_ocr = article_info.get("document_ocr")
    if not isinstance(document_ocr, dict) or not document_ocr:
        return False
    return bool(re.search(r"&lt;/?(?:table|thead|tbody|tr|td|th)\b", body_html, re.IGNORECASE))


def _safe_article_attachments(
    value: object,
    *,
    filter_campus_navigation: bool = False,
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value[:100]:
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "").strip()
        if not url.startswith(("https://", "http://")) or url in seen:
            continue
        name = str(raw.get("name") or "未命名附件").strip()[:300] or "未命名附件"
        if filter_campus_navigation and is_campus_attachment_blacklisted(name):
            continue
        seen.add(url)
        attachments.append(
            {
                "name": name,
                "url": url,
                "download_type": "direct" if raw.get("download_type") == "direct" else "external",
            }
        )
    return attachments


@router.get("/content/{item_id}/text-readiness", response_model=ContentTextReadinessResponse)
async def get_content_text_readiness(item_id: str):
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
    return _readiness_response(inspect_content_text_readiness(item))


@router.post("/content/{item_id}/source-text/refresh", response_model=ContentTextReadinessResponse)
def refresh_content_source_text(item_id: str):
    """Retry article text capture on an explicit user action, never via listing."""
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc

    if item.source_provider not in {"wechat", "campus", "rss"} or item.content_type != "article":
        raise HTTPException(status_code=400, detail="仅已支持的文章来源可以重新抓取正文")
    try:
        load_content_source_text(item.id, refresh=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _readiness_response(inspect_content_text_readiness(item))


@router.get("/content/{item_id}/ai-calls", response_model=list[AICallUsageResponse])
async def get_content_ai_calls(item_id: str):
    initialize_database()
    with connect() as connection:
        try:
            ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        rows = connection.execute(
            """
            SELECT call_type, provider, model, usage_unit,
                   prompt_tokens, completion_tokens, prompt_cache_hit_tokens,
                   prompt_cache_miss_tokens, estimated_cost, elapsed_seconds,
                   image_count, unit_price_cny, billing_region, request_id,
                   image_width, image_height
            FROM ai_calls
            WHERE content_item_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (item_id,),
        ).fetchall()
    return [
        AICallUsageResponse(
            call_type=row["call_type"],
            provider=row["provider"],
            model=row["model"],
            usage_unit=str(row["usage_unit"] or "tokens"),
            prompt_tokens=row["prompt_tokens"],
            completion_tokens=row["completion_tokens"],
            total_tokens=(row["prompt_tokens"] + row["completion_tokens"])
            if row["prompt_tokens"] is not None and row["completion_tokens"] is not None
            else None,
            prompt_cache_hit_tokens=row["prompt_cache_hit_tokens"],
            prompt_cache_miss_tokens=row["prompt_cache_miss_tokens"],
            estimated_cost=row["estimated_cost"],
            elapsed_seconds=row["elapsed_seconds"],
            image_count=int(row["image_count"] or 0),
            unit_price_cny=row["unit_price_cny"],
            billing_region=row["billing_region"],
            request_id=row["request_id"],
            image_width=row["image_width"],
            image_height=row["image_height"],
        )
        for row in rows
    ]


@router.get("/ai-calls/summary", response_model=AICallSummaryResponse)
async def get_ai_call_summary():
    initialize_database()
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = local_midnight.astimezone(timezone.utc).isoformat()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT call_type,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(prompt_cache_hit_tokens), 0) AS prompt_cache_hit_tokens,
                   COALESCE(SUM(prompt_cache_miss_tokens), 0) AS prompt_cache_miss_tokens,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   SUM(CASE WHEN prompt_tokens IS NULL OR completion_tokens IS NULL THEN 1 ELSE 0 END) AS unreported_count
            FROM ai_calls
            WHERE created_at >= ? AND error IS NULL AND usage_unit='tokens'
            GROUP BY call_type
            ORDER BY call_count DESC, call_type ASC
            """,
            (period_start,),
        ).fetchall()
        model_rows = connection.execute(
            """
            SELECT provider,
                   model,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                   COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                   COALESCE(SUM(prompt_cache_hit_tokens), 0) AS prompt_cache_hit_tokens,
                   COALESCE(SUM(prompt_cache_miss_tokens), 0) AS prompt_cache_miss_tokens,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   SUM(CASE WHEN prompt_tokens IS NULL OR completion_tokens IS NULL THEN 1 ELSE 0 END) AS unreported_count
            FROM ai_calls
            WHERE created_at >= ? AND error IS NULL AND usage_unit='tokens'
            GROUP BY provider, model
            ORDER BY call_count DESC, provider ASC, model ASC
            """,
            (period_start,),
        ).fetchall()
        image_model_rows = connection.execute(
            """
            SELECT provider,
                   model,
                   COUNT(*) AS call_count,
                   COALESCE(SUM(image_count), 0) AS image_count,
                   COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                   MAX(unit_price_cny) AS unit_price_cny,
                   MAX(billing_region) AS billing_region
            FROM ai_calls
            WHERE created_at >= ? AND error IS NULL AND usage_unit='images'
            GROUP BY provider, model
            ORDER BY image_count DESC, provider ASC, model ASC
            """,
            (period_start,),
        ).fetchall()
    by_type = []
    prompt_tokens = 0
    completion_tokens = 0
    prompt_cache_hit_tokens = 0
    prompt_cache_miss_tokens = 0
    call_count = 0
    unreported_count = 0
    estimated_cost = 0.0
    for row in rows:
        row_prompt = int(row["prompt_tokens"] or 0)
        row_completion = int(row["completion_tokens"] or 0)
        row_cache_hit = int(row["prompt_cache_hit_tokens"] or 0)
        row_cache_miss = int(row["prompt_cache_miss_tokens"] or 0)
        row_calls = int(row["call_count"] or 0)
        row_unreported = int(row["unreported_count"] or 0)
        prompt_tokens += row_prompt
        completion_tokens += row_completion
        prompt_cache_hit_tokens += row_cache_hit
        prompt_cache_miss_tokens += row_cache_miss
        call_count += row_calls
        unreported_count += row_unreported
        estimated_cost += float(row["estimated_cost"] or 0)
        by_type.append(AICallSummaryItem(
            call_type=str(row["call_type"] or "unknown"),
            call_count=row_calls,
            total_tokens=row_prompt + row_completion,
            prompt_cache_hit_tokens=row_cache_hit,
            prompt_cache_miss_tokens=row_cache_miss,
            unreported_count=row_unreported,
        ))
    by_model = [
        AICallModelSummaryItem(
            provider=str(row["provider"] or "unknown"),
            model=str(row["model"] or "unknown"),
            call_count=int(row["call_count"] or 0),
            prompt_tokens=int(row["prompt_tokens"] or 0),
            completion_tokens=int(row["completion_tokens"] or 0),
            total_tokens=int(row["prompt_tokens"] or 0) + int(row["completion_tokens"] or 0),
            prompt_cache_hit_tokens=int(row["prompt_cache_hit_tokens"] or 0),
            prompt_cache_miss_tokens=int(row["prompt_cache_miss_tokens"] or 0),
            estimated_cost=round(float(row["estimated_cost"] or 0), 8),
            unreported_count=int(row["unreported_count"] or 0),
        )
        for row in model_rows
    ]
    by_image_model = [
        ImageCallModelSummaryItem(
            provider=str(row["provider"] or "unknown"),
            model=str(row["model"] or "unknown"),
            call_count=int(row["call_count"] or 0),
            image_count=int(row["image_count"] or 0),
            estimated_cost=round(float(row["estimated_cost"] or 0), 8),
            unit_price_cny=float(row["unit_price_cny"]) if row["unit_price_cny"] is not None else None,
            billing_region=str(row["billing_region"] or "") or None,
        )
        for row in image_model_rows
    ]
    image_call_count = sum(item.call_count for item in by_image_model)
    image_count = sum(item.image_count for item in by_image_model)
    image_estimated_cost = sum(item.estimated_cost for item in by_image_model)
    return AICallSummaryResponse(
        period_start=period_start,
        call_count=call_count,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        prompt_cache_hit_tokens=prompt_cache_hit_tokens,
        prompt_cache_miss_tokens=prompt_cache_miss_tokens,
        estimated_cost=round(estimated_cost, 8),
        unreported_count=unreported_count,
        by_type=by_type,
        by_model=by_model,
        image_call_count=image_call_count,
        image_count=image_count,
        image_estimated_cost=round(image_estimated_cost, 8),
        by_image_model=by_image_model,
    )


@router.get("/ocr-calls", response_model=list[OcrCallResponse])
async def list_ocr_calls(limit: int = 100, content_item_id: str | None = None):
    initialize_database()
    bounded_limit = max(1, min(limit, 500))
    with connect() as connection:
        if content_item_id:
            rows = connection.execute(
                """
                SELECT content_item_id, image_url, image_bytes, model, status,
                       cloud_submitted, retry_count, elapsed_seconds, error, created_at
                FROM ocr_calls
                WHERE content_item_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (content_item_id, bounded_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT content_item_id, image_url, image_bytes, model, status,
                       cloud_submitted, retry_count, elapsed_seconds, error, created_at
                FROM ocr_calls
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
    return [
        OcrCallResponse(
            content_item_id=row["content_item_id"],
            image_url=str(row["image_url"]),
            image_bytes=int(row["image_bytes"] or 0),
            model=str(row["model"]),
            status=str(row["status"]),
            cloud_submitted=bool(row["cloud_submitted"]),
            retry_count=int(row["retry_count"] or 0),
            elapsed_seconds=float(row["elapsed_seconds"] or 0),
            error=str(row["error"] or ""),
            created_at=str(row["created_at"]),
        )
        for row in rows
    ]


@router.get("/content/folders", response_model=list[LibraryFolderResponse])
async def list_library_folders():
    initialize_database()
    # The library sidebar commonly loads folders before content.  Ensure the
    # pre-created campus source folders are visible in that first response.
    ensure_content_index_ready()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT folder.*,
                   (
                     SELECT CASE binding.source_type
                       WHEN 'provider_root' THEN 'provider:' || binding.source_key
                       WHEN 'manual_collection' THEN 'manual:' || binding.source_key
                       WHEN 'external_markdown' THEN 'external'
                     END
                     FROM library_source_folder_bindings AS binding
                     WHERE binding.folder_id = folder.id
                       AND binding.source_type IN ('provider_root', 'manual_collection', 'external_markdown')
                     ORDER BY CASE binding.source_type
                       WHEN 'provider_root' THEN 0
                       WHEN 'manual_collection' THEN 1
                       ELSE 2
                     END
                     LIMIT 1
                   ) AS presentation_group
            FROM library_folders AS folder
            WHERE folder.deleted_at IS NULL
            ORDER BY folder.sort_order ASC, folder.created_at ASC
            """
        ).fetchall()
        direct_count_rows = connection.execute(
            """
            SELECT library_folder_id, COUNT(*) AS content_count
            FROM content_items
            WHERE deleted_at IS NULL
              AND library_visible = 1
              AND library_folder_id IS NOT NULL
            GROUP BY library_folder_id
            """
        ).fetchall()

    # Folder rows are intentionally tiny, while the count must include all
    # descendants so a collapsed source still communicates its real scope.
    # Aggregate grouped counts in Python instead of joining every content row
    # into the startup response.
    folders_by_id = {str(row["id"]): row for row in rows}
    children_by_parent: dict[str, list[str]] = {}
    for row in rows:
        parent_id = row["parent_folder_id"]
        if parent_id and str(parent_id) in folders_by_id:
            children_by_parent.setdefault(str(parent_id), []).append(str(row["id"]))
    direct_counts = {str(row["library_folder_id"]): int(row["content_count"] or 0) for row in direct_count_rows}
    aggregate_counts: dict[str, int] = {}

    def count_descendants(folder_id: str, visiting: set[str] | None = None) -> int:
        if folder_id in aggregate_counts:
            return aggregate_counts[folder_id]
        active = visiting or set()
        if folder_id in active:
            return direct_counts.get(folder_id, 0)
        active.add(folder_id)
        total = direct_counts.get(folder_id, 0)
        total += sum(count_descendants(child_id, active) for child_id in children_by_parent.get(folder_id, []))
        active.remove(folder_id)
        aggregate_counts[folder_id] = total
        return total

    return [_folder_response(row, content_count=count_descendants(str(row["id"]))) for row in rows]


@router.get("/content/folders/{folder_id}/items", response_model=FolderContentPageResponse)
def list_library_folder_content(
    folder_id: str,
    limit: int = Query(80, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Fetch article rows only after the user expands one sidebar folder."""
    initialize_database()
    ensure_content_index_ready()
    with connect() as connection:
        _ensure_folder_exists(connection, folder_id)
        repository = ContentRepository(connection)
        items = repository.list_folder_content_items(folder_id, limit=limit, offset=offset)
        total = repository.count_folder_content_items(folder_id)
    responses = [_item_to_response(item, include_runtime_details=False) for item in items]
    return FolderContentPageResponse(
        items=responses,
        total=total,
        offset=offset,
        has_more=offset + len(responses) < total,
    )


@router.get("/content/folders/{folder_id}/history", response_model=FolderHistoryPageResponse)
def list_library_folder_history(
    folder_id: str,
    limit: int = Query(80, ge=1, le=200),
    offset: int = Query(0, ge=0),
    history_before: str | None = None,
):
    """Page only the archive portion of one explicit folder.

    The same cutoff is returned and accepted on later pages so an archive
    paging session cannot drift into the recent startup window.
    """
    cutoff = _library_recent_cutoff(include_history=False, recent_after=history_before)
    assert cutoff is not None
    initialize_database()
    ensure_content_index_ready()
    with connect() as connection:
        _ensure_folder_exists(connection, folder_id)
        repository = ContentRepository(connection)
        items = repository.list_folder_history_content_items(
            folder_id,
            published_before=cutoff,
            limit=limit,
            offset=offset,
        )
        total = repository.count_folder_history_content_items(folder_id, published_before=cutoff)
    responses = [_item_to_response(item, include_runtime_details=False) for item in items]
    return FolderHistoryPageResponse(
        items=responses,
        total=total,
        offset=offset,
        has_more=offset + len(responses) < total,
        history_before=cutoff,
    )


@router.get("/content/source-groups")
async def list_source_groups():
    return list_library_source_groups()


@router.delete("/content/source-groups/{group_id}/sources/{source_kind}/{source_id}")
async def remove_source_group_member(group_id: str, source_kind: str, source_id: str):
    """Unlink a source from a virtual library group, retaining all content."""
    try:
        return remove_library_source_group_member(group_id, source_kind, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/content/import-markdown", response_model=ContentItemResponse)
async def import_markdown_document(
    file: UploadFile = File(...),
    library_folder_id: str | None = Form(default=None),
):
    filename = str(file.filename or "").strip()
    if not filename.lower().endswith((".md", ".markdown")):
        raise HTTPException(status_code=400, detail="请选择 Markdown 文件")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Markdown 文件为空")
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="单个 Markdown 文件不能超过 8 MB")
    try:
        markdown = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Markdown 文件需要使用 UTF-8 编码") from exc
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="Markdown 文件为空")

    title = _markdown_import_title(markdown, filename)
    content_hash = hashlib.sha256(raw).hexdigest()
    canonical_id = f"local-markdown:{content_hash}"
    initialize_database()
    with connect() as connection:
        external_root_id = ensure_external_markdown_folder(connection)
        target_folder_id = external_root_id
        if library_folder_id:
            _ensure_folder_exists(connection, library_folder_id)
            if library_folder_id != external_root_id and not _is_descendant_folder(
                connection,
                library_folder_id,
                external_root_id,
            ):
                raise HTTPException(status_code=400, detail="导入 Markdown 只能存入“外部导入”文件夹或其子文件夹")
            target_folder_id = library_folder_id
        repository = ContentRepository(connection)
        existing = repository.find_by_canonical_id(
            source_provider="local_markdown",
            canonical_source_id=canonical_id,
        )
        if existing:
            item = existing
        else:
            item = repository.create_content_item(
                source_provider="local_markdown",
                content_type="document",
                canonical_source_id=canonical_id,
                title=title,
                status="to_read",
                library_folder_id=target_folder_id,
                source_name="本地 Markdown",
            )
        connection.commit()

    save_markdown_draft_and_sync(
        markdown=markdown,
        title=title,
        obsidian_path=settings.obsidian_vault / "导入 Markdown" / f"{item.id}.md",
        content_item_id=item.id,
    )
    upsert_source_text_document(content_key=item.id, title=item.title, transcript=markdown)
    return _item_to_response(item)


@router.post("/content/import-file", response_model=LocalFileImportResponse)
async def import_local_file(
    file: UploadFile = File(...),
    library_folder_id: str | None = Form(default=None),
):
    """Import one local source while retaining its original managed attachment.

    Text-first formats become readable immediately. PDFs and videos create a
    durable task and a visible placeholder item before expensive OCR/ASR work.
    """
    incoming_filename = str(file.filename or "")
    try:
        filename = safe_import_filename(incoming_filename)
        kind = import_kind_for_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw: bytes | None = None
    staged_media: Path | None = None
    media_size = 0
    content_hash = ""
    if kind in {"video", "audio"}:
        staged_media = settings.data_dir / "import_staging" / f"{uuid.uuid4().hex}-{filename}"
        staged_media.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        try:
            with staged_media.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    media_size += len(chunk)
                    maximum = 4 * 1024 * 1024 * 1024 if kind == "video" else 2 * 1024 * 1024 * 1024
                    if media_size > maximum:
                        raise ValueError("视频不能超过 4 GB" if kind == "video" else "音频不能超过 2 GB")
                    digest.update(chunk)
                    output.write(chunk)
            if not media_size:
                raise ValueError("导入文件为空")
            content_hash = digest.hexdigest()
        except ValueError as exc:
            staged_media.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raw = await file.read()
        try:
            filename, kind = validate_import_upload(filename, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        content_hash = hashlib.sha256(raw).hexdigest()

    extracted_text = ""
    title = Path(filename).stem
    if kind not in {"pdf", "video", "audio", "image"}:
        try:
            extracted_text, extracted_title = extract_document_text(raw or b"", filename=filename, kind=kind)
            title = extracted_title or title
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    canonical_id = f"local-file:{content_hash}"
    source_name = {
        "html": "外部 HTML",
        "docx": "外部 Word",
        "pdf": "外部 PDF",
        "video": "外部视频",
        "audio": "外部音频",
        "image": "外部图片",
        "markdown": "外部 Markdown",
        "text": "外部文本",
    }[kind]
    initialize_database()
    with connect() as connection:
        external_root_id = ensure_external_markdown_folder(connection)
        target_folder_id = external_root_id
        if library_folder_id:
            _ensure_folder_exists(connection, library_folder_id)
            if library_folder_id != external_root_id and not _is_descendant_folder(connection, library_folder_id, external_root_id):
                raise HTTPException(status_code=400, detail="外部文件只能存入“外部导入”文件夹或其子文件夹")
            target_folder_id = library_folder_id
        repository = ContentRepository(connection)
        existing = repository.find_by_canonical_id(source_provider="local_file", canonical_source_id=canonical_id)
        if existing:
            if staged_media:
                staged_media.unlink(missing_ok=True)
            return LocalFileImportResponse(item=_item_to_response(existing))
        item = repository.create_content_item(
            source_provider="local_file",
            content_type=kind if kind in {"video", "audio", "image"} else "document",
            source_url=canonical_id,
            canonical_source_id=canonical_id,
            title=title[:160],
            status="processing" if kind in {"pdf", "video", "audio", "image"} else "to_read",
            library_folder_id=target_folder_id,
            source_name=source_name,
        )
        connection.commit()

    try:
        if staged_media:
            original_path = persist_original_attachment_from_file(
                content_item_id=item.id,
                filename=filename,
                source=staged_media,
                mime_type=str(file.content_type or "application/octet-stream"),
                size_bytes=media_size,
            )
        else:
            original_path = persist_original_attachment(
                content_item_id=item.id,
                filename=filename,
                raw=raw or b"",
                mime_type=str(file.content_type or "application/octet-stream"),
            )
    except Exception:
        if staged_media:
            staged_media.unlink(missing_ok=True)
        raise

    if kind in {"markdown", "text", "html", "docx"}:
        save_imported_document(item, body=extracted_text, kind=kind, original_filename=filename)
        return LocalFileImportResponse(item=_item_to_response(item))

    request = PipelineRequest(
        content_item_id=item.id,
        local_video_path=str(original_path) if kind in {"video", "audio"} else None,
        local_document_path=str(original_path) if kind in {"pdf", "image"} else None,
        local_document_kind=kind if kind in {"pdf", "image"} else None,
        source_title=item.title,
        source_url=item.source_url,
        use_cache=False,
        processing_mode="full",
        manual_collection=False,
        priority=100,
        execution_mode="foreground",
    )
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    task = task_manager.create(request, task_type="process_video" if kind in {"video", "audio"} else "import_document")
    return LocalFileImportResponse(item=_item_to_response(item), task_id=task.task_id, processing=True)


@router.post("/content/{content_item_id}/reprocess-local-source", response_model=LocalFileImportResponse)
async def reprocess_local_source(content_item_id: str):
    """Re-run extraction/OCR/ASR from the retained local original.

    The original stays immutable; ``save_imported_document`` preserves existing
    summaries and Q&A when only the source material is refreshed.
    """
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    if item.source_provider != "local_file":
        raise HTTPException(status_code=400, detail="只有外部导入资料可以重新处理")
    original = original_attachment_path(item.id)
    if not original:
        raise HTTPException(status_code=404, detail="找不到保留的原始文件")
    try:
        kind = import_kind_for_filename(original.name.removeprefix("original--"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="原始文件格式不支持重新处理") from exc

    if kind in {"markdown", "text", "html", "docx"}:
        try:
            body, _ = extract_document_text(original.read_bytes(), filename=original.name, kind=kind)
            save_imported_document(item, body=body, kind=kind, original_filename=original.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return LocalFileImportResponse(item=_item_to_response(item))

    request = PipelineRequest(
        content_item_id=item.id,
        local_video_path=str(original) if kind in {"video", "audio"} else None,
        local_document_path=str(original) if kind in {"pdf", "image"} else None,
        local_document_kind=kind if kind in {"pdf", "image"} else None,
        source_title=item.title,
        source_url=item.source_url,
        use_cache=False,
        processing_mode="full",
        priority=100,
        execution_mode="foreground",
    )
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    task = task_manager.create(request, task_type="process_video" if kind in {"video", "audio"} else "import_document")
    return LocalFileImportResponse(item=_item_to_response(item), task_id=task.task_id, processing=True)


@router.post("/content/folders", response_model=LibraryFolderResponse)
async def create_library_folder(req: FolderCreateRequest):
    initialize_database()
    folder_id = new_id()
    now = utc_now_iso()
    try:
        with connect() as connection:
            if req.parent_folder_id:
                _ensure_folder_exists(connection, req.parent_folder_id)
            connection.execute(
                """
                INSERT INTO library_folders (
                    id, name, parent_folder_id, sort_order, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (folder_id, req.name.strip(), req.parent_folder_id, req.sort_order, now, now),
            )
            connection.commit()
            row = connection.execute("SELECT * FROM library_folders WHERE id = ?", (folder_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="文件夹位置无效") from exc
    ensure_library_folder_directory(folder_id)
    return _folder_response(row)


@router.get("/content/folders/{folder_id}/location", response_model=LibraryFolderLocationResponse)
async def get_library_folder_location(folder_id: str):
    """Resolve the local directory represented by a visible library folder."""
    try:
        return LibraryFolderLocationResponse(path=str(ensure_library_folder_directory(folder_id)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="文件夹不存在或已删除") from exc


@router.patch("/content/folders/{folder_id}", response_model=LibraryFolderResponse)
async def update_library_folder(folder_id: str, req: FolderUpdateRequest):
    initialize_database()
    try:
        with connect() as connection:
            current = _ensure_folder_exists(connection, folder_id)
            old_folder_path = ensure_library_folder_directory(folder_id)
            fields = req.model_fields_set
            next_parent_id = req.parent_folder_id if "parent_folder_id" in fields else current["parent_folder_id"]
            next_sort_order = req.sort_order if "sort_order" in fields else current["sort_order"]
            next_is_pinned = req.is_pinned if "is_pinned" in fields else bool(current["is_pinned"])
            if next_parent_id:
                _ensure_folder_exists(connection, next_parent_id)
                if next_parent_id == folder_id or _is_descendant_folder(connection, next_parent_id, folder_id):
                    raise HTTPException(status_code=400, detail="不能移动到自身或子文件夹")
            connection.execute(
                """
                UPDATE library_folders
                SET name = ?,
                    parent_folder_id = ?,
                    sort_order = ?,
                    is_pinned = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    current["name"] if req.name is None else req.name.strip(),
                    next_parent_id,
                    next_sort_order,
                    int(bool(next_is_pinned)),
                    utc_now_iso(),
                    folder_id,
                ),
            )
            connection.commit()
            folder_ids = _folder_tree_ids(connection, folder_id)
            placeholders = ",".join("?" for _ in folder_ids)
            content_rows = connection.execute(
                f"SELECT id FROM content_items WHERE library_folder_id IN ({placeholders}) AND deleted_at IS NULL",
                folder_ids,
            ).fetchall()
            row = connection.execute("SELECT * FROM library_folders WHERE id = ?", (folder_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="文件夹位置无效") from exc
    ensure_library_folder_directory(folder_id)
    relocate_managed_documents([str(content["id"]) for content in content_rows])
    remove_empty_library_folder_directory(old_folder_path)
    return _folder_response(row)


@router.delete("/content/folders/{folder_id}", response_model=dict)
async def delete_library_folder(folder_id: str):
    initialize_database()
    with connect() as connection:
        _ensure_folder_exists(connection, folder_id)
        folder_ids = _folder_tree_ids(connection, folder_id)
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            deleted_at = utc_now_iso()
            batch_id = new_id()
            connection.execute(
                f"UPDATE library_folders SET deleted_at = ?, trash_batch_id = ?, updated_at = ? WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                (deleted_at, batch_id, deleted_at, *folder_ids),
            )
            connection.execute(
                f"UPDATE content_items SET deleted_at = ?, trash_batch_id = ?, updated_at = ? WHERE library_folder_id IN ({placeholders}) AND deleted_at IS NULL",
                (deleted_at, batch_id, deleted_at, *folder_ids),
            )
        connection.commit()
    return {"success": True}


@router.get("/content/trash", response_model=list[TrashEntryResponse])
async def list_library_trash():
    initialize_database()
    with connect() as connection:
        folders = connection.execute(
            """
            SELECT folder.id, folder.name, folder.deleted_at
            FROM library_folders AS folder
            LEFT JOIN library_folders AS parent ON parent.id = folder.parent_folder_id
            WHERE folder.deleted_at IS NOT NULL
              AND (parent.id IS NULL OR parent.deleted_at IS NULL)
            ORDER BY folder.deleted_at DESC
            """
        ).fetchall()
        items = connection.execute(
            """
            SELECT item.id, item.title AS name, item.deleted_at,
                   item.content_type, item.source_provider
            FROM content_items AS item
            LEFT JOIN library_folders AS folder ON folder.id = item.library_folder_id
            WHERE item.deleted_at IS NOT NULL
              AND (folder.id IS NULL OR folder.deleted_at IS NULL)
            ORDER BY item.deleted_at DESC
            """
        ).fetchall()
    entries = [TrashEntryResponse(id=row["id"], entry_type="folder", name=row["name"], deleted_at=row["deleted_at"]) for row in folders]
    entries.extend(
        TrashEntryResponse(
            id=row["id"],
            entry_type="content",
            name=row["name"],
            deleted_at=row["deleted_at"],
            content_type=row["content_type"],
            source_provider=row["source_provider"],
        )
        for row in items
    )
    return sorted(entries, key=lambda entry: entry.deleted_at, reverse=True)


@router.delete("/content/trash", response_model=dict)
async def empty_library_trash():
    """Permanently remove every soft-deleted library item and folder."""
    initialize_database()
    cleanup_plans: list[ContentDeleteCleanup] = []
    with connect() as connection:
        repository = ContentRepository(connection)
        content_rows = connection.execute(
            "SELECT * FROM content_items WHERE deleted_at IS NOT NULL"
        ).fetchall()
        for content_row in content_rows:
            cleanup_plans.append(
                _delete_content_item_data(connection, repository, _content_row_to_record(content_row))
            )
        deleted_folder_count = int(connection.execute(
            "SELECT COUNT(*) FROM library_folders WHERE deleted_at IS NOT NULL"
        ).fetchone()[0])
        connection.execute("DELETE FROM library_folders WHERE deleted_at IS NOT NULL")
        connection.commit()
    for plan in cleanup_plans:
        _cleanup_content_files_after_commit(plan)
    return {
        "success": True,
        "deleted_content_count": len(cleanup_plans),
        "deleted_folder_count": deleted_folder_count,
    }


@router.post("/content/trash/{entry_type}/{entry_id}/restore", response_model=dict)
async def restore_library_trash_entry(entry_type: str, entry_id: str):
    initialize_database()
    if entry_type not in {"folder", "content"}:
        raise HTTPException(status_code=400, detail="不支持的回收站项目")
    with connect() as connection:
        table = "library_folders" if entry_type == "folder" else "content_items"
        row = connection.execute(f"SELECT trash_batch_id FROM {table} WHERE id = ? AND deleted_at IS NOT NULL", (entry_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="回收站项目不存在")
        batch_id = row["trash_batch_id"]
        now = utc_now_iso()
        if entry_type == "folder" and batch_id:
            connection.execute("UPDATE library_folders SET deleted_at = NULL, trash_batch_id = NULL, updated_at = ? WHERE trash_batch_id = ?", (now, batch_id))
            connection.execute("UPDATE content_items SET deleted_at = NULL, trash_batch_id = NULL, updated_at = ? WHERE trash_batch_id = ?", (now, batch_id))
        else:
            connection.execute(f"UPDATE {table} SET deleted_at = NULL, trash_batch_id = NULL, updated_at = ? WHERE id = ?", (now, entry_id))
        connection.commit()
    return {"success": True}


@router.delete("/content/trash/{entry_type}/{entry_id}", response_model=dict)
async def permanently_delete_library_trash_entry(entry_type: str, entry_id: str):
    initialize_database()
    if entry_type not in {"folder", "content"}:
        raise HTTPException(status_code=400, detail="不支持的回收站项目")
    cleanup_plans: list[ContentDeleteCleanup] = []
    with connect() as connection:
        repository = ContentRepository(connection)
        if entry_type == "content":
            row = connection.execute("SELECT * FROM content_items WHERE id = ? AND deleted_at IS NOT NULL", (entry_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="回收站项目不存在")
            cleanup_plans.append(_delete_content_item_data(connection, repository, _content_row_to_record(row)))
        else:
            row = connection.execute("SELECT id FROM library_folders WHERE id = ? AND deleted_at IS NOT NULL", (entry_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="回收站项目不存在")
            folder_ids = _folder_tree_ids(connection, entry_id)
            placeholders = ",".join("?" for _ in folder_ids)
            content_rows = connection.execute(f"SELECT * FROM content_items WHERE library_folder_id IN ({placeholders})", folder_ids).fetchall()
            for content_row in content_rows:
                cleanup_plans.append(_delete_content_item_data(connection, repository, _content_row_to_record(content_row)))
            connection.execute(f"DELETE FROM library_folders WHERE id IN ({placeholders})", folder_ids)
        connection.commit()
    for plan in cleanup_plans:
        _cleanup_content_files_after_commit(plan)
    return {"success": True}


@router.patch("/content/{item_id}/status", response_model=ContentItemResponse)
async def update_content_status(item_id: str, req: ContentStatusRequest):
    if req.status not in CONTENT_STATUSES:
        raise HTTPException(status_code=400, detail=f"不支持的内容状态: {req.status}")
    initialize_database()
    try:
        with connect() as connection:
            item = ContentRepository(connection).update_status(item_id, req.status)
            connection.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="内容不存在") from exc
    cache_entry = _cache_entries_by_source_url([item.source_url]).get(item.source_url or "", {})
    return _item_to_response(item, cache_entry)


@router.patch("/content/{item_id}", response_model=ContentItemResponse)
async def update_content_item(item_id: str, req: ContentUpdateRequest):
    initialize_database()
    try:
        with connect() as connection:
            repository = ContentRepository(connection)
            current = repository.get_content_item(item_id)
            fields = req.model_fields_set
            next_folder_id = req.library_folder_id if "library_folder_id" in fields else current.library_folder_id
            next_sort_order = req.sort_order if "sort_order" in fields else current.sort_order
            if next_folder_id:
                _ensure_folder_exists(connection, next_folder_id)
            item = repository.update_content_item(
                item_id,
                title=current.title if req.title is None else req.title.strip(),
                library_folder_id=next_folder_id,
                sort_order=next_sort_order,
            )
            connection.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="内容不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="文件夹位置无效") from exc
    relocate_managed_documents([item.id])
    cache_entry = _cache_entries_by_source_url([item.source_url]).get(item.source_url or "", {})
    return _item_to_response(item, cache_entry)


@router.delete("/content/{item_id}", response_model=dict)
async def delete_content_item(item_id: str):
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        try:
            item = repository.get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        deleted_at = utc_now_iso()
        connection.execute(
            "UPDATE content_items SET deleted_at = ?, trash_batch_id = ?, updated_at = ? WHERE id = ?",
            (deleted_at, new_id(), deleted_at, item.id),
        )
        connection.commit()
    return {"success": True}


def _cache_entries_by_source_url(source_urls) -> dict[str, dict]:
    entries: dict[str, dict] = {}
    for source_url in {str(value or "").strip() for value in source_urls}:
        if not source_url:
            continue
        # The file tree needs paths and lightweight metadata, not a recursive
        # cache-directory size scan for every row. Exact sizes are reserved for
        # the cache manager endpoint.
        entry = cache_entry_for_url(source_url, include_size=False)
        if entry:
            entries[source_url] = entry
    return entries


def _segments_for_cache_entry(cache_entry: dict, duration: float | None) -> list[dict]:
    cache_key = cache_entry.get("cache_key")
    if not cache_key:
        return []
    cache_dir = settings.data_dir / "cache" / str(cache_key)
    if not cache_dir.exists():
        return []
    transcripts = cache_entry.get("transcripts") or []
    preferred = transcripts[-1] if transcripts else None
    return read_cached_transcript_segments(
        Path(cache_dir),
        preferred_model=preferred,
        duration=duration,
    )


def _folder_response(row, *, content_count: int | None = None) -> LibraryFolderResponse:
    return LibraryFolderResponse(
        id=row["id"],
        name=row["name"],
        parent_folder_id=row["parent_folder_id"],
        sort_order=float(row["sort_order"] or 0),
        is_pinned=bool(row["is_pinned"]),
        presentation_group=(str(row["presentation_group"] or "") or None) if "presentation_group" in row.keys() else None,
        content_count=(
            int(content_count)
            if content_count is not None
            else int(row["content_count"] or 0) if "content_count" in row.keys() else 0
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _markdown_import_title(markdown: str, filename: str) -> str:
    heading = re.search(r"^\s{0,3}#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    if heading:
        title = re.sub(r"\s+#*\s*$", "", heading.group(1)).strip()
        if title:
            return title[:200]
    stem = Path(filename).stem.strip()
    return (stem or "未命名 Markdown")[:200]


def _ensure_folder_exists(connection, folder_id: str):
    row = connection.execute("SELECT * FROM library_folders WHERE id = ?", (folder_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return row


def _is_descendant_folder(connection, candidate_id: str, parent_id: str) -> bool:
    rows = connection.execute(
        """
        WITH RECURSIVE folder_tree(id) AS (
            SELECT id FROM library_folders WHERE parent_folder_id = ?
            UNION ALL
            SELECT library_folders.id
            FROM library_folders
            JOIN folder_tree ON library_folders.parent_folder_id = folder_tree.id
        )
        SELECT id FROM folder_tree WHERE id = ? LIMIT 1
        """,
        (parent_id, candidate_id),
    ).fetchall()
    return bool(rows)


def _folder_tree_ids(connection, folder_id: str) -> list[str]:
    rows = connection.execute(
        """
        WITH RECURSIVE folder_tree(id) AS (
            SELECT id FROM library_folders WHERE id = ?
            UNION ALL
            SELECT library_folders.id
            FROM library_folders
            JOIN folder_tree ON library_folders.parent_folder_id = folder_tree.id
        )
        SELECT id FROM folder_tree
        """,
        (folder_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def _content_row_to_record(row) -> ContentItemRecord:
    return ContentItemRecord(
        id=row["id"],
        content_type=row["content_type"],
        source_provider=row["source_provider"],
        source_url=row["source_url"],
        canonical_source_id=row["canonical_source_id"],
        title=row["title"],
        cover_url=row["cover_url"],
        duration_seconds=row["duration_seconds"],
        status=row["status"],
        series_id=row["series_id"],
        library_folder_id=row["library_folder_id"],
        sort_order=float(row["sort_order"] or 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@dataclass(frozen=True)
class ContentDeleteCleanup:
    markdown_paths: tuple[str, ...]
    obsidian_paths: tuple[str, ...]
    attachment_directory: Path
    report_cover_directory: Path
    cache_key: str | None


def _delete_content_item_data(
    connection,
    repository: ContentRepository,
    item: ContentItemRecord,
) -> ContentDeleteCleanup:
    # V2 relational rows cascade with the content item. FTS5 is virtual, so
    # its rows must be cleared explicitly to avoid orphaned searchable text.
    v2_chunk_rows = connection.execute(
        "SELECT id FROM knowledge_v2_chunks WHERE content_item_id = ?",
        (item.id,),
    ).fetchall()
    connection.executemany(
        "DELETE FROM knowledge_v2_search WHERE chunk_id = ?",
        [(row["id"],) for row in v2_chunk_rows],
    )
    markdown_paths = tuple(
        str(row["markdown_path"])
        for row in connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id = ?",
            (item.id,),
        ).fetchall()
        if row["markdown_path"]
    )
    obsidian_paths = tuple(
        str(row["obsidian_path"])
        for row in connection.execute(
            "SELECT obsidian_path FROM obsidian_sync WHERE content_item_id = ?",
            (item.id,),
        ).fetchall()
        if row["obsidian_path"]
    )
    connection.execute("DELETE FROM content_search WHERE content_item_id = ?", (item.id,))
    repository.delete_content_item(item.id)
    return ContentDeleteCleanup(
        markdown_paths=markdown_paths,
        obsidian_paths=obsidian_paths,
        attachment_directory=settings.data_dir / "attachments" / item.id,
        report_cover_directory=settings.data_dir / "report_covers" / item.id,
        cache_key=cache_dir_for_url(item.source_url).name if item.source_url else None,
    )


def _cleanup_content_files_after_commit(plan: ContentDeleteCleanup) -> None:
    """Delete physical artifacts only after their SQLite deletion committed.

    If this stage fails, files may remain as reclaimable orphans, but a failed
    database transaction can no longer make a recoverable item lose its source
    Markdown, attachments, or cache.
    """
    try:
        for path in plan.markdown_paths:
            _delete_data_file(path)
        _delete_data_directory(plan.attachment_directory)
        _delete_data_directory(plan.report_cover_directory)
        for path in plan.obsidian_paths:
            _delete_obsidian_note_file(path)
        if plan.cache_key:
            delete_cache_entry(plan.cache_key)
    except OSError:
        logger.exception("Post-commit content cleanup failed; files can be reclaimed later")

def _delete_data_file(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    data_dir = settings.data_dir.expanduser().resolve()
    try:
        path.relative_to(data_dir)
    except ValueError:
        return
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)


def _delete_data_directory(path_value: Path) -> None:
    path = path_value.expanduser().resolve()
    data_dir = settings.data_dir.expanduser().resolve()
    try:
        path.relative_to(data_dir)
    except ValueError:
        return
    if path.exists() and path.is_dir():
        shutil.rmtree(path)


def _delete_obsidian_note_file(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    if not is_managed_obsidian_note_path(path):
        return
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)
