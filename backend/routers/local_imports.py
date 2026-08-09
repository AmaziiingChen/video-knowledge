"""Local-source import endpoints, kept separate from library browsing."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from config import settings
from services.content_index import ensure_external_markdown_folder
from services.content_presentation import ContentItemResponse, content_item_response
from services.database import connect, initialize_database
from services.library_folder_tree import is_descendant_folder, require_folder
from services.markdown_sync import save_markdown_draft_and_sync
from services.repository import ContentRepository
from services.search_index import upsert_source_text_document


router = APIRouter()


def _markdown_import_title(markdown: str, filename: str) -> str:
    heading = re.search(r"^\s{0,3}#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    if heading:
        title = re.sub(r"\s+#*\s*$", "", heading.group(1)).strip()
        if title:
            return title[:200]
    return (Path(filename).stem.strip() or "未命名 Markdown")[:200]


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
    canonical_id = f"local-markdown:{hashlib.sha256(raw).hexdigest()}"
    initialize_database()
    with connect() as connection:
        external_root_id = ensure_external_markdown_folder(connection)
        target_folder_id = external_root_id
        if library_folder_id:
            try:
                require_folder(connection, library_folder_id)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail="文件夹不存在") from exc
            if library_folder_id != external_root_id and not is_descendant_folder(
                connection, library_folder_id, external_root_id
            ):
                raise HTTPException(status_code=400, detail="导入 Markdown 只能存入“外部导入”文件夹或其子文件夹")
            target_folder_id = library_folder_id
        repository = ContentRepository(connection)
        item = repository.find_by_canonical_id(
            source_provider="local_markdown", canonical_source_id=canonical_id
        )
        if item is None:
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
    return content_item_response(item)
