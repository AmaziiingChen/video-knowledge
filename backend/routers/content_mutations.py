from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.cache import cache_entry_for_url
from services.content_presentation import ContentItemResponse, content_item_response
from services.database import connect, initialize_database, utc_now_iso
from services.knowledge_library import relocate_managed_documents
from services.library_folder_tree import require_folder
from services.repository import ContentRepository, new_id


router = APIRouter()

CONTENT_STATUSES = {"inbox", "processing", "to_read", "distilled", "archived", "failed"}


class ContentStatusRequest(BaseModel):
    status: str = Field(min_length=1)


class ContentUpdateRequest(BaseModel):
    title: str | None = None
    library_folder_id: str | None = None
    sort_order: float | None = None


def _require_folder(connection, folder_id: str):
    try:
        return require_folder(connection, folder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="文件夹不存在") from exc


def _response(item) -> ContentItemResponse:
    cache_entry = cache_entry_for_url(item.source_url or "", include_size=False)
    return content_item_response(item, cache_entry)


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
    return _response(item)


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
                _require_folder(connection, next_folder_id)
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
    return _response(item)


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
