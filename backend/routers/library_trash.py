"""Soft-delete and recovery endpoints for the local library."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.content_deletion import (
    ContentDeleteCleanup,
    cleanup_content_files_after_commit,
    content_record_from_row,
    delete_content_item_data,
)
from services.database import connect, initialize_database, utc_now_iso
from services.repository import ContentRepository, new_id


router = APIRouter()


class TrashEntryResponse(BaseModel):
    id: str
    entry_type: str
    name: str
    deleted_at: str
    content_type: str | None = None
    source_provider: str | None = None


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
    entries = [
        TrashEntryResponse(
            id=row["id"],
            entry_type="folder",
            name=row["name"],
            deleted_at=row["deleted_at"],
        )
        for row in folders
    ]
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
                delete_content_item_data(
                    connection,
                    repository,
                    content_record_from_row(content_row),
                )
            )
        deleted_folder_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM library_folders WHERE deleted_at IS NOT NULL"
            ).fetchone()[0]
        )
        connection.execute("DELETE FROM library_folders WHERE deleted_at IS NOT NULL")
        connection.commit()
    for plan in cleanup_plans:
        cleanup_content_files_after_commit(plan)
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
        row = connection.execute(
            f"SELECT trash_batch_id FROM {table} WHERE id = ? AND deleted_at IS NOT NULL",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="回收站项目不存在")
        batch_id = row["trash_batch_id"]
        now = utc_now_iso()
        restored_content_ids: list[str] = []
        restored_folder_ids: list[str] = []
        if entry_type == "folder" and batch_id:
            restored_folder_ids = [
                str(item["id"])
                for item in connection.execute(
                    "SELECT id FROM library_folders WHERE trash_batch_id = ?",
                    (batch_id,),
                ).fetchall()
            ]
            restored_content_ids = [
                str(item["id"])
                for item in connection.execute(
                    "SELECT id FROM content_items WHERE trash_batch_id = ?",
                    (batch_id,),
                ).fetchall()
            ]
            connection.execute(
                "UPDATE library_folders SET deleted_at = NULL, trash_batch_id = NULL, "
                "updated_at = ? WHERE trash_batch_id = ?",
                (now, batch_id),
            )
            connection.execute(
                "UPDATE content_items SET deleted_at = NULL, trash_batch_id = NULL, "
                "updated_at = ? WHERE trash_batch_id = ?",
                (now, batch_id),
            )
        else:
            if entry_type == "content":
                restored_content_ids = [entry_id]
            else:
                restored_folder_ids = [entry_id]
            connection.execute(
                f"UPDATE {table} SET deleted_at = NULL, trash_batch_id = NULL, "
                "updated_at = ? WHERE id = ?",
                (now, entry_id),
            )
        connection.commit()
    return {
        "success": True,
        # The tree is progressively loaded, so a folder refresh alone cannot
        # repopulate a restored file row. Return the exact durable records for
        # the renderer to resolve and merge without reloading the whole library.
        "restored_content_ids": restored_content_ids,
        "restored_folder_ids": restored_folder_ids,
    }


@router.delete("/content/trash/{entry_type}/{entry_id}", response_model=dict)
async def permanently_delete_library_trash_entry(entry_type: str, entry_id: str):
    initialize_database()
    if entry_type not in {"folder", "content"}:
        raise HTTPException(status_code=400, detail="不支持的回收站项目")
    cleanup_plans: list[ContentDeleteCleanup] = []
    with connect() as connection:
        repository = ContentRepository(connection)
        if entry_type == "content":
            row = connection.execute(
                "SELECT * FROM content_items WHERE id = ? AND deleted_at IS NOT NULL",
                (entry_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="回收站项目不存在")
            cleanup_plans.append(
                delete_content_item_data(connection, repository, content_record_from_row(row))
            )
        else:
            row = connection.execute(
                "SELECT id FROM library_folders WHERE id = ? AND deleted_at IS NOT NULL",
                (entry_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="回收站项目不存在")
            folder_ids = _folder_tree_ids(connection, entry_id)
            placeholders = ",".join("?" for _ in folder_ids)
            content_rows = connection.execute(
                f"SELECT * FROM content_items WHERE library_folder_id IN ({placeholders})",
                folder_ids,
            ).fetchall()
            for content_row in content_rows:
                cleanup_plans.append(
                    delete_content_item_data(
                        connection,
                        repository,
                        content_record_from_row(content_row),
                    )
                )
            connection.execute(f"DELETE FROM library_folders WHERE id IN ({placeholders})", folder_ids)
        connection.commit()
    for plan in cleanup_plans:
        cleanup_content_files_after_commit(plan)
    return {"success": True}
