"""Recover app-generated Markdown after selecting an existing library root.

The selected directory may also be an ordinary Obsidian vault.  Recovery is
therefore deliberately strict: only Markdown carrying the fixed KnowledgeHub
frontmatter contract is admitted, and the source files are never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from services.bilibili_url import extract_bvid, requested_page_number
from services.database import connect, initialize_database, utc_now_iso
from services.providers.douyin import DOUYIN_VIDEO_ID_RE
from services.repository import new_id
from services.wechat_urls import canonical_wechat_article_id
from services.xiaohongshu_client import note_id_from_url

MAX_MARKDOWN_FILES = 20_000
MAX_FRONTMATTER_BYTES = 64 * 1024
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_RE = re.compile(r"^([a-z_]+):\s*(.*)$")
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SUPPORTED_SOURCE_TYPES = frozenset(
    {"bilibili", "campus", "douyin", "local_file", "rss", "wechat", "xiaohongshu"}
)
_ARTICLE_PROVIDERS = frozenset({"campus", "rss", "wechat", "xiaohongshu"})
_DEFAULT_FOLDER_NAMES = {
    "bilibili": "Bilibili",
    "campus": "校园官网",
    "douyin": "抖音",
    "local_file": "外部导入",
    "rss": "RSS订阅",
    "wechat": "微信公众号",
    "xiaohongshu": "小红书",
}


@dataclass(frozen=True)
class ExistingLibraryDocument:
    item_id: str
    source_provider: str
    source_url: str
    source_name: str
    published_at: str
    fetched_at: str
    declared_content_hash: str
    title: str
    path: Path
    folder_parts: tuple[str, ...]


def empty_recovery_stats() -> dict[str, int | bool]:
    return {
        "scanned_markdown": 0,
        "recognized_documents": 0,
        "restored_documents": 0,
        "existing_documents": 0,
        "conflicted_documents": 0,
        "skipped_documents": 0,
        "restored_folders": 0,
        "scan_truncated": False,
    }


def recover_existing_library(vault_path: str | Path) -> dict[str, int | bool]:
    """Index recognized local documents without moving or modifying them."""
    stats = empty_recovery_stats()
    vault = Path(vault_path).expanduser().resolve()
    library = (vault / "library").resolve()
    if not library.is_dir() or not _is_relative_to(library, vault):
        return stats

    documents: list[ExistingLibraryDocument] = []
    for path in _markdown_paths(library):
        if int(stats["scanned_markdown"]) >= MAX_MARKDOWN_FILES:
            stats["scan_truncated"] = True
            break
        stats["scanned_markdown"] = int(stats["scanned_markdown"]) + 1
        document = _read_document(path, library)
        if document is None:
            stats["skipped_documents"] = int(stats["skipped_documents"]) + 1
            continue
        documents.append(document)
    stats["recognized_documents"] = len(documents)
    if not documents:
        return stats

    initialize_database()
    with connect() as connection:
        folder_cache = _active_folder_paths(connection)
        for document in documents:
            outcome, created_folders = _restore_document(
                connection, document, folder_cache
            )
            stats[f"{outcome}_documents"] = int(stats[f"{outcome}_documents"]) + 1
            stats["restored_folders"] = int(stats["restored_folders"]) + created_folders
        connection.commit()
    return stats


def _markdown_paths(library: Path):
    for current_root, directory_names, filenames in os.walk(library, followlinks=False):
        current = Path(current_root)
        directory_names[:] = sorted(
            name
            for name in directory_names
            if not name.startswith(".") and not (current / name).is_symlink()
        )
        for filename in sorted(filenames):
            if not filename.lower().endswith(".md") or filename.startswith("."):
                continue
            path = current / filename
            if path.is_symlink() or not path.is_file():
                continue
            resolved = path.resolve()
            if _is_relative_to(resolved, library):
                yield resolved


def _read_document(path: Path, library: Path) -> ExistingLibraryDocument | None:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(MAX_FRONTMATTER_BYTES)
    except OSError:
        return None
    text = prefix.decode("utf-8", errors="replace").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    metadata: dict[str, object] = {}
    for line in text[4:end].splitlines():
        match = _KEY_RE.match(line)
        if match is None:
            return None
        key, raw_value = match.groups()
        try:
            metadata[key] = json.loads(raw_value)
        except json.JSONDecodeError:
            return None

    item_id = str(metadata.get("id") or "").strip().lower()
    provider = str(metadata.get("source_type") or "").strip().lower()
    source_url = str(metadata.get("source_url") or "").strip()
    content_hash = str(metadata.get("content_hash") or "").strip().lower()
    if (
        not _ID_RE.fullmatch(item_id)
        or provider not in _SUPPORTED_SOURCE_TYPES
        or not _valid_source_url(provider, source_url)
        or not _HASH_RE.fullmatch(content_hash)
    ):
        return None
    title_match = _TITLE_RE.search(text[end + 5 :])
    title = " ".join(str(title_match.group(1) if title_match else path.stem).split())[
        :500
    ]
    if not title:
        return None
    try:
        folder_parts = tuple(path.parent.relative_to(library).parts)
    except ValueError:
        return None
    if any(not part or part in {".", ".."} or len(part) > 120 for part in folder_parts):
        return None
    return ExistingLibraryDocument(
        item_id=item_id,
        source_provider=provider,
        source_url=source_url,
        source_name=str(metadata.get("source_name") or "").strip()[:500],
        published_at=str(metadata.get("published_at") or "").strip()[:120],
        fetched_at=str(metadata.get("fetched_at") or "").strip()[:120],
        declared_content_hash=content_hash,
        title=title,
        path=path,
        folder_parts=folder_parts,
    )


def _restore_document(
    connection: sqlite3.Connection,
    document: ExistingLibraryDocument,
    folder_cache: dict[tuple[str, ...], str],
) -> tuple[str, int]:
    existing_id = connection.execute(
        "SELECT id FROM content_items WHERE id=?",
        (document.item_id,),
    ).fetchone()
    existing_path = connection.execute(
        "SELECT markdown_path FROM content_documents WHERE content_item_id=?",
        (document.item_id,),
    ).fetchone()
    if existing_id:
        if (
            existing_path
            and Path(str(existing_path["markdown_path"])).expanduser().resolve()
            == document.path
        ):
            return "existing", 0
        return "conflicted", 0

    canonical_id = _canonical_source_id(document.source_provider, document.source_url)
    duplicate = connection.execute(
        """SELECT id FROM content_items
           WHERE source_provider=? AND (
             (? <> '' AND canonical_source_id=?) OR
             (? <> '' AND source_url=?)
           ) LIMIT 1""",
        (
            document.source_provider,
            canonical_id,
            canonical_id,
            document.source_url,
            document.source_url,
        ),
    ).fetchone()
    if duplicate:
        return "conflicted", 0

    try:
        file_hash = _file_hash(document.path)
    except OSError:
        return "skipped", 0

    folder_parts = document.folder_parts or (
        _DEFAULT_FOLDER_NAMES[document.source_provider],
    )
    folder_id, created_folders = _ensure_folder_path(
        connection, folder_parts, folder_cache
    )
    timestamp = _valid_timestamp(document.fetched_at) or _file_timestamp(document.path)
    published_at = _valid_timestamp(document.published_at) or None
    content_type = (
        "article" if document.source_provider in _ARTICLE_PROVIDERS else "video"
    )
    if document.source_provider == "local_file":
        content_type = "document"
    connection.execute(
        """INSERT INTO content_items (
             id, content_type, source_provider, source_url, canonical_source_id,
             title, status, library_folder_id, library_visible, sort_order,
             published_at, source_name, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, 'to_read', ?, 1, 0, ?, ?, ?, ?)""",
        (
            document.item_id,
            content_type,
            document.source_provider,
            document.source_url,
            canonical_id or None,
            document.title,
            folder_id,
            published_at,
            document.source_name or None,
            timestamp,
            timestamp,
        ),
    )
    connection.execute(
        """INSERT INTO content_documents (content_item_id, markdown_path, content_hash, updated_at)
           VALUES (?, ?, ?, ?)""",
        (document.item_id, str(document.path), file_hash, utc_now_iso()),
    )
    return "restored", created_folders


def _active_folder_paths(connection: sqlite3.Connection) -> dict[tuple[str, ...], str]:
    rows = connection.execute(
        "SELECT id, name, parent_folder_id FROM library_folders WHERE deleted_at IS NULL"
    ).fetchall()
    by_parent: dict[str | None, list[sqlite3.Row]] = {}
    for row in rows:
        parent = str(row["parent_folder_id"]) if row["parent_folder_id"] else None
        by_parent.setdefault(parent, []).append(row)
    result: dict[tuple[str, ...], str] = {}

    def visit(
        parent_id: str | None, prefix: tuple[str, ...], visiting: set[str]
    ) -> None:
        for row in by_parent.get(parent_id, []):
            folder_id = str(row["id"])
            if folder_id in visiting:
                continue
            path = (*prefix, str(row["name"]))
            result.setdefault(path, folder_id)
            visit(folder_id, path, {*visiting, folder_id})

    visit(None, (), set())
    return result


def _ensure_folder_path(
    connection: sqlite3.Connection,
    parts: tuple[str, ...],
    cache: dict[tuple[str, ...], str],
) -> tuple[str | None, int]:
    parent_id: str | None = None
    created = 0
    prefix: tuple[str, ...] = ()
    for position, part in enumerate(parts):
        prefix = (*prefix, part)
        folder_id = cache.get(prefix)
        if folder_id is None:
            folder_id = new_id()
            now = utc_now_iso()
            connection.execute(
                """INSERT INTO library_folders
                   (id, name, parent_folder_id, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (folder_id, part, parent_id, float(position), now, now),
            )
            cache[prefix] = folder_id
            created += 1
        parent_id = folder_id
    return parent_id, created


def _canonical_source_id(provider: str, source_url: str) -> str:
    if provider == "bilibili":
        bvid = extract_bvid(source_url) or ""
        page = requested_page_number(source_url)
        return f"{bvid}:p{page}" if bvid and page > 1 else bvid
    if provider == "douyin":
        match = DOUYIN_VIDEO_ID_RE.search(source_url)
        return match.group("id") if match else source_url
    if provider == "wechat":
        return canonical_wechat_article_id(source_url)
    if provider == "xiaohongshu":
        try:
            return note_id_from_url(source_url)
        except ValueError:
            return source_url
    return source_url


def _valid_source_url(provider: str, source_url: str) -> bool:
    if provider == "local_file":
        return source_url.startswith("local-file:") and len(source_url) <= 2048
    parsed = urlparse(source_url)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and len(source_url) <= 4096
    )


def _valid_timestamp(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return utc_now_iso()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
