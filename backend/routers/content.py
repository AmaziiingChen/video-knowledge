from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from services.cache import cache_entry_for_url
from services.content_index import ensure_content_index_ready
from services.content_presentation import (
    ContentItemResponse,
    content_item_response,
)
from services.database import connect, initialize_database
from services.library_folder_tree import require_folder
from services.repository import ContentRepository

router = APIRouter()

CONTENT_STATUSES = {"inbox", "processing", "to_read", "distilled", "archived", "failed"}

class ContentPageResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool
    recent_after: str | None = None


class ContentItemsResolveRequest(BaseModel):
    content_item_ids: list[str] = Field(min_length=1, max_length=300)


class FolderHistoryPageResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool
    history_before: str


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
        content_item_response(
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
    responses = [content_item_response(item, include_runtime_details=False) for item in items]
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
    return content_item_response(item, cache_entry)


@router.post("/content/items/resolve", response_model=list[ContentItemResponse])
def resolve_content_items(req: ContentItemsResolveRequest):
    """Hydrate a bounded set of explicit library records for the tree.

    This is intentionally separate from the 30-day startup listing: callers
    use it only after a user action (for example, a completed history sync).
    """
    initialize_database()
    with connect() as connection:
        items = ContentRepository(connection).list_content_items_by_ids(req.content_item_ids)
    return [content_item_response(item, include_runtime_details=False) for item in items]


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
    responses = [content_item_response(item, include_runtime_details=False) for item in items]
    return FolderHistoryPageResponse(
        items=responses,
        total=total,
        offset=offset,
        has_more=offset + len(responses) < total,
        history_before=cutoff,
    )


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


def _ensure_folder_exists(connection, folder_id: str):
    try:
        return require_folder(connection, folder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="文件夹不存在") from exc
