"""Local-source import endpoints, kept separate from library browsing."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from config import settings
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from services.content_index import ensure_external_markdown_folder
from services.content_presentation import (
    ContentItemResponse,
    LocalFileImportResponse,
    content_item_response,
)
from services.database import connect, initialize_database
from services.library_folder_tree import is_descendant_folder, require_folder
from services.local_file_imports import (
    extract_document_text,
    import_kind_for_filename,
    original_attachment_path,
    persist_original_attachment,
    persist_original_attachment_from_file,
    safe_import_filename,
    save_imported_document,
    validate_import_upload,
)
from services.markdown_sync import save_markdown_draft_and_sync
from services.pipeline_runner import PipelineRequest
from services.repository import ContentRepository
from services.search_index import upsert_source_text_document
from services.task_manager import task_manager

router = APIRouter()


def _markdown_import_title(markdown: str, filename: str) -> str:
    heading = re.search(r"^\s{0,3}#\s+(.+?)\s*$", markdown, flags=re.MULTILINE)
    if heading:
        title = re.sub(r"\s+#*\s*$", "", heading.group(1)).strip()
        if title:
            return title[:200]
    return (Path(filename).stem.strip() or "未命名 Markdown")[:200]


def _ensure_folder_exists(connection, folder_id: str):
    try:
        return require_folder(connection, folder_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="文件夹不存在") from exc


@router.post("/content/import-markdown", response_model=ContentItemResponse)
async def import_markdown_document(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI declares request fields in signatures.
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
            _ensure_folder_exists(connection, library_folder_id)
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


@router.post("/content/import-file", response_model=LocalFileImportResponse)
async def import_local_file(
    file: UploadFile = File(...),  # noqa: B008 - FastAPI declares request fields in signatures.
    library_folder_id: str | None = Form(default=None),
):
    """Import one local source while retaining its original managed attachment.

    Text-first formats become readable immediately. PDFs and videos create a
    durable task and a visible placeholder item before expensive OCR/ASR work.
    """
    incoming_filename = str(file.filename or "")
    try:
        filename = safe_import_filename(incoming_filename)
        kind = import_kind_for_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw: bytes | None = None
    staged_media: Path | None = None
    media_size = 0
    content_hash = ""
    if kind in {"video", "audio"}:
        staged_media = settings.data_dir / "import_staging" / f"{uuid.uuid4().hex}-{filename}"
        staged_media.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        try:
            with staged_media.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    media_size += len(chunk)
                    maximum = 4 * 1024 * 1024 * 1024 if kind == "video" else 2 * 1024 * 1024 * 1024
                    if media_size > maximum:
                        raise ValueError("视频不能超过 4 GB" if kind == "video" else "音频不能超过 2 GB")
                    digest.update(chunk)
                    output.write(chunk)
            if not media_size:
                raise ValueError("导入文件为空")
            content_hash = digest.hexdigest()
        except ValueError as exc:
            staged_media.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raw = await file.read()
        try:
            filename, kind = validate_import_upload(filename, raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        content_hash = hashlib.sha256(raw).hexdigest()

    extracted_text = ""
    title = Path(filename).stem
    if kind not in {"pdf", "video", "audio", "image"}:
        try:
            extracted_text, extracted_title = extract_document_text(raw or b"", filename=filename, kind=kind)
            title = extracted_title or title
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    canonical_id = f"local-file:{content_hash}"
    source_name = {
        "html": "外部 HTML",
        "docx": "外部 Word",
        "pdf": "外部 PDF",
        "video": "外部视频",
        "audio": "外部音频",
        "image": "外部图片",
        "markdown": "外部 Markdown",
        "text": "外部文本",
    }[kind]
    initialize_database()
    with connect() as connection:
        external_root_id = ensure_external_markdown_folder(connection)
        target_folder_id = external_root_id
        if library_folder_id:
            _ensure_folder_exists(connection, library_folder_id)
            if library_folder_id != external_root_id and not is_descendant_folder(
                connection, library_folder_id, external_root_id
            ):
                raise HTTPException(status_code=400, detail="外部文件只能存入“外部导入”文件夹或其子文件夹")
            target_folder_id = library_folder_id
        repository = ContentRepository(connection)
        existing = repository.find_by_canonical_id(source_provider="local_file", canonical_source_id=canonical_id)
        if existing:
            if staged_media:
                staged_media.unlink(missing_ok=True)
            return LocalFileImportResponse(item=content_item_response(existing))
        item = repository.create_content_item(
            source_provider="local_file",
            content_type=kind if kind in {"video", "audio", "image"} else "document",
            source_url=canonical_id,
            canonical_source_id=canonical_id,
            title=title[:160],
            status="processing" if kind in {"pdf", "video", "audio", "image"} else "to_read",
            library_folder_id=target_folder_id,
            source_name=source_name,
        )
        connection.commit()

    try:
        if staged_media:
            original_path = persist_original_attachment_from_file(
                content_item_id=item.id,
                filename=filename,
                source=staged_media,
                mime_type=str(file.content_type or "application/octet-stream"),
                size_bytes=media_size,
            )
        else:
            original_path = persist_original_attachment(
                content_item_id=item.id,
                filename=filename,
                raw=raw or b"",
                mime_type=str(file.content_type or "application/octet-stream"),
            )
    except Exception:
        if staged_media:
            staged_media.unlink(missing_ok=True)
        raise

    if kind in {"markdown", "text", "html", "docx"}:
        save_imported_document(item, body=extracted_text, kind=kind, original_filename=filename)
        return LocalFileImportResponse(item=content_item_response(item))

    request = PipelineRequest(
        content_item_id=item.id,
        local_video_path=str(original_path) if kind in {"video", "audio"} else None,
        local_document_path=str(original_path) if kind in {"pdf", "image"} else None,
        local_document_kind=kind if kind in {"pdf", "image"} else None,
        source_title=item.title,
        source_url=item.source_url,
        use_cache=False,
        processing_mode="full",
        manual_collection=False,
        priority=100,
        execution_mode="foreground",
    )
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    task = task_manager.create(
        request,
        task_type="process_video" if kind in {"video", "audio"} else "import_document",
    )
    return LocalFileImportResponse(item=content_item_response(item), task_id=task.task_id, processing=True)


@router.post("/content/{content_item_id}/reprocess-local-source", response_model=LocalFileImportResponse)
async def reprocess_local_source(content_item_id: str):
    """Re-run extraction/OCR/ASR from the retained local original.

    The original stays immutable; ``save_imported_document`` preserves existing
    summaries and Q&A when only the source material is refreshed.
    """
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    if item.source_provider != "local_file":
        raise HTTPException(status_code=400, detail="只有外部导入资料可以重新处理")
    original = original_attachment_path(item.id)
    if not original:
        raise HTTPException(status_code=404, detail="找不到保留的原始文件")
    try:
        kind = import_kind_for_filename(original.name.removeprefix("original--"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="原始文件格式不支持重新处理") from exc

    if kind in {"markdown", "text", "html", "docx"}:
        try:
            body, _ = extract_document_text(original.read_bytes(), filename=original.name, kind=kind)
            save_imported_document(item, body=body, kind=kind, original_filename=original.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return LocalFileImportResponse(item=content_item_response(item))

    request = PipelineRequest(
        content_item_id=item.id,
        local_video_path=str(original) if kind in {"video", "audio"} else None,
        local_document_path=str(original) if kind in {"pdf", "image"} else None,
        local_document_kind=kind if kind in {"pdf", "image"} else None,
        source_title=item.title,
        source_url=item.source_url,
        use_cache=False,
        processing_mode="full",
        priority=100,
        execution_mode="foreground",
    )
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    task = task_manager.create(
        request,
        task_type="process_video" if kind in {"video", "audio"} else "import_document",
    )
    return LocalFileImportResponse(item=content_item_response(item), task_id=task.task_id, processing=True)
