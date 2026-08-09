"""Lazy library-folder tree endpoints."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.content_index import ensure_content_index_ready
from services.content_presentation import ContentItemResponse, content_item_response
from services.database import connect, initialize_database, utc_now_iso
from services.knowledge_library import (
    ensure_library_folder_directory,
    relocate_managed_documents,
    remove_empty_library_folder_directory,
)
from services.library_folder_presentation import (
    LibraryFolderLocationResponse,
    LibraryFolderResponse,
    library_folder_response,
)
from services.library_folder_tree import folder_tree_ids, is_descendant_folder, require_folder
from services.repository import ContentRepository, new_id


router = APIRouter()


class FolderContentPageResponse(BaseModel):
    items: list[ContentItemResponse]
    total: int
    offset: int
    has_more: bool


class FolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_folder_id: str | None = None
    sort_order: float = 0


class FolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_folder_id: str | None = None
    sort_order: float | None = None
    is_pinned: bool | None = None


def _ensure_folder_exists(connection, folder_id: str):
    try:
        return require_folder(connection, folder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="文件夹不存在") from exc


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
                """INSERT INTO library_folders
                   (id, name, parent_folder_id, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (folder_id, req.name.strip(), req.parent_folder_id, req.sort_order, now, now),
            )
            connection.commit()
            row = require_folder(connection, folder_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="文件夹位置无效") from exc
    ensure_library_folder_directory(folder_id)
    return library_folder_response(row)


@router.get("/content/folders/{folder_id}/location", response_model=LibraryFolderLocationResponse)
async def get_library_folder_location(folder_id: str):
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
                if next_parent_id == folder_id or is_descendant_folder(connection, next_parent_id, folder_id):
                    raise HTTPException(status_code=400, detail="不能移动到自身或子文件夹")
            connection.execute(
                """UPDATE library_folders
                   SET name = ?, parent_folder_id = ?, sort_order = ?, is_pinned = ?, updated_at = ?
                   WHERE id = ?""",
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
            folder_ids = folder_tree_ids(connection, folder_id)
            placeholders = ",".join("?" for _ in folder_ids)
            content_rows = connection.execute(
                f"SELECT id FROM content_items WHERE library_folder_id IN ({placeholders}) AND deleted_at IS NULL",
                folder_ids,
            ).fetchall()
            row = require_folder(connection, folder_id)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail="文件夹位置无效") from exc
    ensure_library_folder_directory(folder_id)
    relocate_managed_documents([str(content["id"]) for content in content_rows])
    remove_empty_library_folder_directory(old_folder_path)
    return library_folder_response(row)


@router.delete("/content/folders/{folder_id}", response_model=dict)
async def delete_library_folder(folder_id: str):
    initialize_database()
    with connect() as connection:
        _ensure_folder_exists(connection, folder_id)
        folder_ids = folder_tree_ids(connection, folder_id)
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            deleted_at = utc_now_iso()
            batch_id = new_id()
            connection.execute(
                f"UPDATE library_folders SET deleted_at = ?, trash_batch_id = ?, updated_at = ? "
                f"WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                (deleted_at, batch_id, deleted_at, *folder_ids),
            )
            connection.execute(
                f"UPDATE content_items SET deleted_at = ?, trash_batch_id = ?, updated_at = ? "
                f"WHERE library_folder_id IN ({placeholders}) AND deleted_at IS NULL",
                (deleted_at, batch_id, deleted_at, *folder_ids),
            )
        connection.commit()
    return {"success": True}
