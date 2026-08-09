"""Lazy library-folder tree endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.content_index import ensure_content_index_ready
from services.content_presentation import ContentItemResponse, content_item_response
from services.database import connect, initialize_database
from services.library_folder_presentation import LibraryFolderResponse, library_folder_response
from services.repository import ContentRepository


router = APIRouter()


class FolderContentPageResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool


def _ensure_folder_exists(connection, folder_id: str):
    row = connection.execute("SELECT * FROM library_folders WHERE id = ?", (folder_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return row


@router.get("/content/folders", response_model=list[LibraryFolderResponse])
async def list_library_folders():
    initialize_database()
    ensure_content_index_ready()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT folder.*,
                   (SELECT CASE binding.source_type
                       WHEN 'provider_root' THEN 'provider:' || binding.source_key
                       WHEN 'manual_collection' THEN 'manual:' || binding.source_key
                       WHEN 'external_markdown' THEN 'external'
                     END
                     FROM library_source_folder_bindings AS binding
                     WHERE binding.folder_id = folder.id
                       AND binding.source_type IN ('provider_root', 'manual_collection', 'external_markdown')
                     ORDER BY CASE binding.source_type
                       WHEN 'provider_root' THEN 0 WHEN 'manual_collection' THEN 1 ELSE 2 END
                     LIMIT 1) AS presentation_group
            FROM library_folders AS folder
            WHERE folder.deleted_at IS NULL
            ORDER BY folder.sort_order ASC, folder.created_at ASC
            """
        ).fetchall()
        count_rows = connection.execute(
            """SELECT library_folder_id, COUNT(*) AS content_count
               FROM content_items
               WHERE deleted_at IS NULL AND library_visible = 1 AND library_folder_id IS NOT NULL
               GROUP BY library_folder_id"""
        ).fetchall()
    folders_by_id = {str(row["id"]): row for row in rows}
    children_by_parent: dict[str, list[str]] = {}
    for row in rows:
        parent_id = row["parent_folder_id"]
        if parent_id and str(parent_id) in folders_by_id:
            children_by_parent.setdefault(str(parent_id), []).append(str(row["id"]))
    direct_counts = {str(row["library_folder_id"]): int(row["content_count"] or 0) for row in count_rows}
    aggregate_counts: dict[str, int] = {}

    def count_descendants(folder_id: str, visiting: set[str] | None = None) -> int:
        if folder_id in aggregate_counts:
            return aggregate_counts[folder_id]
        active = visiting or set()
        if folder_id in active:
            return direct_counts.get(folder_id, 0)
        active.add(folder_id)
        total = direct_counts.get(folder_id, 0) + sum(
            count_descendants(child_id, active)
            for child_id in children_by_parent.get(folder_id, [])
        )
        active.remove(folder_id)
        aggregate_counts[folder_id] = total
        return total

    return [
        library_folder_response(row, content_count=count_descendants(str(row["id"])))
        for row in rows
    ]


@router.get("/content/folders/{folder_id}/items", response_model=FolderContentPageResponse)
def list_library_folder_content(
    folder_id: str,
    limit: int = Query(80, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Fetch rows only after the user expands one sidebar folder."""
    initialize_database()
    ensure_content_index_ready()
    with connect() as connection:
        _ensure_folder_exists(connection, folder_id)
        repository = ContentRepository(connection)
        items = repository.list_folder_content_items(folder_id, limit=limit, offset=offset)
        total = repository.count_folder_content_items(folder_id)
    responses = [content_item_response(item, include_runtime_details=False) for item in items]
    return FolderContentPageResponse(
        items=responses,
        total=total,
        offset=offset,
        has_more=offset + len(responses) < total,
    )
