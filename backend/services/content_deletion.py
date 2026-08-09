"""Transactional deletion helpers for content-library artifacts.

Database rows are removed inside the caller's transaction.  The returned
cleanup plan is deliberately executed only after that transaction commits so a
failed database operation never removes a user's recoverable files.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from config import settings
from services.cache import cache_dir_for_url, delete_cache_entry
from services.obsidian_settings import is_managed_obsidian_note_path
from services.repository import ContentItemRecord, ContentRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContentDeleteCleanup:
    markdown_paths: tuple[str, ...]
    obsidian_paths: tuple[str, ...]
    attachment_directory: Path
    report_cover_directory: Path
    cache_key: str | None


def delete_content_item_data(
    connection,
    repository: ContentRepository,
    item: ContentItemRecord,
) -> ContentDeleteCleanup:
    """Delete relational records and return physical artifacts for later cleanup."""
    # V2 relational rows cascade with the content item. FTS5 is virtual, so
    # its rows must be cleared explicitly to avoid orphaned searchable text.
    v2_chunk_rows = connection.execute(
        "SELECT id FROM knowledge_v2_chunks WHERE content_item_id = ?",
        (item.id,),
    ).fetchall()
    connection.executemany(
        "DELETE FROM knowledge_v2_search WHERE chunk_id = ?",
        [(row["id"],) for row in v2_chunk_rows],
    )
    markdown_paths = tuple(
        str(row["markdown_path"])
        for row in connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id = ?",
            (item.id,),
        ).fetchall()
        if row["markdown_path"]
    )
    obsidian_paths = tuple(
        str(row["obsidian_path"])
        for row in connection.execute(
            "SELECT obsidian_path FROM obsidian_sync WHERE content_item_id = ?",
            (item.id,),
        ).fetchall()
        if row["obsidian_path"]
    )
    connection.execute("DELETE FROM content_search WHERE content_item_id = ?", (item.id,))
    repository.delete_content_item(item.id)
    return ContentDeleteCleanup(
        markdown_paths=markdown_paths,
        obsidian_paths=obsidian_paths,
        attachment_directory=settings.data_dir / "attachments" / item.id,
        report_cover_directory=settings.data_dir / "report_covers" / item.id,
        cache_key=cache_dir_for_url(item.source_url).name if item.source_url else None,
    )


def cleanup_content_files_after_commit(plan: ContentDeleteCleanup) -> None:
    """Delete physical artifacts only after their SQLite deletion committed.

    If this stage fails, files may remain as reclaimable orphans, but a failed
    database transaction can no longer make a recoverable item lose its source
    Markdown, attachments, or cache.
    """
    try:
        for path in plan.markdown_paths:
            _delete_data_file(path)
        _delete_data_directory(plan.attachment_directory)
        _delete_data_directory(plan.report_cover_directory)
        for path in plan.obsidian_paths:
            _delete_obsidian_note_file(path)
        if plan.cache_key:
            delete_cache_entry(plan.cache_key)
    except OSError:
        logger.exception("Post-commit content cleanup failed; files can be reclaimed later")


def _delete_data_file(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    data_dir = settings.data_dir.expanduser().resolve()
    try:
        path.relative_to(data_dir)
    except ValueError:
        return
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)


def _delete_data_directory(path_value: Path) -> None:
    path = path_value.expanduser().resolve()
    data_dir = settings.data_dir.expanduser().resolve()
    try:
        path.relative_to(data_dir)
    except ValueError:
        return
    if path.exists() and path.is_dir():
        shutil.rmtree(path)


def _delete_obsidian_note_file(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    if not is_managed_obsidian_note_path(path):
        return
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)
