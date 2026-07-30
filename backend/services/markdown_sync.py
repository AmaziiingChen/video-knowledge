from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from config import settings
from services.database import connect, ensure_database_initialized, initialize_database, utc_now_iso
from services.obsidian_settings import automatic_markdown_write_enabled, content_library_root
from services.repository import new_id
from services.search_index import upsert_source_text_document
from services.summarizer import resolve_obsidian_note_path
from services.telemetry import record as record_telemetry


@dataclass(frozen=True)
class MarkdownSyncState:
    content_item_id: str | None
    markdown_draft_path: str
    obsidian_path: str | None
    markdown: str
    sync_status: str
    conflict: bool
    last_synced_hash: str | None
    external_hash: str | None
    last_synced_at: str | None


def save_markdown_draft_and_sync(
    *,
    markdown: str,
    title: str,
    obsidian_path: Path,
    content_item_id: str | None = None,
    series_id: str | None = None,
    draft_key: str | None = None,
    document_name: str | None = None,
) -> MarkdownSyncState:
    should_write = automatic_markdown_write_enabled()
    if content_item_id:
        from services.knowledge_library import write_content_markdown_document

        draft_path = write_content_markdown_document(
            content_item_id,
            markdown,
            document_name=document_name,
        )
        # With automatic writing enabled, the canonical document already lives
        # under the selected storage root.  Do not create a second flat copy.
        note_path = draft_path if _is_under_root(draft_path, content_library_root()) else resolve_obsidian_note_path(obsidian_path)
    else:
        draft_path = _draft_path_for(title=title, key=draft_key)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(markdown, encoding="utf-8")
        note_path = resolve_obsidian_note_path(obsidian_path)

    if should_write and note_path != draft_path:
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(markdown, encoding="utf-8")

    markdown_hash = _hash_text(markdown)
    ensure_database_initialized()
    with connect() as connection:
        _upsert_sync_record(
            connection,
            content_item_id=content_item_id,
            series_id=series_id,
            markdown_draft_path=str(draft_path),
            obsidian_path=str(note_path),
            last_synced_hash=markdown_hash,
            external_hash=markdown_hash if should_write else None,
            sync_status="synced" if should_write else "dirty",
            last_synced_at=utc_now_iso() if should_write else None,
        )
        connection.commit()
    return _state_from_values(
        content_item_id=content_item_id,
        markdown_draft_path=str(draft_path),
        obsidian_path=str(note_path),
        markdown=markdown,
        sync_status="synced" if should_write else "dirty",
        last_synced_hash=markdown_hash,
        external_hash=markdown_hash if should_write else None,
        last_synced_at=utc_now_iso() if should_write else None,
    )


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return False


def get_markdown_state(content_item_id: str) -> MarkdownSyncState:
    initialize_database()
    with connect() as connection:
        row = _get_sync_row(connection, content_item_id)
        if row is None:
            raise LookupError("markdown draft not found")
        row = _recover_missing_draft_path(connection, row)
        connection.commit()
        return _state_from_row(row, refresh_sync_status=True)


def ensure_content_markdown_state(content_item_id: str) -> MarkdownSyncState:
    """Expose a Markdown-first source document through the editable draft state.

    Newly ingested articles already have a canonical file under ``data/library``
    but deliberately have no legacy ``obsidian_sync`` row until an AI summary is
    requested.  Promoting that existing file avoids a second, divergent draft.
    """
    initialize_database()
    with connect() as connection:
        row = _get_sync_row(connection, content_item_id)
        if row is not None:
            row = _recover_missing_draft_path(connection, row)
            connection.commit()
            return _state_from_row(row, refresh_sync_status=True)

        document = connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id = ?",
            (content_item_id,),
        ).fetchone()
        canonical_path = Path(str(document["markdown_path"])) if document else None
        if canonical_path is None or not canonical_path.exists() or not canonical_path.is_file():
            raise LookupError("markdown draft not found")
        _ensure_under_data_dir(canonical_path)
        markdown = canonical_path.read_text(encoding="utf-8")
        markdown_hash = _hash_text(markdown)
        auto_write = automatic_markdown_write_enabled()
        note_path: Path | None = None
        if auto_write:
            note_path = canonical_path if _is_under_root(canonical_path, content_library_root()) else resolve_obsidian_note_path(settings.obsidian_vault / canonical_path.name)
            if note_path != canonical_path:
                note_path.parent.mkdir(parents=True, exist_ok=True)
                note_path.write_text(markdown, encoding="utf-8")
        _upsert_sync_record(
            connection,
            content_item_id=content_item_id,
            series_id=None,
            markdown_draft_path=str(canonical_path),
            obsidian_path=str(note_path) if note_path else None,
            last_synced_hash=markdown_hash,
            external_hash=markdown_hash if note_path else None,
            sync_status="synced",
            last_synced_at=utc_now_iso(),
        )
        connection.commit()
        return _state_from_values(
            content_item_id=content_item_id,
            markdown_draft_path=str(canonical_path),
            obsidian_path=str(note_path) if note_path else None,
            markdown=markdown,
            sync_status="synced",
            last_synced_hash=markdown_hash,
            external_hash=markdown_hash if note_path else None,
            last_synced_at=utc_now_iso(),
        )


def update_markdown_draft(content_item_id: str, markdown: str) -> MarkdownSyncState:
    initialize_database()
    with connect() as connection:
        row = _get_sync_row(connection, content_item_id)
        if row is None:
            raise LookupError("markdown draft not found")
        row = _recover_missing_draft_path(connection, row)
        draft_path = Path(row["markdown_draft_path"])
        _ensure_under_data_dir(draft_path)
        external_path = str(row["obsidian_path"] or "").strip()
        shared_canonical_file = bool(external_path) and _same_path(draft_path, Path(external_path))
        content_row = connection.execute(
            "SELECT title FROM content_items WHERE id = ?",
            (content_item_id,),
        ).fetchone()
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(markdown, encoding="utf-8")
        markdown_hash = _hash_text(markdown)
        if shared_canonical_file and automatic_markdown_write_enabled():
            # The application-owned Markdown is canonical.  When the selected
            # library is also exposed to Obsidian, an in-app save deliberately
            # replaces any external edit rather than splitting the document.
            connection.execute(
                """
                UPDATE obsidian_sync
                SET sync_status='synced', last_synced_hash=?, external_hash=?, last_synced_at=?
                WHERE id=?
                """,
                (markdown_hash, markdown_hash, utc_now_iso(), row["id"]),
            )
        else:
            connection.execute(
                "UPDATE obsidian_sync SET sync_status='dirty', external_hash=? WHERE id=?",
                (_file_hash(Path(row["obsidian_path"])) if row["obsidian_path"] else None, row["id"]),
            )
        connection.commit()
        updated_state = _state_from_row(_get_sync_row(connection, content_item_id), refresh_sync_status=False)

    if content_row is not None:
        upsert_source_text_document(
            content_key=content_item_id,
            title=str(content_row["title"] or ""),
            transcript=markdown,
        )
    return updated_state


def sync_markdown_to_obsidian(content_item_id: str, *, force: bool = False) -> MarkdownSyncState:
    initialize_database()
    with connect() as connection:
        row = _get_sync_row(connection, content_item_id)
        if row is None:
            raise LookupError("markdown draft not found")
        row = _recover_missing_draft_path(connection, row)
        # ``force`` remains accepted for older callers.  The application-owned
        # document is now always authoritative, so every sync is an overwrite.
        del force
        state = _state_from_row(row, refresh_sync_status=True)

        if not state.obsidian_path:
            raise ValueError("缺少 Obsidian 路径")
        note_path = resolve_obsidian_note_path(state.obsidian_path)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(state.markdown, encoding="utf-8")
        markdown_hash = _hash_text(state.markdown)
        connection.execute(
            """
            UPDATE obsidian_sync
            SET last_synced_hash = ?,
                external_hash = ?,
                sync_status = 'synced',
                last_synced_at = ?
            WHERE id = ?
            """,
            (markdown_hash, markdown_hash, utc_now_iso(), row["id"]),
        )
        connection.commit()
        record_telemetry("obsidian_sync_completed", {"result": "succeeded"})
        return _state_from_row(_get_sync_row(connection, content_item_id), refresh_sync_status=False)


def sync_draft_from_obsidian(content_item_id: str, obsidian_path: str | Path) -> MarkdownSyncState:
    note_path = resolve_obsidian_note_path(obsidian_path)
    if not note_path.exists() or not note_path.is_file():
        raise ValueError("对应的 Obsidian 笔记不存在")
    markdown = note_path.read_text(encoding="utf-8")
    markdown_hash = _hash_text(markdown)

    initialize_database()
    with connect() as connection:
        row = _get_sync_row(connection, content_item_id)
        if row is None:
            raise LookupError("markdown draft not found")
        row = _recover_missing_draft_path(connection, row)
        draft_path = Path(row["markdown_draft_path"])
        _ensure_under_data_dir(draft_path)
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(markdown, encoding="utf-8")
        connection.execute(
            """
            UPDATE obsidian_sync
            SET obsidian_path = ?,
                last_synced_hash = ?,
                external_hash = ?,
                sync_status = 'synced',
                last_synced_at = ?
            WHERE id = ?
            """,
            (str(note_path), markdown_hash, markdown_hash, utc_now_iso(), row["id"]),
        )
        connection.commit()
        return _state_from_row(_get_sync_row(connection, content_item_id), refresh_sync_status=False)


def replace_content_summary_and_sync(
    content_item_id: str,
    summary: str,
    *,
    drop_generated_title: bool = False,
) -> MarkdownSyncState:
    """Replace a content item's canonical summary and sync the existing note."""
    replacement = _normalize_generated_article_summary(summary, drop_generated_title=drop_generated_title)
    if not replacement:
        raise ValueError("重新生成的文章总结为空")

    state = ensure_content_markdown_state(content_item_id)
    auto_write = automatic_markdown_write_enabled()

    legacy_pattern = re.compile(
        r"(^# [^\r\n]+\r?\n(?:\r?\n)+)(.*?)(\r?\n\r?\n<details>\r?\n<summary>原文正文</summary>)",
        re.MULTILINE | re.DOTALL,
    )
    match = legacy_pattern.search(state.markdown)
    if match is not None:
        updated_markdown = (
            state.markdown[:match.start()]
            + match.group(1)
            + replacement
            + match.group(3)
            + state.markdown[match.end():]
        )
    else:
        # Assistant summaries may contain ordinary H2 sections (notably a
        # generated weekly report).  Only the reserved Q&A section ends this
        # block; heading depth inside generated content is not structural.
        canonical_pattern = re.compile(
            r"(^## AI 摘要\s*\n)(.*?)(?=^## 追问记录\s*$|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        canonical_match = canonical_pattern.search(state.markdown)
        if canonical_match is None:
            updated_markdown = state.markdown.rstrip() + f"\n\n## AI 摘要\n\n{replacement}\n"
        else:
            updated_markdown = (
                state.markdown[:canonical_match.start()]
                + canonical_match.group(1)
                + "\n"
                + replacement
                + "\n\n"
                + state.markdown[canonical_match.end():].lstrip("\n")
            )
    update_markdown_draft(content_item_id, updated_markdown)
    if auto_write:
        return sync_markdown_to_obsidian(content_item_id)
    return get_markdown_state(content_item_id)


def replace_article_summary_and_sync(content_item_id: str, summary: str) -> MarkdownSyncState:
    """Compatibility wrapper for existing article-summary callers."""
    return replace_content_summary_and_sync(content_item_id, summary)


def _normalize_generated_article_summary(summary: str, *, drop_generated_title: bool = False) -> str:
    """Drop the filename-style first line emitted by article summary prompts."""
    replacement = str(summary or "").strip()
    lines = replacement.splitlines()
    if len(lines) < 2:
        return replacement

    first = lines[0].strip()
    remaining = "\n".join(lines[1:]).lstrip()
    if drop_generated_title and first and not first.startswith("#"):
        return remaining
    if first and not first.startswith("##") and remaining.startswith("##"):
        return remaining
    return replacement


def _upsert_sync_record(
    connection: sqlite3.Connection,
    *,
    content_item_id: str | None,
    series_id: str | None,
    markdown_draft_path: str,
    obsidian_path: str,
    last_synced_hash: str,
    external_hash: str,
    sync_status: str,
    last_synced_at: str,
) -> None:
    row = _get_sync_row(connection, content_item_id) if content_item_id else None
    if row:
        connection.execute(
            """
            UPDATE obsidian_sync
            SET markdown_draft_path = ?,
                obsidian_path = ?,
                last_synced_hash = ?,
                external_hash = ?,
                sync_status = ?,
                last_synced_at = ?
            WHERE id = ?
            """,
            (
                markdown_draft_path,
                obsidian_path,
                last_synced_hash,
                external_hash,
                sync_status,
                last_synced_at,
                row["id"],
            ),
        )
        return

    connection.execute(
        """
        INSERT INTO obsidian_sync (
            id, content_item_id, series_id, markdown_draft_path, obsidian_path,
            last_synced_hash, external_hash, sync_status, last_synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            content_item_id,
            series_id,
            markdown_draft_path,
            obsidian_path,
            last_synced_hash,
            external_hash,
            sync_status,
            last_synced_at,
        ),
    )


def _get_sync_row(connection: sqlite3.Connection, content_item_id: str | None) -> sqlite3.Row | None:
    if not content_item_id:
        return None
    return connection.execute(
        """
        SELECT * FROM obsidian_sync
        WHERE content_item_id = ?
        ORDER BY last_synced_at DESC
        LIMIT 1
        """,
        (content_item_id,),
    ).fetchone()


def _recover_missing_draft_path(connection: sqlite3.Connection, row: sqlite3.Row) -> sqlite3.Row:
    """Move stale legacy draft references to the migrated canonical Markdown."""
    legacy_path = Path(row["markdown_draft_path"])
    if legacy_path.exists() and legacy_path.is_file():
        return row
    content_item_id = str(row["content_item_id"] or "")
    document = connection.execute(
        "SELECT markdown_path FROM content_documents WHERE content_item_id = ?",
        (content_item_id,),
    ).fetchone()
    canonical_path = Path(str(document["markdown_path"])) if document else None
    if canonical_path is None or not canonical_path.exists() or not canonical_path.is_file():
        raise LookupError("本地 Markdown 已清理，且没有可恢复的迁移文档")
    _ensure_under_data_dir(canonical_path)
    connection.execute(
        "UPDATE obsidian_sync SET markdown_draft_path = ? WHERE id = ?",
        (str(canonical_path), row["id"]),
    )
    recovered = _get_sync_row(connection, content_item_id)
    if recovered is None:
        raise LookupError("markdown draft not found")
    return recovered


def _state_from_row(
    row: sqlite3.Row | None,
    *,
    refresh_sync_status: bool,
) -> MarkdownSyncState:
    if row is None:
        raise LookupError("markdown draft not found")
    draft_path = Path(row["markdown_draft_path"])
    _ensure_under_data_dir(draft_path)
    markdown = draft_path.read_text(encoding="utf-8")
    external_hash = _file_hash(Path(row["obsidian_path"])) if row["obsidian_path"] else None
    # Obsidian is an export mirror, not a concurrent editor.  Keep reporting
    # its current fingerprint for diagnostics, but never turn an external edit
    # or a deleted export into a conflict that blocks the application pipeline.
    sync_status = "dirty" if row["sync_status"] == "conflict" else row["sync_status"]
    if refresh_sync_status and sync_status == "synced" and _hash_text(markdown) != row["last_synced_hash"]:
        sync_status = "dirty"
    return _state_from_values(
        content_item_id=row["content_item_id"],
        markdown_draft_path=str(draft_path),
        obsidian_path=row["obsidian_path"],
        markdown=markdown,
        sync_status=sync_status,
        last_synced_hash=row["last_synced_hash"],
        external_hash=external_hash,
        last_synced_at=row["last_synced_at"],
    )


def _state_from_values(
    *,
    content_item_id: str | None,
    markdown_draft_path: str,
    obsidian_path: str | None,
    markdown: str,
    sync_status: str,
    last_synced_hash: str | None,
    external_hash: str | None,
    last_synced_at: str | None,
) -> MarkdownSyncState:
    return MarkdownSyncState(
        content_item_id=content_item_id,
        markdown_draft_path=markdown_draft_path,
        obsidian_path=obsidian_path,
        markdown=markdown,
        sync_status="dirty" if sync_status == "conflict" else sync_status,
        conflict=False,
        last_synced_hash=last_synced_hash,
        external_hash=external_hash,
        last_synced_at=last_synced_at,
    )


def _draft_path_for(*, title: str, key: str | None) -> Path:
    safe_key = _safe_filename(key or title or "untitled")
    safe_title = _safe_filename(title or "untitled")[:80]
    return settings.data_dir / "drafts" / f"{safe_key}-{safe_title}.md"


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in " -_" else "_" for char in value).strip()
    return cleaned[:90] or "untitled"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_under_data_dir(path: Path) -> None:
    resolved = path.resolve()
    for root in (settings.data_dir.resolve(), content_library_root().resolve()):
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue
    raise ValueError("Markdown 草稿必须位于应用数据目录或当前资料库目录下")
