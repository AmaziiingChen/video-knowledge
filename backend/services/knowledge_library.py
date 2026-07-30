"""Markdown-first storage for source material.

The application database keeps a small, rebuildable index.  The complete
source text (including OCR in document order), attachments and later Q&A are
kept below the selected storage root's ``library`` and ``attachments`` folders.
"""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from config import settings
from services.cache import cache_dir_for_url, read_cache_meta
from services.database import connect, ensure_database_initialized, initialize_database, utc_now_iso
from services.repository import ContentItemRecord, ContentRepository, new_id
from services.cache import find_cached_video, read_cached_subtitle_transcript, read_cached_transcript
from services.article_image_storage import compact_cached_article_images
from services.obsidian_settings import content_library_root, default_content_library_root
from services.source_context import render_source_context_markdown
from services.xiaohongshu_cache import xiaohongshu_cache_dir

if TYPE_CHECKING:
    from services.content_source_text import ContentSourceText


COLLECTIONS = {
    "wechat": "wechat",
    "campus": "campus",
    "bilibili": "bilibili",
    "douyin": "douyin",
    "wechat_miniprogram": "miniprogram",
    "wechat_report": "reports",
}


@dataclass(frozen=True)
class _LocalSource:
    content_item_id: str
    title: str
    source_url: str
    text: str
    source_kind: str


@dataclass(frozen=True)
class MarkdownQAExchange:
    """One recoverable Q&A exchange stored in a content Markdown document."""

    question: str
    answer: str
    timestamp: str


def library_root() -> Path:
    return content_library_root()


def attachments_root() -> Path:
    return _attachments_root_for_library(library_root())


def _attachments_root_for_library(root: Path) -> Path:
    root = root.expanduser().resolve()
    return root.parent / "attachments"


def ensure_library_layout() -> None:
    for path in (library_root(), attachments_root(), settings.data_dir / "groups", settings.data_dir / "prompts", settings.data_dir / "reports"):
        path.mkdir(parents=True, exist_ok=True)


def ensure_library_folder_directory(folder_id: str) -> Path:
    """Create the on-disk counterpart for one active file-tree folder."""
    initialize_database()
    with connect() as connection:
        components = _library_folder_components(folder_id, connection=connection)
    if not components:
        raise LookupError("文件夹不存在或已删除")
    path = library_root().joinpath(*(_safe_component(component) for component in components))
    path.mkdir(parents=True, exist_ok=True)
    return path


def sync_library_folder_directories() -> int:
    """Materialize every active file-tree folder, including empty folders."""
    ensure_library_layout()
    initialize_database()
    with connect() as connection:
        folder_ids = [
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM library_folders WHERE deleted_at IS NULL"
            ).fetchall()
        ]
        components_by_id = {
            folder_id: _library_folder_components(folder_id, connection=connection)
            for folder_id in folder_ids
        }
    created = 0
    for components in components_by_id.values():
        if not components:
            continue
        path = library_root().joinpath(*(_safe_component(component) for component in components))
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            created += 1
    return created


def remove_empty_library_folder_directory(path: Path) -> bool:
    """Remove only an empty obsolete directory; never delete user files."""
    try:
        path.resolve().relative_to(library_root().resolve())
        path.rmdir()
        return True
    except (OSError, ValueError):
        return False


def compact_article_image_storage() -> dict[str, int]:
    """Migrate managed article images to compact previews and text-first Markdown.

    Only app-generated ``![原图 N]`` links are replaced. Manually added image
    links are deliberately left untouched, and their files are not deleted.
    """
    stats = compact_cached_article_images()
    stats.update({"documents_rewritten": 0, "attachment_files_removed": 0})
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT content_items.id, content_items.source_url, content_documents.markdown_path
               FROM content_items
               JOIN content_documents ON content_documents.content_item_id = content_items.id
               WHERE content_items.deleted_at IS NULL AND content_documents.markdown_path <> ''"""
        ).fetchall()

    for row in rows:
        item_id = str(row["id"])
        markdown_path = Path(str(row["markdown_path"] or ""))
        if not markdown_path.is_file():
            continue
        article_info = read_cache_meta(cache_dir_for_url(str(row["source_url"] or ""))).get("article_info") if row["source_url"] else {}
        image_urls = _article_image_urls(article_info if isinstance(article_info, dict) else {})
        markdown = markdown_path.read_text(encoding="utf-8", errors="replace")
        rewritten = _replace_generated_article_image_links(markdown, item_id=item_id, image_urls=image_urls)
        if rewritten != markdown:
            _atomic_write(markdown_path, rewritten)
            _upsert_document_index(item_id, markdown_path, rewritten)
            stats["documents_rewritten"] += 1
        attachment_dir = attachments_root() / item_id
        if not attachment_dir.is_dir():
            continue
        for image in attachment_dir.glob("image-*.*"):
            if image.name not in rewritten:
                image.unlink(missing_ok=True)
                stats["attachment_files_removed"] += 1
        try:
            attachment_dir.rmdir()
        except OSError:
            pass
    return stats


def migrate_legacy_local_content() -> dict[str, int]:
    """Migrate only locally available legacy content; never fetch or call AI."""
    ensure_library_layout()
    stats = {"scanned": 0, "documents_created": 0, "skipped_without_local_text": 0, "legacy_summaries": 0, "qa_threads": 0, "reports_copied": 0}
    initialize_database()
    with connect() as connection:
        item_ids = [str(row["id"]) for row in connection.execute("SELECT id FROM content_items WHERE deleted_at IS NULL").fetchall()]

    for item_id in item_ids:
        stats["scanned"] += 1
        source = _local_source_for_item(item_id)
        if source is None:
            stats["skipped_without_local_text"] += 1
            continue
        with connect() as connection:
            from services.repository import ContentRepository
            item = ContentRepository(connection).get_content_item(item_id)
        existed = markdown_document_path(item_id) is not None
        path = materialize_source_document(item, source)
        if not existed:
            stats["documents_created"] += 1
            if _merge_legacy_summary(item_id, path):
                stats["legacy_summaries"] += 1
        if _migrate_qa_thread(item_id, path):
            stats["qa_threads"] += 1

    stats["reports_copied"] = _copy_legacy_reports()
    return stats


def recover_legacy_report_documents() -> dict[str, int]:
    """Reconnect pre-library reports with their preserved Markdown files.

    Early report generation wrote directly to ``data/drafts``.  When that
    folder was retired, the files were preserved under ``library/legacy-drafts``
    but report rows and Markdown indexes could be left behind.  This recovery
    is deliberately idempotent: it only fills missing report metadata and
    document indexes, and never replaces an existing canonical document.
    """
    ensure_library_layout()
    initialize_database()
    stats = {
        "scanned": 0,
        "documents_recovered": 0,
        "report_links_recovered": 0,
        "groups_created": 0,
        "missing_legacy_files": 0,
        "unrecognized_reports": 0,
    }
    legacy_root = library_root() / "legacy-drafts"

    with connect() as connection:
        rows = connection.execute(
            """SELECT id, title, created_at, updated_at, published_at
               FROM content_items
               WHERE source_provider='wechat_report'
                 AND content_type='report'
                 AND deleted_at IS NULL
               ORDER BY created_at"""
        ).fetchall()
        groups = {
            str(row["name"]): str(row["id"])
            for row in connection.execute(
                "SELECT id, name FROM wechat_subscription_groups"
            ).fetchall()
        }

        for row in rows:
            stats["scanned"] += 1
            item_id = str(row["id"])
            legacy_path = _legacy_report_markdown_path(legacy_root, item_id)
            if legacy_path is None:
                stats["missing_legacy_files"] += 1
                continue
            legacy_markdown = legacy_path.read_text(encoding="utf-8", errors="replace")
            metadata = _legacy_report_metadata(legacy_markdown, str(row["title"] or ""))
            if metadata is None:
                stats["unrecognized_reports"] += 1
                continue

            group_id = groups.get(metadata["group_name"])
            if group_id is None:
                group_id = new_id()
                now = utc_now_iso()
                connection.execute(
                    """INSERT INTO wechat_subscription_groups
                       (id, name, description, include_campus_sources, created_at, updated_at)
                       VALUES (?, ?, '', 0, ?, ?)""",
                    (group_id, metadata["group_name"], now, now),
                )
                groups[metadata["group_name"]] = group_id
                stats["groups_created"] += 1

            document_row = connection.execute(
                "SELECT markdown_path FROM content_documents WHERE content_item_id=?",
                (item_id,),
            ).fetchone()
            document_path = (
                Path(str(document_row["markdown_path"]))
                if document_row and document_row["markdown_path"]
                else None
            )
            if document_path is None or not document_path.exists():
                month = _month_key(str(row["published_at"] or row["created_at"] or ""))
                filename = f"{_safe_component(metadata['title'])[:96]}--{item_id}.md"
                document_path = (
                    library_root()
                    / "reports"
                    / month
                    / _safe_component(metadata["group_name"])
                    / filename
                )
                document_path.parent.mkdir(parents=True, exist_ok=True)
                if not document_path.exists():
                    _atomic_write(document_path, legacy_markdown)
                stats["documents_recovered"] += 1

            document_markdown = document_path.read_text(encoding="utf-8", errors="replace")
            connection.execute(
                """INSERT INTO content_documents (content_item_id, markdown_path, content_hash, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(content_item_id) DO UPDATE SET
                     markdown_path=excluded.markdown_path,
                     content_hash=excluded.content_hash,
                     updated_at=excluded.updated_at""",
                (item_id, str(document_path), _hash(document_markdown), utc_now_iso()),
            )
            if str(row["title"] or "") != metadata["title"]:
                connection.execute(
                    "UPDATE content_items SET title=?, updated_at=? WHERE id=?",
                    (metadata["title"], utc_now_iso(), item_id),
                )

            sync_row = connection.execute(
                "SELECT id FROM obsidian_sync WHERE content_item_id=? ORDER BY rowid DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            if sync_row:
                connection.execute(
                    "UPDATE obsidian_sync SET markdown_draft_path=? WHERE id=?",
                    (str(document_path), sync_row["id"]),
                )
            else:
                connection.execute(
                    """INSERT INTO obsidian_sync
                       (id, content_item_id, markdown_draft_path, last_synced_hash, sync_status)
                       VALUES (?, ?, ?, ?, 'dirty')""",
                    (new_id(), item_id, str(document_path), _hash(document_markdown)),
                )

            existing_report = connection.execute(
                "SELECT id FROM wechat_reports WHERE content_item_id=? LIMIT 1",
                (item_id,),
            ).fetchone()
            if existing_report is None:
                connection.execute(
                    """INSERT INTO wechat_reports
                       (id, group_id, content_item_id, report_type, period_start, period_end,
                        source_count, source_coverage_json, window_start, window_end,
                        generation_trigger, generation_mode, cover_status, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, 'legacy_recovery', 'legacy', 'none', ?)""",
                    (
                        new_id(),
                        group_id,
                        item_id,
                        metadata["report_type"],
                        metadata["period_start"],
                        metadata["period_end"],
                        metadata["source_count"],
                        metadata["window_start"],
                        metadata["window_end"],
                        str(row["created_at"]),
                    ),
                )
                stats["report_links_recovered"] += 1
        connection.commit()
    return stats


def _legacy_report_markdown_path(legacy_root: Path, content_item_id: str) -> Path | None:
    if not legacy_root.exists():
        return None
    candidates = sorted(legacy_root.glob(f"{content_item_id}-*.md"))
    return candidates[0] if candidates else None


def _legacy_report_metadata(markdown: str, fallback_title: str) -> dict[str, object] | None:
    title_match = re.search(r"^#\s+([^\n]+)", markdown, re.MULTILINE)
    title = str(title_match.group(1) if title_match else fallback_title).strip()
    group_match = re.search(r"｜\s*([^\n]+?)\s*$", title)
    if group_match is None:
        group_match = re.search(r"(?:^|[·\n])\s*分组：\s*([^·\n]+)", markdown)
    if group_match is None:
        return None
    group_name = str(group_match.group(1)).strip()
    if "区间汇总" in title:
        report_type = "range"
    elif "日报" in title:
        report_type = "daily"
    elif "周报" in title:
        report_type = "weekly"
    else:
        return None

    dates = re.findall(r"(20\d{2}-\d{2}-\d{2})", title)
    if not dates:
        return None
    period_start = dates[0]
    period_end = dates[-1]
    if report_type == "daily":
        period_end = period_start
    windows = re.findall(r"(\d{1,2})时(\d{2})分", title)
    window_start = window_end = None
    if len(windows) >= 2:
        start_date = dates[0]
        end_date = dates[-1]
        window_start = f"{start_date}T{int(windows[0][0]):02d}:{windows[0][1]}:00"
        window_end = f"{end_date}T{int(windows[1][0]):02d}:{windows[1][1]}:00"
    source_match = re.search(r"(?:分析文章|来源文章)：\s*(\d+)\s*篇", markdown)
    source_count = int(source_match.group(1)) if source_match else 0
    return {
        "title": title,
        "group_name": group_name,
        "report_type": report_type,
        "period_start": period_start,
        "period_end": period_end,
        "window_start": window_start,
        "window_end": window_end,
        "source_count": source_count,
    }


def archive_legacy_files_for_cleanup() -> dict[str, int]:
    """Preserve binary attachments and old drafts before their cache folders go away."""
    ensure_library_layout()
    cache_root = settings.data_dir / "cache"
    legacy_attachments = attachments_root() / "legacy-cache"
    legacy_drafts = library_root() / "legacy-drafts"
    stats = {"attachments_archived": 0, "drafts_archived": 0}
    if cache_root.exists():
        for cache_entry in cache_root.iterdir():
            if not cache_entry.is_dir():
                continue
            for candidate in cache_entry.rglob("*"):
                if not candidate.is_file() or not _is_legacy_attachment(candidate):
                    continue
                relative = candidate.relative_to(cache_entry)
                target = legacy_attachments / cache_entry.name / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    shutil.copy2(candidate, target)
                    stats["attachments_archived"] += 1
    drafts_root = settings.data_dir / "drafts"
    if drafts_root.exists():
        legacy_drafts.mkdir(parents=True, exist_ok=True)
        for draft in drafts_root.glob("*.md"):
            target = legacy_drafts / draft.name
            if not target.exists():
                shutil.copy2(draft, target)
                stats["drafts_archived"] += 1
    return stats


def _is_legacy_attachment(path: Path) -> bool:
    suffix = path.suffix.lower()
    return "/article_images/" in path.as_posix() or suffix in {
        ".mp4", ".mkv", ".webm", ".flv", ".mov", ".mp3", ".m4a", ".wav", ".aac",
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".pdf",
    }


def _local_source_for_item(content_item_id: str) -> _LocalSource | None:
    from services.repository import ContentRepository
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    if item.source_url and item.content_type == "article":
        info = _article_info(item)
        text = str(info.get("body_text") or "").strip()
        if text:
            return _LocalSource(item.id, str(info.get("title") or item.title), item.source_url, text, "article")
    if item.source_url and item.content_type == "video":
        cache_dir = cache_dir_for_url(item.source_url)
        text = read_cached_subtitle_transcript(cache_dir) or _cached_transcript(cache_dir)
        if text:
            return _LocalSource(item.id, item.title, item.source_url, text, "video")
    if item.content_type == "forum_post":
        with connect() as connection:
            row = connection.execute("SELECT body_text FROM forum_posts WHERE content_item_id=?", (item.id,)).fetchone()
        if row and str(row["body_text"] or "").strip():
            return _LocalSource(item.id, item.title, str(item.source_url or ""), str(row["body_text"]).strip(), "forum_post")
    return None


def _cached_transcript(cache_dir: Path) -> str | None:
    metadata = read_cache_meta(cache_dir).get("transcripts")
    names = list(metadata) if isinstance(metadata, dict) else []
    for name in reversed(names):
        if name != "subtitle":
            text = read_cached_transcript(cache_dir, str(name))
            if text:
                return text
    for path in sorted(cache_dir.glob("transcript_*.txt"), key=lambda value: value.stat().st_mtime, reverse=True):
        if path.name == "transcript_subtitle.txt":
            continue
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            return text
    return None


def _merge_legacy_summary(content_item_id: str, destination: Path) -> bool:
    legacy = _legacy_draft_path(content_item_id)
    if legacy is None:
        return False
    text = legacy.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^# [^\n]+\n\n(.*?)(?:\n\n<details>|\n\n## 追问记录|\Z)", text, re.DOTALL | re.MULTILINE)
    summary = match.group(1).strip() if match else ""
    if not summary:
        return False
    current = destination.read_text(encoding="utf-8")
    marker = "## AI 摘要\n\n<!-- 由应用生成；人工编辑内容将被保留。 -->"
    if marker not in current:
        return False
    updated = current.replace(marker, f"## AI 摘要\n\n{summary}", 1)
    _atomic_write(destination, updated)
    _upsert_document_index(content_item_id, destination, updated)
    return True


def _migrate_qa_thread(content_item_id: str, destination: Path) -> bool:
    current = destination.read_text(encoding="utf-8")
    if re.search(r"^###\s+\d{4}-\d{2}-\d{2}", current, re.MULTILINE):
        return False
    with connect() as connection:
        rows = connection.execute(
            """SELECT role, content, created_at FROM qa_messages WHERE thread_id IN
               (SELECT id FROM qa_threads WHERE scope='content' AND content_item_id=?) ORDER BY created_at, rowid""",
            (content_item_id,),
        ).fetchall()
    pairs: list[tuple[sqlite3.Row, sqlite3.Row]] = []
    pending = None
    for row in rows:
        if row["role"] == "user":
            pending = row
        elif row["role"] == "assistant" and pending is not None:
            pairs.append((pending, row)); pending = None
    if not pairs:
        return False
    updated = current.rstrip()
    for question, answer in pairs:
        timestamp = str(question["created_at"] or "")[:16].replace("T", " ")
        updated += f"\n\n### {timestamp}\n\n**问：** {str(question['content']).strip()}\n\n**答：**\n{str(answer['content']).strip()}"
    updated += "\n"
    _atomic_write(destination, updated)
    _upsert_document_index(content_item_id, destination, updated)
    return True


def _legacy_draft_path(content_item_id: str) -> Path | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT markdown_draft_path FROM obsidian_sync WHERE content_item_id=? ORDER BY rowid DESC LIMIT 1",
            (content_item_id,),
        ).fetchone()
    path = Path(str(row["markdown_draft_path"])) if row and row["markdown_draft_path"] else None
    return path if path and path.exists() else None


def _copy_legacy_reports() -> int:
    copied = 0
    with connect() as connection:
        rows = connection.execute(
            """SELECT s.markdown_draft_path, c.title FROM obsidian_sync s
               LEFT JOIN content_items c ON c.id=s.content_item_id
               WHERE s.series_id IS NOT NULL OR (c.content_type='report')"""
        ).fetchall()
    destination_root = settings.data_dir / "reports" / "legacy"
    destination_root.mkdir(parents=True, exist_ok=True)
    for row in rows:
        source = Path(str(row["markdown_draft_path"] or ""))
        if not source.exists() or not source.is_file():
            continue
        target = destination_root / f"{_safe_component(str(row['title'] or source.stem))}--{_hash(str(source))[:10]}.md"
        if target.exists():
            continue
        shutil.copy2(source, target)
        copied += 1
    return copied


def materialize_source_document(item: "ContentItemRecord", source: "ContentSourceText") -> Path:
    """Create or update the canonical Markdown document for available source text.

    This deliberately does not consume a model or network resource.  It only
    mirrors data that has already been fetched/transcribed by the normal flow.
    """
    ensure_library_layout()
    filename = f"{_safe_component(item.title)[:96]}--{item.id}.md"
    path = _document_target_path(item, filename=filename)
    existing_path = markdown_document_path(item.id)
    if existing_path is not None and existing_path.resolve() != path.resolve():
        was_manually_modified = _document_is_manually_modified(item.id, existing_path)
        path, relocated_markdown = _relocate_markdown_document(
            content_item_id=item.id,
            source_path=existing_path,
            target_path=path,
            attachment_root=attachments_root(),
        )
        if was_manually_modified:
            _update_document_path(item.id, path)
        else:
            _upsert_document_index(item.id, path, relocated_markdown)
    elif existing_path is not None:
        path = existing_path
    path.parent.mkdir(parents=True, exist_ok=True)

    article_info = _article_info(item)
    body = _source_markdown_body(item, source.text, article_info, document_parent=path.parent)
    markdown = _document_markdown(item, source, body, article_info, document_parent=path.parent)
    # A user may edit this document in Obsidian. Do not silently overwrite an
    # externally changed canonical file during a later cache read; a future
    # source-update UI can offer an explicit merge/version decision instead.
    if path.exists() and _document_is_manually_modified(item.id, path):
        return path
    if path.exists():
        markdown = _preserve_generated_sections(markdown, path.read_text(encoding="utf-8", errors="replace"))
    _atomic_write(path, markdown)
    _upsert_document_index(item.id, path, markdown)
    return path


def update_source_context_section(
    content_item_id: str,
    source_context: dict[str, object],
) -> bool:
    """Surgically refresh generated interaction evidence without replacing user edits."""
    path = markdown_document_path(content_item_id)
    context_markdown = render_source_context_markdown(source_context)
    if path is None or not context_markdown:
        return False
    try:
        current = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    was_manually_modified = _document_is_manually_modified(content_item_id, path)
    managed_section = (
        "<!-- source-context:start -->\n"
        "## 平台互动与评论样本\n\n"
        f"{context_markdown}\n"
        "<!-- source-context:end -->"
    )
    marker_pattern = re.compile(
        r"<!-- source-context:start -->[\s\S]*?<!-- source-context:end -->"
    )
    legacy_pattern = re.compile(
        r"^## 平台互动与评论样本\s*$\n+"
        r"<details>\s*\n<summary>互动指标与评论样本</summary>"
        r"[\s\S]*?</details>",
        re.MULTILINE,
    )
    if marker_pattern.search(current):
        updated = marker_pattern.sub(lambda _match: managed_section, current, count=1)
    elif legacy_pattern.search(current):
        updated = legacy_pattern.sub(lambda _match: managed_section, current, count=1)
    else:
        insertion = re.search(r"^## (?:AI 摘要|追问记录)\s*$", current, re.MULTILINE)
        if insertion:
            updated = (
                current[:insertion.start()].rstrip()
                + "\n\n"
                + managed_section
                + "\n\n"
                + current[insertion.start():].lstrip()
            )
        else:
            updated = current.rstrip() + "\n\n" + managed_section + "\n"
    if updated == current:
        return True
    try:
        _atomic_write(path, updated)
    except OSError:
        return False
    # Keep the mismatch for externally edited documents so later automatic
    # materialization continues to protect their source body.
    if not was_manually_modified:
        _upsert_document_index(content_item_id, path, updated)
    return True


def markdown_document_path(content_item_id: str) -> Path | None:
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id = ?",
            (content_item_id,),
        ).fetchone()
    if not row:
        return None
    path = Path(str(row["markdown_path"]))
    return path if path.exists() else None


def write_content_markdown_document(
    content_item_id: str,
    markdown: str,
    *,
    document_name: str | None = None,
) -> Path:
    """Write generated content into the same canonical file used by the tree."""
    ensure_database_initialized()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    existing_path = markdown_document_path(content_item_id)
    if existing_path is not None and item.source_provider == "wechat_report" and not document_name:
        path = existing_path
    else:
        filename = _document_filename(item, document_name) if document_name else None
        with connect() as connection:
            path = _document_target_path(item, filename=filename, connection=connection)
    if existing_path is not None and existing_path.resolve() != path.resolve():
        path, _ = _relocate_markdown_document(
            content_item_id=content_item_id,
            source_path=existing_path,
            target_path=path,
            attachment_root=attachments_root(),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, markdown)
    _upsert_document_index(content_item_id, path, markdown)
    return path


def _document_filename(item: "ContentItemRecord", document_name: str) -> str:
    stem = _safe_component(str(document_name or "").removesuffix(".md"))[:96] or "报告"
    suffix = item.id[:12] if item.source_provider == "wechat_report" else item.id
    return f"{stem}--{suffix}.md"


def append_qa_to_source_document(
    content_item_id: str,
    question: str,
    answer: str,
    timestamp: str,
    *,
    message_id: str | None = None,
) -> Path:
    """Append a completed exchange to the active conversation in canonical Markdown."""
    path = markdown_document_path(content_item_id)
    if path is None:
        raise LookupError("对应的内容 Markdown 尚未生成")
    markdown = path.read_text(encoding="utf-8")
    marker = f"<!-- qa-message:{message_id} -->" if message_id else ""
    if marker and marker in markdown:
        return path
    markdown, section_body = _split_qa_section(markdown)
    section_body, _ = _ensure_active_qa_conversation(section_body)
    marker_line = f"\n{marker}" if marker else ""
    entry = f"#### {timestamp}{marker_line}\n\n**问：** {question.strip()}\n\n**答：**\n{answer.strip()}"
    updated = _join_qa_section(markdown, f"{section_body.rstrip()}\n\n{entry}\n")
    _atomic_write(path, updated)
    _upsert_document_index(content_item_id, path, updated)
    return path


def replace_qa_answer_in_source_document(
    content_item_id: str,
    answer: str,
    *,
    message_id: str,
) -> Path:
    """Replace one persisted Q&A answer without appending a duplicate exchange."""
    path = markdown_document_path(content_item_id)
    if path is None:
        raise LookupError("对应的内容 Markdown 尚未生成")
    markdown = path.read_text(encoding="utf-8")
    marker = re.escape(f"<!-- qa-message:{message_id} -->")
    match = re.search(
        rf"(?P<prefix>^{marker}\s*\n\s*\*\*问：\*\*[\s\S]*?\n\s*\*\*答：\*\*[ \t]*(?:\n)?)"
        rf"(?P<previous>[\s\S]*?)(?=^#### \d{{4}}-\d{{2}}-\d{{2}}|\Z)",
        markdown,
        re.MULTILINE,
    )
    if match is None:
        raise ValueError("Markdown 中未找到待重新生成的回答")
    updated = markdown[:match.start()] + match.group("prefix") + answer.strip() + "\n" + markdown[match.end():]
    _atomic_write(path, updated)
    _upsert_document_index(content_item_id, path, updated)
    return path


def qa_history_from_markdown(markdown: str) -> list[MarkdownQAExchange]:
    """Return the active Q&A thread from a canonical or legacy Markdown document.

    Markdown is a durable projection of content conversations.  This parser is
    intentionally narrow: it reads only the dedicated Q&A section and ignores
    archived threads, so restoring the sidebar never leaks an older thread into
    the current conversation.
    """
    sections = list(re.finditer(r"^## 追问记录\s*$", str(markdown or ""), re.MULTILINE))
    if not sections:
        return []
    # Canonical documents always keep Q&A last.  Do not treat headings inside
    # an AI answer as document delimiters while importing a Markdown-only thread.
    section = str(markdown or "")[sections[-1].end():].strip()
    conversations = list(re.finditer(r"^### 对话 \d+（(当前|已归档)）\s*$", section, re.MULTILINE))
    if conversations:
        current = [match for match in conversations if match.group(1) == "当前"]
        if not current:
            return []
        active = current[-1]
        following = next((match for match in conversations if match.start() > active.start()), None)
        section = section[active.end():following.start() if following else None].strip()

    entries = re.finditer(
        r"^#### (?P<timestamp>\d{4}-\d{2}-\d{2}[^\n]*)\n"
        r"(?:<!-- qa-message:[^>]+ -->\s*)?\n*"
        r"\*\*问：\*\*\s*(?P<question>[\s\S]*?)\n\s*\*\*答：\*\*[ \t]*(?:\n)?"
        r"(?P<answer>[\s\S]*?)(?=^#### \d{4}-\d{2}-\d{2}|\Z)",
        section,
        re.MULTILINE,
    )
    return [
        MarkdownQAExchange(
            question=match.group("question").strip(),
            answer=match.group("answer").strip(),
            timestamp=match.group("timestamp").strip(),
        )
        for match in entries
        if match.group("question").strip() and match.group("answer").strip()
    ]


def archive_qa_conversation_in_source_document(content_item_id: str) -> Path:
    """Close the current Markdown Q&A conversation and open an empty next one."""
    path = markdown_document_path(content_item_id)
    if path is None:
        raise LookupError("对应的内容 Markdown 尚未生成")
    markdown = path.read_text(encoding="utf-8")
    prefix, section_body = _split_qa_section(markdown)
    section_body, current_number = _ensure_active_qa_conversation(section_body)
    current_heading = f"### 对话 {current_number}（当前）"
    archived_heading = f"### 对话 {current_number}（已归档）"
    if current_heading not in section_body:
        raise ValueError("当前追问记录格式无法归档")
    section_body = section_body.replace(current_heading, archived_heading, 1).rstrip()
    section_body += f"\n\n### 对话 {current_number + 1}（当前）\n"
    updated = _join_qa_section(prefix, section_body)
    _atomic_write(path, updated)
    _upsert_document_index(content_item_id, path, updated)
    return path


def _split_qa_section(markdown: str) -> tuple[str, str]:
    section = "## 追问记录"
    match = re.search(r"^## 追问记录\s*$", markdown, re.MULTILINE)
    if match is None:
        return markdown.rstrip(), ""
    return markdown[:match.start()].rstrip(), markdown[match.end():].strip()


def _join_qa_section(prefix: str, section_body: str) -> str:
    body = section_body.strip()
    return f"{prefix.rstrip()}\n\n## 追问记录\n" + (f"\n{body}\n" if body else "")


def _ensure_active_qa_conversation(section_body: str) -> tuple[str, int]:
    """Upgrade legacy timestamp-only records into the current conversation format."""
    body = section_body.strip()
    matches = list(re.finditer(r"^### 对话 (\d+)（(当前|已归档)）\s*$", body, re.MULTILINE))
    if not matches:
        legacy_entries = re.sub(r"^### (?=\d{4}-\d{2}-\d{2} )", "#### ", body, flags=re.MULTILINE)
        return f"### 对话 1（当前）" + (f"\n\n{legacy_entries}" if legacy_entries else ""), 1

    current_matches = [match for match in matches if match.group(2) == "当前"]
    if current_matches:
        return body, int(current_matches[-1].group(1))

    number = max(int(match.group(1)) for match in matches) + 1
    return f"{body}\n\n### 对话 {number}（当前）", number


def _source_markdown_body(
    item: "ContentItemRecord",
    fallback_text: str,
    article_info: dict,
    *,
    document_parent: Path,
) -> str:
    html = str(article_info.get("body_html") or article_info.get("normalized_html") or "").strip()
    if not html:
        return fallback_text.strip()

    soup = BeautifulSoup(html, "lxml")
    image_number = 0
    for image in soup.find_all("img"):
        image_number += 1
        source_url = str(image.get("data-src") or image.get("src") or "").strip()
        # Markdown is a text-first knowledge record: OCR text is retained in
        # document order while only the source link represents the original
        # image. The reading workspace uses its own compact local preview.
        image.replace_with(f"\n\n[原图 {image_number}：{source_url}]\n\n" if source_url else "")

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or fallback_text.strip()


def _article_image_urls(article_info: dict) -> list[str]:
    html = str(article_info.get("body_html") or article_info.get("normalized_html") or "").strip()
    if not html:
        return [str(url).strip() for url in article_info.get("images") or [] if str(url).strip()]
    soup = BeautifulSoup(html, "lxml")
    return [
        str(image.get("data-src") or image.get("src") or "").strip()
        for image in soup.find_all("img")
    ]


def _replace_generated_article_image_links(markdown: str, *, item_id: str, image_urls: list[str]) -> str:
    escaped_id = re.escape(item_id)
    pattern = re.compile(
        rf"!\[原图\s+(?P<number>\d+)\]\((?:\.\./)*attachments/{escaped_id}/image-[^)\n]+\)"
    )

    def replace(match: re.Match[str]) -> str:
        number = int(match.group("number"))
        source_url = image_urls[number - 1] if number <= len(image_urls) else ""
        return f"[原图 {number}：{source_url}]" if source_url else f"[原图 {number}：已省略本地图片副本]"

    return pattern.sub(replace, markdown)


def _article_info(item: "ContentItemRecord") -> dict:
    if not item.source_url:
        return {}
    cache_dir = (
        xiaohongshu_cache_dir(item.source_url)
        if item.source_provider == "xiaohongshu"
        else cache_dir_for_url(item.source_url)
    )
    value = read_cache_meta(cache_dir).get("article_info")
    return value if isinstance(value, dict) else {}


def _document_markdown(
    item: "ContentItemRecord",
    source: "ContentSourceText",
    body: str,
    article_info: dict,
    *,
    document_parent: Path,
) -> str:
    published = str(article_info.get("published_at") or item.published_at or "").strip()
    author = str(article_info.get("author") or "").strip()
    metadata = {
        "id": item.id,
        "source_type": item.source_provider,
        "source_name": item.source_name or _provider_name(item.source_provider),
        "source_url": item.source_url or source.source_url,
        "published_at": published,
        "fetched_at": utc_now_iso(),
        "content_hash": _hash(body),
    }
    if author:
        metadata["author"] = author
    frontmatter = "\n".join(f"{key}: {_yaml_scalar(value)}" for key, value in metadata.items())
    media_heading = "视频字幕或转写" if source.source_kind in {"video", "subtitle", "transcript"} else "原文内容"
    attachment = _video_attachment_markdown(item, document_parent=document_parent) if source.source_kind in {"video", "subtitle", "transcript"} else ""
    source_context = article_info.get("source_context") if isinstance(article_info.get("source_context"), dict) else {}
    if not source_context and item.source_url:
        cache_meta = read_cache_meta(cache_dir_for_url(item.source_url))
        value = cache_meta.get("source_context")
        if not isinstance(value, dict):
            video_info = cache_meta.get("video_info") if isinstance(cache_meta.get("video_info"), dict) else {}
            value = video_info.get("source_context")
        source_context = value if isinstance(value, dict) else {}
    context_markdown = render_source_context_markdown(source_context)
    context_section = (
        "\n\n<!-- source-context:start -->\n"
        "## 平台互动与评论样本\n\n"
        f"{context_markdown}\n"
        "<!-- source-context:end -->"
        if context_markdown
        else ""
    )
    return (
        f"---\n{frontmatter}\n---\n\n"
        f"# {item.title or source.title or '未命名内容'}\n\n"
        f"{attachment}## {media_heading}\n\n{body.strip()}{context_section}\n\n"
        "## AI 摘要\n\n<!-- 由应用生成；人工编辑内容将被保留。 -->\n\n"
        "## 追问记录\n"
    )


def _video_attachment_markdown(item: "ContentItemRecord", *, document_parent: Path) -> str:
    stored = _managed_original_attachment(item.id)
    if stored is None and item.source_url:
        video = find_cached_video(cache_dir_for_url(item.source_url))
        stored = _copy_attachment(video, attachments_root() / item.id, "video") if video else None
    if not stored:
        return ""
    relative = Path(os.path.relpath(stored, start=document_parent))
    return f"## 附件\n\n[原视频文件]({relative.as_posix()})\n\n"


def _managed_original_attachment(content_item_id: str) -> Path | None:
    """Return a user-imported original without treating it as disposable cache."""
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """SELECT path FROM media_assets
               WHERE content_item_id=? AND asset_type='original_file'
               ORDER BY created_at DESC LIMIT 1""",
            (content_item_id,),
        ).fetchone()
    path = Path(str(row["path"] or "")) if row else None
    return path if path and path.is_file() else None


def migrate_managed_library_storage(
    *,
    source_roots: tuple[Path, ...],
    destination_root: Path,
) -> dict[str, int]:
    """Move indexed source Markdown and its attachments to a new library root.

    The database is the ownership boundary: files without a ``content_documents``
    row are user files and are deliberately left untouched.
    """
    initialize_database()
    destination_root = destination_root.expanduser().resolve()
    normalized_sources: list[Path] = []
    for root in source_roots:
        resolved = root.expanduser().resolve()
        if resolved != destination_root and resolved not in normalized_sources:
            normalized_sources.append(resolved)
    if not normalized_sources:
        return {"documents": 0, "attachments": 0}

    with connect() as connection:
        rows = connection.execute(
            """SELECT d.content_item_id, d.markdown_path, d.content_hash,
                      c.content_type, c.source_provider, c.source_url, c.canonical_source_id,
                      c.title, c.cover_url, c.duration_seconds, c.status, c.series_id,
                      c.library_folder_id, c.sort_order, c.created_at, c.updated_at,
                      c.published_at, c.source_name, c.source_section
               FROM content_documents AS d
               JOIN content_items AS c ON c.id=d.content_item_id"""
        ).fetchall()
        moved_documents = 0
        moved_attachments = 0
        for row in rows:
            item_id = str(row["content_item_id"])
            source_path = Path(str(row["markdown_path"])).expanduser().resolve()
            source_root = next(
                (root for root in normalized_sources if _is_relative_to(source_path, root)),
                None,
            )
            if source_root is None:
                continue
            if not source_path.exists() or not source_path.is_file():
                continue
            item = ContentItemRecord(
                id=item_id,
                content_type=str(row["content_type"] or ""),
                source_provider=str(row["source_provider"] or ""),
                source_url=row["source_url"],
                canonical_source_id=row["canonical_source_id"],
                title=str(row["title"] or ""),
                cover_url=row["cover_url"],
                duration_seconds=row["duration_seconds"],
                status=str(row["status"] or ""),
                series_id=row["series_id"],
                library_folder_id=row["library_folder_id"],
                sort_order=float(row["sort_order"] or 0),
                created_at=str(row["created_at"] or ""),
                updated_at=str(row["updated_at"] or ""),
                published_at=row["published_at"],
                source_name=row["source_name"],
                source_section=row["source_section"],
            )
            desired_path = _document_target_path(item, connection=connection, root=destination_root)
            was_manually_modified = _hash(source_path.read_text(encoding="utf-8", errors="replace")) != str(row["content_hash"] or "")
            destination_path, relocated_markdown = _relocate_markdown_document(
                content_item_id=item_id,
                source_path=source_path,
                target_path=desired_path,
                attachment_root=_attachments_root_for_library(destination_root),
            )
            moved_documents += 1

            source_attachments = _attachments_root_for_library(source_root) / item_id
            destination_attachments = _attachments_root_for_library(destination_root) / item_id
            if source_attachments.exists() and source_attachments != destination_attachments:
                destination_attachments.parent.mkdir(parents=True, exist_ok=True)
                if not destination_attachments.exists():
                    shutil.move(str(source_attachments), str(destination_attachments))
                    moved_attachments += 1
                elif _merge_attachment_directory(source_attachments, destination_attachments):
                    moved_attachments += 1

            if was_manually_modified:
                connection.execute(
                    "UPDATE content_documents SET markdown_path=?, updated_at=? WHERE content_item_id=?",
                    (str(destination_path), utc_now_iso(), item_id),
                )
            else:
                connection.execute(
                    "UPDATE content_documents SET markdown_path=?, content_hash=?, updated_at=? WHERE content_item_id=?",
                    (str(destination_path), _hash(relocated_markdown), utc_now_iso(), item_id),
                )
            connection.execute(
                "UPDATE obsidian_sync SET markdown_draft_path=? WHERE content_item_id=? AND markdown_draft_path=?",
                (str(destination_path), item_id, str(source_path)),
            )
        connection.commit()
    return {"documents": moved_documents, "attachments": moved_attachments}


def relocate_managed_documents(content_item_ids: list[str]) -> int:
    """Immediately reflect file-tree rename and move operations on disk."""
    identifiers = [str(item_id) for item_id in content_item_ids if str(item_id).strip()]
    if not identifiers:
        return 0
    initialize_database()
    moved = 0
    with connect() as connection:
        repository = ContentRepository(connection)
        for item_id in identifiers:
            document = connection.execute(
                "SELECT markdown_path, content_hash FROM content_documents WHERE content_item_id=?",
                (item_id,),
            ).fetchone()
            if document is None:
                continue
            source_path = Path(str(document["markdown_path"])).expanduser().resolve()
            if not source_path.exists() or not source_path.is_file():
                continue
            try:
                item = repository.get_content_item(item_id)
            except LookupError:
                continue
            target_path = _document_target_path(item, connection=connection)
            if target_path.resolve() == source_path:
                continue
            was_manually_modified = _hash(source_path.read_text(encoding="utf-8", errors="replace")) != str(document["content_hash"] or "")
            destination_path, relocated_markdown = _relocate_markdown_document(
                content_item_id=item_id,
                source_path=source_path,
                target_path=target_path,
                attachment_root=attachments_root(),
            )
            if was_manually_modified:
                connection.execute(
                    "UPDATE content_documents SET markdown_path=?, updated_at=? WHERE content_item_id=?",
                    (str(destination_path), utc_now_iso(), item_id),
                )
            else:
                connection.execute(
                    "UPDATE content_documents SET markdown_path=?, content_hash=?, updated_at=? WHERE content_item_id=?",
                    (str(destination_path), _hash(relocated_markdown), utc_now_iso(), item_id),
                )
            connection.execute(
                "UPDATE obsidian_sync SET markdown_draft_path=? WHERE content_item_id=? AND markdown_draft_path=?",
                (str(destination_path), item_id, str(source_path)),
            )
            moved += 1
        connection.commit()
    return moved


def align_sync_records_to_canonical_documents() -> int:
    """Point legacy sync rows at the canonical file-tree document.

    Older versions created a second flat Markdown file in the selected vault.
    The files are left alone for safety, but all future app writes must target
    the canonical library entry.
    """
    initialize_database()
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE obsidian_sync
               SET markdown_draft_path=(
                     SELECT markdown_path FROM content_documents
                     WHERE content_documents.content_item_id=obsidian_sync.content_item_id
                   ),
                   obsidian_path=(
                     SELECT markdown_path FROM content_documents
                     WHERE content_documents.content_item_id=obsidian_sync.content_item_id
                   )
               WHERE content_item_id IN (SELECT content_item_id FROM content_documents)"""
        )
        connection.commit()
        return int(cursor.rowcount or 0)


def _document_target_path(
    item: "ContentItemRecord",
    *,
    filename: str | None = None,
    connection: sqlite3.Connection | None = None,
    root: Path | None = None,
) -> Path:
    """Build the disk path from the exact hierarchy shown in the file tree."""
    # A generated report title already carries its full time window and group.
    # Keep only a compact, still collision-resistant identity suffix in its
    # filename; the durable database ID remains complete elsewhere.
    item_suffix = item.id[:12] if item.source_provider == "wechat_report" else item.id
    name = filename or f"{_safe_component(item.title)[:96]}--{item_suffix}.md"
    components = _library_folder_components(item.library_folder_id, connection=connection)
    if not components:
        components = [_provider_name(item.source_provider)]
    return (root or library_root()).joinpath(*(_safe_component(part) for part in components), name)


def _library_folder_components(
    folder_id: str | None,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[str]:
    if not folder_id:
        return []
    owns_connection = connection is None
    if owns_connection:
        initialize_database()
        connection = connect()
    try:
        components: list[str] = []
        current_id = str(folder_id)
        visited: set[str] = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            row = connection.execute(
                "SELECT name, parent_folder_id FROM library_folders WHERE id=? AND deleted_at IS NULL",
                (current_id,),
            ).fetchone()
            if row is None:
                break
            name = str(row["name"] or "").strip()
            if name:
                components.append(name)
            current_id = str(row["parent_folder_id"] or "")
        return list(reversed(components))
    finally:
        if owns_connection and connection is not None:
            connection.close()


def _relocate_markdown_document(
    *,
    content_item_id: str,
    source_path: Path,
    target_path: Path,
    attachment_root: Path,
) -> tuple[Path, str]:
    """Move a Markdown document while keeping its managed attachment links valid."""
    source_markdown = source_path.read_text(encoding="utf-8", errors="replace")
    rewritten = _rewrite_attachment_links(
        source_markdown,
        content_item_id=content_item_id,
        target_parent=target_path.parent,
        attachment_root=attachment_root,
    )
    destination = target_path
    if destination.exists() and destination.read_text(encoding="utf-8", errors="replace") != rewritten:
        suffix = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:8]
        destination = destination.with_name(f"{destination.stem}--migrated-{suffix}{destination.suffix}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination != source_path:
        if not destination.exists() or destination.read_text(encoding="utf-8", errors="replace") != rewritten:
            _atomic_write(destination, rewritten)
        source_path.unlink(missing_ok=True)
    return destination, rewritten


def _rewrite_attachment_links(markdown: str, *, content_item_id: str, target_parent: Path, attachment_root: Path) -> str:
    pattern = re.compile(r"\]\((?:\.\./)*attachments/" + re.escape(content_item_id) + r"/([^\n)]+)\)")

    def replace(match: re.Match[str]) -> str:
        attachment = attachment_root / content_item_id / match.group(1)
        relative = Path(os.path.relpath(attachment, start=target_parent)).as_posix()
        return f"]({relative})"

    return pattern.sub(replace, markdown)


def _update_document_path(content_item_id: str, path: Path) -> None:
    initialize_database()
    with connect() as connection:
        connection.execute(
            "UPDATE content_documents SET markdown_path=?, updated_at=? WHERE content_item_id=?",
            (str(path), utc_now_iso(), content_item_id),
        )
        connection.commit()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_migration_target(source: Path, target: Path) -> Path:
    if not target.exists() or not source.exists() or _hash_file(target) == _hash_file(source):
        return target
    suffix = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:8]
    return target.with_name(f"{target.stem}--migrated-{suffix}{target.suffix}")


def _merge_attachment_directory(source: Path, destination: Path) -> bool:
    """Merge an interrupted previous migration without overwriting either copy."""
    moved = False
    for child in source.rglob("*"):
        if not child.is_file():
            continue
        relative = child.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target = _safe_migration_target(child, target)
        if target.exists() and _hash_file(target) == _hash_file(child):
            child.unlink()
        else:
            shutil.move(str(child), str(target))
        moved = True
    shutil.rmtree(source, ignore_errors=True)
    return moved


def _preserve_generated_sections(next_markdown: str, existing_markdown: str) -> str:
    """Keep summaries and Q&A while refreshing only the source-material portion."""
    for heading in ("AI 摘要", "追问记录"):
        pattern = re.compile(rf"^## {re.escape(heading)}\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
        existing = pattern.search(existing_markdown)
        replacement = pattern.search(next_markdown)
        if existing and replacement:
            next_markdown = next_markdown[:replacement.start()] + existing.group(0).rstrip() + "\n" + next_markdown[replacement.end():]
    return next_markdown


def _upsert_document_index(content_item_id: str, path: Path, markdown: str) -> None:
    initialize_database()
    with connect() as connection:
        connection.execute(
            """INSERT INTO content_documents (content_item_id, markdown_path, content_hash, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(content_item_id) DO UPDATE SET
                 markdown_path=excluded.markdown_path,
                 content_hash=excluded.content_hash,
                 updated_at=excluded.updated_at""",
            (content_item_id, str(path), _hash(markdown), utc_now_iso()),
        )
        connection.commit()


def _document_is_manually_modified(content_item_id: str, path: Path) -> bool:
    try:
        actual_hash = _hash(path.read_text(encoding="utf-8"))
    except OSError:
        return True
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT content_hash FROM content_documents WHERE content_item_id = ?",
            (content_item_id,),
        ).fetchone()
    return bool(row and str(row["content_hash"] or "") != actual_hash)


def _copy_attachment(source: Path, directory: Path, stem: str) -> Path | None:
    if not source.exists() or not source.is_file():
        return None
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{stem}{source.suffix.lower() or '.bin'}"
    if not destination.exists() or _hash_file(destination) != _hash_file(source):
        shutil.copy2(source, destination)
    return destination


def _month_key(value: str) -> str:
    matched = re.search(r"(20\d{2})[-/]?(\d{1,2})", value or "")
    if matched:
        return f"{matched.group(1)}-{int(matched.group(2)):02d}"
    return datetime.now().strftime("%Y-%m")


def _provider_name(provider: str) -> str:
    return {"wechat": "微信公众号", "campus": "校园官网", "bilibili": "B站", "douyin": "抖音", "wechat_miniprogram": "微信小程序"}.get(provider, provider or "其他来源")


def _safe_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    return cleaned.rstrip(" .") or "未命名"


def _yaml_scalar(value: object) -> str:
    return '"' + str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp", delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
