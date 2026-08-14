from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.obsidian_settings import (
    apply_saved_obsidian_settings,
    markdown_output_settings,
    save_obsidian_settings,
)

router = APIRouter()


class ObsidianSettingsRequest(BaseModel):
    vault_path: str = Field(min_length=1, max_length=2000)
    export_path: str | None = Field(default=None, max_length=2000)
    auto_write: bool = False
    recover_existing: bool = False


class ObsidianSettingsResponse(BaseModel):
    vault_path: str
    export_path: str
    auto_write: bool
    migrated_documents: int = 0
    migrated_attachments: int = 0
    scanned_markdown: int = 0
    recognized_documents: int = 0
    restored_documents: int = 0
    existing_documents: int = 0
    conflicted_documents: int = 0
    skipped_documents: int = 0
    restored_folders: int = 0
    scan_truncated: bool = False


@router.get("/obsidian/settings", response_model=ObsidianSettingsResponse)
def get_obsidian_settings():
    apply_saved_obsidian_settings()
    return ObsidianSettingsResponse(**markdown_output_settings())


@router.post("/obsidian/settings", response_model=ObsidianSettingsResponse)
def set_obsidian_settings(req: ObsidianSettingsRequest):
    try:
        saved = save_obsidian_settings(
            req.vault_path,
            export_path=req.export_path or req.vault_path,
            auto_write=req.auto_write,
            recover_existing=req.recover_existing,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ObsidianSettingsResponse(**saved)
