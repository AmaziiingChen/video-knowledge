from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from services.markdown_sync import (
    MarkdownSyncState,
    ensure_content_markdown_state,
    get_markdown_state,
    sync_markdown_to_obsidian,
    update_markdown_draft,
)
from services.obsidian_settings import export_markdown_document
from services.wechat_reports import hydrate_legacy_report_footnotes


router = APIRouter()


class MarkdownStateResponse(BaseModel):
    content_item_id: str | None = None
    markdown_draft_path: str
    obsidian_path: str | None = None
    markdown: str
    markdown_size_bytes: int = 0
    sync_status: str
    conflict: bool
    last_synced_hash: str | None = None
    external_hash: str | None = None
    last_synced_at: str | None = None


class MarkdownUpdateRequest(BaseModel):
    markdown: str


class MarkdownSyncRequest(BaseModel):
    force: bool = False


class MarkdownDocumentExportRequest(BaseModel):
    title: str = Field(default="AI 对话", max_length=500)
    markdown: str = Field(min_length=1, max_length=5_000_000)


class MarkdownDocumentExportResponse(BaseModel):
    path: str
    overwritten: bool


def _to_response(state: MarkdownSyncState) -> MarkdownStateResponse:
    payload = dict(state.__dict__)
    payload["markdown_size_bytes"] = _markdown_file_size(Path(state.markdown_draft_path))
    return MarkdownStateResponse(**payload)


def _markdown_file_size(path: Path) -> int:
    """Return the on-disk Markdown size without exposing its local path to the UI."""
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _with_hydrated_report_footnotes(state: MarkdownSyncState) -> MarkdownSyncState:
    if not state.content_item_id:
        return state
    return replace(
        state,
        markdown=hydrate_legacy_report_footnotes(state.content_item_id, state.markdown),
    )


@router.get("/markdown/content/{content_item_id}", response_model=MarkdownStateResponse)
async def get_content_markdown(content_item_id: str):
    try:
        # Articles, including their recovered body and image OCR text, are
        # written to the canonical Markdown library before a user ever asks
        # for an AI summary.  Those documents do not yet have an
        # ``obsidian_sync`` row, so use the promoting accessor here rather
        # than treating an already saved source document as missing.
        return _to_response(_with_hydrated_report_footnotes(ensure_content_markdown_state(content_item_id)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Markdown 草稿不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/markdown/content/{content_item_id}", response_model=MarkdownStateResponse)
async def update_content_markdown(content_item_id: str, req: MarkdownUpdateRequest):
    try:
        return _to_response(update_markdown_draft(content_item_id, req.markdown))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Markdown 草稿不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/markdown/content/{content_item_id}/sync", response_model=MarkdownStateResponse)
async def sync_content_markdown(content_item_id: str, req: MarkdownSyncRequest):
    try:
        state = sync_markdown_to_obsidian(content_item_id, force=req.force)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Markdown 草稿不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(state)


@router.get("/markdown/content/{content_item_id}/export", response_class=PlainTextResponse)
def export_content_markdown(content_item_id: str):
    try:
        state = _with_hydrated_report_footnotes(get_markdown_state(content_item_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Markdown 草稿不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(
        state.markdown,
        media_type="text/markdown; charset=utf-8",
    )


@router.post("/markdown/export", response_model=MarkdownDocumentExportResponse)
def export_markdown(req: MarkdownDocumentExportRequest):
    try:
        # The product deliberately treats export as replace-by-name. The UI
        # explains this before the user chooses a default export directory.
        destination, overwritten = export_markdown_document(title=req.title, markdown=req.markdown)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MarkdownDocumentExportResponse(path=str(destination), overwritten=overwritten)
