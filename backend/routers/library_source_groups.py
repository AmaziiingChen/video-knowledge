"""Virtual library source-group endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from services.library_source_groups import list_library_source_groups, remove_library_source_group_member


router = APIRouter()


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
