"""Import a file discovered by the opt-in local inbox watcher.

The watcher owns neither the selected folder nor its files: every import is
copied into the managed attachment store before any OCR or transcription task
starts.  This keeps the normal external-import durability contract intact.
"""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
import uuid
from pathlib import Path

from config import settings
from services.content_index import ensure_external_markdown_folder
from services.database import connect, initialize_database
from services.local_file_imports import (
    MAX_AUDIO_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_VIDEO_BYTES,
    extract_document_text,
    import_kind_for_filename,
    persist_original_attachment,
    persist_original_attachment_from_file,
    safe_import_filename,
    save_imported_document,
)
from services.pipeline_runner import PipelineRequest
from services.repository import ContentRepository
from services.task_manager import task_manager


_SOURCE_NAMES = {
    "html": "外部 HTML",
    "docx": "外部 Word",
    "pdf": "外部 PDF",
    "video": "外部视频",
    "audio": "外部音频",
    "image": "外部图片",
    "markdown": "外部 Markdown",
    "text": "外部文本",
}


def import_folder_file(source: Path) -> dict[str, object]:
    """Copy one stable file into the external-import store and schedule work.

    The signature used by the watcher is updated before this call, so a file
    that is still being copied by another application is retried only after it
    changes again instead of being repeatedly queued.
    """
    source = source.expanduser().resolve()
    if not source.is_file():
        raise ValueError("收件箱文件不存在")
    filename = safe_import_filename(source.name)
    kind = import_kind_for_filename(filename)
    size = int(source.stat().st_size)
    limit = MAX_VIDEO_BYTES if kind == "video" else MAX_AUDIO_BYTES if kind == "audio" else MAX_DOCUMENT_BYTES
    if size <= 0:
        raise ValueError("导入文件为空")
    if size > limit:
        raise ValueError("视频不能超过 4 GB" if kind == "video" else "音频不能超过 2 GB" if kind == "audio" else "文档不能超过 50 MB")

    content_hash = _sha256(source)
    canonical_id = f"local-file:{content_hash}"
    initialize_database()
    with connect() as connection:
        folder_id = ensure_external_markdown_folder(connection)
        repository = ContentRepository(connection)
        existing = repository.find_by_canonical_id(source_provider="local_file", canonical_source_id=canonical_id)
        if existing:
            return {"content_item_id": existing.id, "task_id": None, "duplicate": True}
        item = repository.create_content_item(
            source_provider="local_file",
            content_type=kind if kind in {"video", "audio", "image"} else "document",
            source_url=canonical_id,
            canonical_source_id=canonical_id,
            title=Path(filename).stem[:160],
            status="processing" if kind in {"pdf", "video", "audio", "image"} else "to_read",
            library_folder_id=folder_id,
            source_name=_SOURCE_NAMES[kind],
        )
        connection.commit()

    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if kind in {"video", "audio"}:
        staging = settings.data_dir / "import_staging" / f"{uuid.uuid4().hex}-{filename}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source, staging)
            original_path = persist_original_attachment_from_file(
                content_item_id=item.id,
                filename=filename,
                source=staging,
                mime_type=mime_type,
                size_bytes=size,
            )
        finally:
            staging.unlink(missing_ok=True)
    else:
        raw = source.read_bytes()
        original_path = persist_original_attachment(
            content_item_id=item.id,
            filename=filename,
            raw=raw,
            mime_type=mime_type,
        )

    if kind in {"markdown", "text", "html", "docx"}:
        body, title = extract_document_text(source.read_bytes(), filename=filename, kind=kind)
        if title.strip() and title != item.title:
            with connect() as connection:
                repository = ContentRepository(connection)
                repository.update_content_item(item.id, title=title[:160])
                connection.commit()
                item = repository.get_content_item(item.id)
        save_imported_document(item, body=body, kind=kind, original_filename=filename)
        return {"content_item_id": item.id, "task_id": None, "duplicate": False}

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
        execution_mode="background",
    )
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "processing")
        connection.commit()
    task = task_manager.create(request, task_type="process_video" if kind in {"video", "audio"} else "import_document")
    return {"content_item_id": item.id, "task_id": task.task_id, "duplicate": False}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
