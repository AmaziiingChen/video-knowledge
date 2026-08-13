"""Stable API read models for the local library-folder tree."""

from __future__ import annotations

from pydantic import BaseModel


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


def library_folder_response(row, *, content_count: int | None = None) -> LibraryFolderResponse:
    return LibraryFolderResponse(
        id=row["id"],
        name=row["name"],
        parent_folder_id=row["parent_folder_id"],
        sort_order=float(row["sort_order"] or 0),
        is_pinned=bool(row["is_pinned"]),
        presentation_group=(str(row["presentation_group"] or "") or None)
        if "presentation_group" in row.keys()
        else None,
        content_count=(
            int(content_count)
            if content_count is not None
            else int(row["content_count"] or 0) if "content_count" in row.keys() else 0
        ),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
