from __future__ import annotations

from pathlib import Path
import hashlib
import sqlite3
from threading import RLock

from config import settings
from services.bilibili_url import bilibili_video_id_from_page_url, requested_page_number
from services.cache import list_cache_entries, read_cache_meta
from services.database import connect, initialize_database, utc_now_iso
from services.repository import ContentItemRecord, ContentRepository, new_id

DEFAULT_PROVIDER_FOLDERS = {
    "douyin": "抖音",
    "bilibili": "B站",
    "wechat": "微信公众号",
    "campus": "校园官网",
    "wechat_miniprogram": "微信小程序",
    "rss": "RSS订阅",
    "xiaohongshu": "小红书",
}
MANUAL_COLLECTION_FOLDER_NAME = "待整理收藏"
MANUAL_WECHAT_FOLDER_NAME = "手动收藏"
EXTERNAL_MARKDOWN_FOLDER_NAME = "外部导入"
_PRECREATED_CAMPUS_SOURCE_FOLDERS = ("采购与招投标管理中心",)

_CONTENT_INDEX_READY_LOCK = RLock()
_CONTENT_INDEX_READY_ROOTS: set[str] = set()
_CONTENT_INDEX_READY_VERSION = "4"
_CONTENT_INDEX_READY_MARKER = "content_index_ready.version"


def ensure_content_index_ready() -> None:
    """Run legacy cache and folder backfills once per data directory version.

    Every normal ingestion path already assigns a folder. The expensive cache
    scan is only for upgrading older installations, so repeating it at every
    backend restart would make the first file-tree request unnecessarily slow.
    """
    data_root = str(settings.data_dir.expanduser().resolve())
    with _CONTENT_INDEX_READY_LOCK:
        if data_root in _CONTENT_INDEX_READY_ROOTS:
            return
        # Unlike legacy cache repair, this is a small, durable tree invariant:
        # imported documents always have one predictable place in the sidebar.
        ensure_external_markdown_library()
        marker = settings.data_dir / _CONTENT_INDEX_READY_MARKER
        try:
            if marker.read_text(encoding="utf-8").strip() == _CONTENT_INDEX_READY_VERSION:
                _CONTENT_INDEX_READY_ROOTS.add(data_root)
                return
        except OSError:
            pass
        # Directly shared links now return to their detected platform.  The
        # collection folder remains a true fallback inbox for unknown sources.
        migrate_manual_collection_items()
        backfill_content_items_from_cache()
        backfill_default_provider_folders()
        migrate_manual_collection_items()
        backfill_campus_source_folders()
        backfill_wechat_subscription_folders()
        repair_rss_source_folders()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(_CONTENT_INDEX_READY_VERSION + "\n", encoding="utf-8")
        _CONTENT_INDEX_READY_ROOTS.add(data_root)


def ensure_content_item_for_media(
    *,
    source_provider: str,
    source_url: str | None,
    video_info: dict | None = None,
    title: str | None = None,
    content_type: str = "video",
    status: str = "processing",
    library_folder_id: str | None = None,
) -> ContentItemRecord | None:
    provider = source_provider or (video_info or {}).get("platform") or "unknown"
    canonical_id = _canonical_source_id(source_url=source_url, video_info=video_info)
    item_title = title or (video_info or {}).get("title") or canonical_id or "未命名内容"
    duration = _duration_seconds(video_info)

    initialize_database()
    with connect() as connection:
        folder_id = library_folder_id or ensure_default_provider_folder(connection, provider)
        item = _find_existing(connection, provider=provider, source_url=source_url, canonical_id=canonical_id)
        if item:
            _update_content_item(
                connection,
                item.id,
                title=item_title,
                source_url=source_url,
                canonical_id=canonical_id,
                duration_seconds=duration,
                status=status,
                library_folder_id=folder_id if item.library_folder_id is None else item.library_folder_id,
            )
            connection.commit()
            return ContentRepository(connection).get_content_item(item.id)

        try:
            item = ContentRepository(connection).create_content_item(
                content_type=content_type,
                source_provider=provider,
                source_url=source_url,
                canonical_source_id=canonical_id,
                title=item_title,
                duration_seconds=duration,
                status=status,
                library_folder_id=folder_id,
            )
            connection.commit()
            return item
        except sqlite3.IntegrityError:
            connection.rollback()
            with connect() as retry_connection:
                item = _find_existing(
                    retry_connection,
                    provider=provider,
                    source_url=source_url,
                    canonical_id=canonical_id,
                )
                return item


def ensure_manual_collection_folder(connection: sqlite3.Connection) -> str:
    """Return the fallback inbox for collected links without a destination."""
    return ensure_managed_folder(
        connection,
        source_type="manual_collection",
        source_key="default",
        name=MANUAL_COLLECTION_FOLDER_NAME,
        sort_order=5,
    )


def ensure_external_markdown_folder(connection: sqlite3.Connection) -> str:
    """Return the user-managed root for imported local Markdown files."""
    return ensure_managed_folder(
        connection,
        source_type="external_markdown",
        source_key="root",
        name=EXTERNAL_MARKDOWN_FOLDER_NAME,
        sort_order=70,
    )


def ensure_external_markdown_library() -> int:
    """Create the external-import root and repair unfiled local imports."""
    initialize_database()
    with connect() as connection:
        folder_id = ensure_external_markdown_folder(connection)
        cursor = connection.execute(
            """
            UPDATE content_items
            SET library_folder_id = ?, updated_at = ?
            WHERE source_provider IN ('local_markdown', 'local_file')
              AND library_folder_id IS NULL
              AND deleted_at IS NULL
            """,
            (folder_id, utc_now_iso()),
        )
        connection.commit()
    return cursor.rowcount or 0


def ensure_manual_collection_target_folder(connection: sqlite3.Connection, provider: str) -> str:
    """Route an explicit collection to its source root, with an inbox fallback.

    A folder describes how people browse content, while ``source_provider``
    remains the durable source-of-truth.  New providers automatically join
    this behavior as soon as they declare a default provider root.
    """
    normalized_provider = str(provider or "").strip()
    if normalized_provider == "wechat":
        return ensure_manual_wechat_folder(connection)
    if normalized_provider in DEFAULT_PROVIDER_FOLDERS:
        folder_id = ensure_default_provider_folder(connection, normalized_provider)
        if folder_id:
            return folder_id
    return ensure_manual_collection_folder(connection)


def ensure_manual_wechat_folder(connection: sqlite3.Connection) -> str:
    """Keep manually shared WeChat articles separate from subscriptions."""
    root_folder_id = ensure_default_provider_folder(connection, "wechat")
    if not root_folder_id:
        raise ValueError("未能创建微信公众号根文件夹")
    return ensure_managed_folder(
        connection,
        source_type="manual_collection",
        source_key="wechat",
        name=MANUAL_WECHAT_FOLDER_NAME,
        parent_folder_id=root_folder_id,
    )


def migrate_manual_collection_items() -> int:
    """Move existing known-source items out of the legacy collection inbox."""
    initialize_database()
    with connect() as connection:
        folder_id = _bound_folder_id(connection, "manual_collection", "default")
        if not folder_id:
            row = connection.execute(
                """SELECT id FROM library_folders
                   WHERE parent_folder_id IS NULL AND name=? AND deleted_at IS NULL LIMIT 1""",
                (MANUAL_COLLECTION_FOLDER_NAME,),
            ).fetchone()
            folder_id = str(row["id"]) if row else None
        if not folder_id:
            return 0
        rows = connection.execute(
            """SELECT id, source_provider FROM content_items
               WHERE deleted_at IS NULL AND library_folder_id=?""",
            (folder_id,),
        ).fetchall()
        if not rows:
            return 0
        updates: list[tuple[str, str, str]] = []
        for row in rows:
            provider = str(row["source_provider"] or "").strip()
            if provider not in DEFAULT_PROVIDER_FOLDERS:
                continue
            target_folder_id = ensure_manual_collection_target_folder(connection, provider)
            if target_folder_id != folder_id:
                updates.append((target_folder_id, utc_now_iso(), str(row["id"])))
        if not updates:
            return 0
        connection.executemany("UPDATE content_items SET library_folder_id=?,updated_at=? WHERE id=?", updates)
        connection.commit()
    return len(updates)


def backfill_content_items_from_cache() -> int:
    initialize_database()
    created = 0
    for entry in list_cache_entries(include_size=False):
        item = _upsert_cache_entry(entry)
        if item:
            created += 1
    return created


def _upsert_cache_entry(entry: dict) -> ContentItemRecord | None:
    source_url = entry.get("source_url") or None
    cache_key = entry.get("cache_key") or ""
    cache_dir = settings.data_dir / "cache" / cache_key
    meta = read_cache_meta(cache_dir)
    video_info = meta.get("video_info") or {}
    provider = entry.get("platform") or video_info.get("platform") or "unknown"
    if not source_url and provider != "local":
        return None

    canonical_id = _canonical_source_id(source_url=source_url, video_info=video_info) or cache_key
    title = entry.get("title") or video_info.get("title") or canonical_id or "未命名内容"
    pipeline_status = str(meta.get("pipeline_status") or "").strip()
    if pipeline_status == "failed":
        status = "failed"
    elif entry.get("obsidian_path") or entry.get("transcripts") or pipeline_status == "succeeded":
        status = "to_read"
    else:
        status = "inbox"

    initialize_database()
    with connect() as connection:
        folder_id = ensure_default_provider_folder(connection, provider)
        existing = _find_existing(connection, provider=provider, source_url=source_url, canonical_id=canonical_id)
        if existing:
            duration = _duration_seconds(video_info) or entry.get("duration")
            next_status = existing.status if existing.status != "inbox" else status
            next_folder_id = existing.library_folder_id or folder_id
            if (
                not existing.title
                or (source_url and not existing.source_url)
                or (canonical_id and not existing.canonical_source_id)
                or (duration and existing.duration_seconds is None)
                or existing.status != next_status
                or existing.library_folder_id != next_folder_id
            ):
                _update_content_item(
                    connection,
                    existing.id,
                    title=title,
                    source_url=source_url,
                    canonical_id=canonical_id,
                    duration_seconds=duration,
                    status=next_status,
                    library_folder_id=next_folder_id,
                )
            _ensure_obsidian_sync(connection, existing.id, title, entry.get("obsidian_path"))
            connection.commit()
            return None

        item = ContentRepository(connection).create_content_item(
            source_provider=provider,
            source_url=source_url,
            canonical_source_id=canonical_id,
            title=title,
            duration_seconds=_duration_seconds(video_info) or entry.get("duration"),
            status=status,
            library_folder_id=folder_id,
        )
        _ensure_obsidian_sync(connection, item.id, title, entry.get("obsidian_path"))
        connection.commit()
        return item


def _find_existing(
    connection: sqlite3.Connection,
    *,
    provider: str,
    source_url: str | None,
    canonical_id: str | None,
) -> ContentItemRecord | None:
    row = None
    if source_url:
        row = connection.execute(
            "SELECT * FROM content_items WHERE source_provider = ? AND source_url = ? LIMIT 1",
            (provider, source_url),
        ).fetchone()
    if row is None and canonical_id:
        row = connection.execute(
            "SELECT * FROM content_items WHERE source_provider = ? AND canonical_source_id = ? LIMIT 1",
            (provider, canonical_id),
        ).fetchone()
        if row is not None and provider == "bilibili" and source_url:
            requested_page = requested_page_number(source_url)
            existing_page = requested_page_number(str(row["source_url"] or ""))
            if requested_page != existing_page and existing_page > 1 and ":p" not in str(row["canonical_source_id"] or ""):
                existing_video_id = (
                    bilibili_video_id_from_page_url(str(row["source_url"] or ""))
                    or str(row["canonical_source_id"] or canonical_id)
                )
                repaired_id = f"{existing_video_id}:p{existing_page}"
                connection.execute(
                    "UPDATE content_items SET canonical_source_id=?, updated_at=? WHERE id=?",
                    (repaired_id, utc_now_iso(), row["id"]),
                )
                row = None
    if row is None:
        return None
    return ContentItemRecord(
        id=row["id"],
        content_type=row["content_type"],
        source_provider=row["source_provider"],
        source_url=row["source_url"],
        canonical_source_id=row["canonical_source_id"],
        title=row["title"],
        cover_url=row["cover_url"],
        duration_seconds=row["duration_seconds"],
        status=row["status"],
        series_id=row["series_id"],
        library_folder_id=row["library_folder_id"] if "library_folder_id" in row.keys() else None,
        sort_order=float(row["sort_order"] if "sort_order" in row.keys() else 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _update_content_item(
    connection: sqlite3.Connection,
    item_id: str,
    *,
    title: str,
    source_url: str | None,
    canonical_id: str | None,
    duration_seconds: float | None,
    status: str,
    library_folder_id: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE content_items
        SET title = COALESCE(NULLIF(?, ''), title),
            source_url = COALESCE(?, source_url),
            canonical_source_id = COALESCE(?, canonical_source_id),
            duration_seconds = COALESCE(?, duration_seconds),
            status = ?,
            library_folder_id = COALESCE(?, library_folder_id),
            updated_at = ?
        WHERE id = ?
        """,
        (title, source_url, canonical_id, duration_seconds, status, library_folder_id, utc_now_iso(), item_id),
    )


def ensure_default_provider_folder(connection: sqlite3.Connection, provider: str) -> str | None:
    folder_name = DEFAULT_PROVIDER_FOLDERS.get(provider)
    if not folder_name:
        return None
    sort_order = {"douyin": 10, "bilibili": 20, "wechat": 30, "campus": 40, "wechat_miniprogram": 50, "rss": 60}.get(provider, 90)
    return ensure_managed_folder(
        connection,
        source_type="provider_root",
        source_key=provider,
        name=folder_name,
        sort_order=sort_order,
    )


def ensure_rss_source_folder(connection: sqlite3.Connection, source_id: str, source_name: str) -> str:
    """Return an exclusive, direct child folder for one RSS subscription."""
    bound_folder_id = _bound_folder_id(connection, "rss_source", source_id)
    root_folder_id = ensure_default_provider_folder(connection, "rss")
    if not root_folder_id:
        raise RuntimeError("无法创建 RSS 订阅文件夹")
    if _is_direct_child_folder(connection, bound_folder_id, root_folder_id):
        return bound_folder_id
    return _create_rss_source_folder(connection, root_folder_id, source_id, source_name)


def repair_rss_source_folders() -> int:
    """Guarantee that every RSS source owns one direct child of ``RSS订阅``.

    Earlier RSS records could share a same-named folder.  Retain the first
    source's folder and move every later source into a distinct sibling,
    including its already imported articles.
    """
    initialize_database()
    repaired = 0
    with connect() as connection:
        root_folder_id = ensure_default_provider_folder(connection, "rss")
        if not root_folder_id:
            return repaired
        rows = connection.execute(
            "SELECT id, title, library_folder_id FROM rss_sources ORDER BY created_at, id"
        ).fetchall()
        assigned_folder_ids: set[str] = set()
        for row in rows:
            source_id = str(row["id"])
            candidates = (_bound_folder_id(connection, "rss_source", source_id), row["library_folder_id"])
            folder_id = next(
                (
                    str(candidate)
                    for candidate in candidates
                    if candidate
                    and str(candidate) not in assigned_folder_ids
                    and _is_direct_child_folder(connection, str(candidate), root_folder_id)
                ),
                None,
            )
            if not folder_id:
                folder_id = _create_rss_source_folder(connection, root_folder_id, source_id, str(row["title"] or ""))
                repaired += 1
            else:
                _bind_folder(connection, "rss_source", source_id, folder_id)
            assigned_folder_ids.add(folder_id)
            if row["library_folder_id"] != folder_id:
                connection.execute(
                    "UPDATE rss_sources SET library_folder_id=?, updated_at=? WHERE id=?",
                    (folder_id, utc_now_iso(), source_id),
                )
                repaired += 1
            connection.execute(
                """UPDATE content_items SET library_folder_id=?, updated_at=?
                   WHERE id IN (SELECT content_item_id FROM rss_source_items WHERE source_id=?)
                     AND (library_folder_id IS NULL OR library_folder_id <> ?)""",
                (folder_id, utc_now_iso(), source_id, folder_id),
            )
        connection.commit()
    return repaired


def _create_rss_source_folder(
    connection: sqlite3.Connection,
    root_folder_id: str,
    source_id: str,
    source_name: str,
) -> str:
    name = _next_rss_source_folder_name(connection, root_folder_id, source_name)
    folder_id = new_id()
    now = utc_now_iso()
    connection.execute(
        """INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (folder_id, name, root_folder_id, 0, now, now),
    )
    return _bind_folder(connection, "rss_source", source_id, folder_id)


def _next_rss_source_folder_name(connection: sqlite3.Connection, root_folder_id: str, source_name: str) -> str:
    """Give same-titled feeds distinct folder names without merging sources."""
    base_name = (source_name or "未命名 RSS 订阅").strip() or "未命名 RSS 订阅"
    existing_names = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM library_folders WHERE parent_folder_id=? AND deleted_at IS NULL",
            (root_folder_id,),
        ).fetchall()
    }
    candidate = base_name[:160]
    if candidate not in existing_names:
        return candidate
    suffix_number = 2
    while True:
        suffix = f" ({suffix_number})"
        candidate = f"{base_name[:160 - len(suffix)]}{suffix}"
        if candidate not in existing_names:
            return candidate
        suffix_number += 1


def _is_direct_child_folder(connection: sqlite3.Connection, folder_id: str | None, parent_folder_id: str) -> bool:
    if not folder_id:
        return False
    row = connection.execute(
        "SELECT 1 FROM library_folders WHERE id=? AND parent_folder_id=? AND deleted_at IS NULL",
        (folder_id, parent_folder_id),
    ).fetchone()
    return row is not None


def ensure_wechat_subscription_folder(
    connection: sqlite3.Connection,
    publisher_name: str,
    *,
    subscription_id: str | None = None,
) -> str:
    """Return the publisher folder directly under the WeChat library root."""
    if subscription_id:
        bound_folder_id = _bound_folder_id(connection, "wechat_subscription", subscription_id)
        if bound_folder_id:
            return bound_folder_id
        inferred_folder_id = _legacy_wechat_subscription_folder(connection, subscription_id)
        if inferred_folder_id:
            return _bind_folder(connection, "wechat_subscription", subscription_id, inferred_folder_id)
    root_folder_id = ensure_default_provider_folder(connection, "wechat")
    if not root_folder_id:
        raise ValueError("未能创建微信公众号根文件夹")
    name = publisher_name.strip() or "未命名公众号"
    row = connection.execute(
        """
        SELECT id FROM library_folders
        WHERE parent_folder_id = ? AND name = ? AND deleted_at IS NULL
        LIMIT 1
        """,
        (root_folder_id, name),
    ).fetchone()
    if row:
        folder_id = str(row["id"])
        return _bind_folder(connection, "wechat_subscription", subscription_id, folder_id) if subscription_id else folder_id
    now = utc_now_iso()
    folder_id = new_id()
    connection.execute(
        """
        INSERT INTO library_folders (
            id, name, parent_folder_id, sort_order, created_at, updated_at
        )
        VALUES (?, ?, ?, 0, ?, ?)
        """,
        (folder_id, name, root_folder_id, now, now),
    )
    return _bind_folder(connection, "wechat_subscription", subscription_id, folder_id) if subscription_id else folder_id


def ensure_creator_folder(
    connection: sqlite3.Connection,
    provider: str,
    creator_key: str,
    creator_name: str,
) -> str:
    """Return one stable creator folder below its platform root.

    The binding is keyed by the platform's opaque creator ID, so a creator
    rename never creates a second folder or moves later videos unexpectedly.
    """
    binding_key = f"{provider}:{creator_key}"
    bound_folder_id = _bound_folder_id(connection, "creator_source", binding_key)
    if bound_folder_id:
        return bound_folder_id
    root_folder_id = ensure_default_provider_folder(connection, provider)
    if not root_folder_id:
        raise ValueError(f"未能创建 {provider} 创作者根文件夹")
    name = creator_name.strip() or "未命名创作者"
    row = connection.execute(
        """
        SELECT id FROM library_folders
        WHERE parent_folder_id = ? AND name = ? AND deleted_at IS NULL
        LIMIT 1
        """,
        (root_folder_id, name),
    ).fetchone()
    if row:
        return _bind_folder(connection, "creator_source", binding_key, str(row["id"]))
    now = utc_now_iso()
    folder_id = new_id()
    connection.execute(
        """
        INSERT INTO library_folders (
            id, name, parent_folder_id, sort_order, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (folder_id, name, root_folder_id, 0, now, now),
    )
    return _bind_folder(connection, "creator_source", binding_key, folder_id)


def ensure_campus_source_folder(connection: sqlite3.Connection, source_name: str) -> str:
    """Return a source folder directly under the campus website root."""
    root_folder_id = ensure_default_provider_folder(connection, "campus")
    if not root_folder_id:
        raise ValueError("未能创建校园官网根文件夹")
    name = source_name.strip() or "未命名校园来源"
    return ensure_managed_folder(
        connection,
        source_type="campus_source",
        source_key=name,
        name=name,
        parent_folder_id=root_folder_id,
    )


def ensure_campus_section_folder(
    connection: sqlite3.Connection,
    source_name: str,
    section_name: str,
    *,
    source_key: str | None = None,
    preferred_folder_id: str | None = None,
) -> str:
    """Return a section folder under a campus source folder.

    Campus content is deliberately kept in the same library tree as every
    other source: ``校园官网 → 学院/来源 → 栏目 → 文章``.  The caller decides
    the source label so 公文通 can use its publishing department as the second
    level without special UI handling.
    """
    if source_key:
        bound_folder_id = _bound_folder_id(connection, "campus_source_section", source_key)
        if bound_folder_id:
            return bound_folder_id
        if preferred_folder_id and _active_folder_id(connection, preferred_folder_id):
            return _bind_folder(connection, "campus_source_section", source_key, preferred_folder_id)
    source_folder_id = ensure_campus_source_folder(connection, source_name)
    name = section_name.strip() or "未分类"
    row = connection.execute(
        """
        SELECT id FROM library_folders
        WHERE parent_folder_id = ? AND name = ? AND deleted_at IS NULL
        LIMIT 1
        """,
        (source_folder_id, name),
    ).fetchone()
    if row:
        folder_id = str(row["id"])
        return _bind_folder(connection, "campus_source_section", source_key, folder_id) if source_key else folder_id
    now = utc_now_iso()
    folder_id = new_id()
    connection.execute(
        """
        INSERT INTO library_folders (
            id, name, parent_folder_id, sort_order, created_at, updated_at
        )
        VALUES (?, ?, ?, 0, ?, ?)
        """,
        (folder_id, name, source_folder_id, now, now),
    )
    return _bind_folder(connection, "campus_source_section", source_key, folder_id) if source_key else folder_id


def campus_section_binding_key(source_name: str, section_name: str) -> str:
    return f"{source_name.strip() or '未命名校园来源'}\x1f{section_name.strip() or '未分类'}"


def _active_folder_id(connection: sqlite3.Connection, folder_id: str | None) -> str | None:
    if not folder_id:
        return None
    row = connection.execute(
        "SELECT id FROM library_folders WHERE id = ? AND deleted_at IS NULL",
        (folder_id,),
    ).fetchone()
    return str(row["id"]) if row else None


def ensure_managed_folder(
    connection: sqlite3.Connection,
    *,
    source_type: str,
    source_key: str,
    name: str,
    parent_folder_id: str | None = None,
    sort_order: float = 0,
) -> str:
    """Return a durable system folder that survives renames and repairs deletes.

    Bindings use the folder ID, so a user rename is intentionally preserved.
    Deleted folders are excluded by ``_bound_folder_id``; the next managed
    write recreates an active folder using the original system rule.
    """
    bound_folder_id = _bound_folder_id(connection, source_type, source_key)
    if bound_folder_id:
        return bound_folder_id
    row = connection.execute(
        """SELECT id FROM library_folders
           WHERE parent_folder_id IS ? AND name=? AND deleted_at IS NULL LIMIT 1""",
        (parent_folder_id, name),
    ).fetchone()
    if row:
        return _bind_folder(connection, source_type, source_key, str(row["id"]))
    now, folder_id = utc_now_iso(), new_id()
    connection.execute(
        """INSERT INTO library_folders (id,name,parent_folder_id,sort_order,created_at,updated_at)
           VALUES (?,?,?,?,?,?)""",
        (folder_id, name, parent_folder_id, sort_order, now, now),
    )
    return _bind_folder(connection, source_type, source_key, folder_id)


def _bound_folder_id(connection: sqlite3.Connection, source_type: str, source_key: str | None) -> str | None:
    if not source_key:
        return None
    row = connection.execute(
        """
        SELECT binding.folder_id
        FROM library_source_folder_bindings AS binding
        JOIN library_folders AS folder ON folder.id = binding.folder_id
        WHERE binding.source_type = ? AND binding.source_key = ?
          AND binding.folder_id IS NOT NULL AND folder.deleted_at IS NULL
        """,
        (source_type, source_key),
    ).fetchone()
    return str(row["folder_id"]) if row else None


def _bind_folder(connection: sqlite3.Connection, source_type: str, source_key: str | None, folder_id: str) -> str:
    if not source_key:
        return folder_id
    now = utc_now_iso()
    connection.execute(
        """
        INSERT INTO library_source_folder_bindings (source_type, source_key, folder_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_type, source_key) DO UPDATE SET
            folder_id = excluded.folder_id,
            updated_at = excluded.updated_at
        """,
        (source_type, source_key, folder_id, now, now),
    )
    return folder_id


def _legacy_wechat_subscription_folder(connection: sqlite3.Connection, subscription_id: str) -> str | None:
    """Adopt an existing subscription folder before falling back to the default path."""
    row = connection.execute(
        """
        SELECT content.library_folder_id
        FROM wechat_subscription_items AS item
        JOIN content_items AS content ON content.id = item.content_item_id
        JOIN library_folders AS folder ON folder.id = content.library_folder_id
        WHERE item.subscription_id = ?
          AND content.library_folder_id IS NOT NULL
          AND content.deleted_at IS NULL
          AND folder.deleted_at IS NULL
        ORDER BY content.updated_at DESC, content.created_at DESC
        LIMIT 1
        """,
        (subscription_id,),
    ).fetchone()
    return str(row["library_folder_id"]) if row else None


def _campus_folder_names(source_name: str | None, source_section: str | None) -> tuple[str, str]:
    """Normalize stored campus metadata into a two-level library path."""
    source = str(source_name or "").strip() or "未命名校园来源"
    section = str(source_section or "").strip() or "未分类"
    # 公文通的 source_name 是文章发布部门，栏目本身才是公文通。
    if section == "公文通":
        return "公文通", source
    return source, section


def backfill_campus_source_folders() -> int:
    """Move existing campus articles into their source/section folders.

    Also includes campus-discovered WeChat links that are already stored under
    the campus root.  They retain their WeChat reader/provider behavior while
    remaining in the campus source tree that discovered them.
    """
    initialize_database()
    updated = 0
    with connect() as connection:
        campus_root_id = ensure_default_provider_folder(connection, "campus")
        if not campus_root_id:
            return updated
        # Show built-in public sources in the library tree before their first
        # scheduled sync, so users can immediately find and enable them.
        for source_name in _PRECREATED_CAMPUS_SOURCE_FOLDERS:
            ensure_campus_source_folder(connection, source_name)

        rows = connection.execute(
            """
            WITH RECURSIVE campus_folders(id) AS (
                SELECT ?
                UNION ALL
                SELECT folder.id
                FROM library_folders AS folder
                JOIN campus_folders AS parent ON folder.parent_folder_id = parent.id
            )
            SELECT id, source_name, source_section, library_folder_id
            FROM content_items
            WHERE deleted_at IS NULL
              AND (
                    source_provider = 'campus'
                    OR (
                        library_folder_id IN (SELECT id FROM campus_folders)
                        AND (source_name IS NOT NULL OR source_section IS NOT NULL)
                    )
              )
            """,
            (campus_root_id,),
        ).fetchall()
        for row in rows:
            source_name, section_name = _campus_folder_names(
                row["source_name"], row["source_section"],
            )
            folder_id = ensure_campus_section_folder(
                connection,
                source_name,
                section_name,
                source_key=campus_section_binding_key(source_name, section_name),
            )
            if row["library_folder_id"] == folder_id:
                continue
            connection.execute(
                """
                UPDATE content_items
                SET library_folder_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (folder_id, utc_now_iso(), row["id"]),
            )
            updated += 1
        connection.commit()
    return updated


def backfill_default_provider_folders() -> int:
    initialize_database()
    updated = 0
    with connect() as connection:
        folder_ids = {
            provider: ensure_default_provider_folder(connection, provider)
            for provider in DEFAULT_PROVIDER_FOLDERS
        }
        for provider, folder_id in folder_ids.items():
            if not folder_id:
                continue
            cursor = connection.execute(
                """
                UPDATE content_items
                SET library_folder_id = ?,
                    updated_at = ?
                WHERE source_provider = ?
                  AND library_folder_id IS NULL
                """,
                (folder_id, utc_now_iso(), provider),
            )
            updated += cursor.rowcount or 0
        connection.commit()
    return updated


def backfill_wechat_subscription_folders() -> int:
    """Move only default-root subscription articles into their publisher folder."""
    initialize_database()
    updated = 0
    with connect() as connection:
        root_folder_id = ensure_default_provider_folder(connection, "wechat")
        if not root_folder_id:
            return updated
        subscriptions = connection.execute(
            "SELECT id, mp_name FROM wechat_subscriptions"
        ).fetchall()
        for subscription in subscriptions:
            ensure_wechat_subscription_folder(
                connection,
                str(subscription["mp_name"] or ""),
                subscription_id=str(subscription["id"]),
            )
        rows = connection.execute(
            """
            SELECT item.content_item_id, item.subscription_id, subscription.mp_name
            FROM wechat_subscription_items item
            JOIN wechat_subscriptions subscription ON subscription.id = item.subscription_id
            JOIN content_items content ON content.id = item.content_item_id
            WHERE content.source_provider = 'wechat'
              AND content.library_folder_id = ?
            """,
            (root_folder_id,),
        ).fetchall()
        for row in rows:
            folder_id = ensure_wechat_subscription_folder(
                connection,
                str(row["mp_name"] or ""),
                subscription_id=str(row["subscription_id"]),
            )
            cursor = connection.execute(
                """
                UPDATE content_items
                SET library_folder_id = ?, updated_at = ?
                WHERE id = ? AND library_folder_id = ?
                """,
                (folder_id, utc_now_iso(), row["content_item_id"], root_folder_id),
            )
            updated += cursor.rowcount or 0
        connection.commit()
    return updated


def _ensure_obsidian_sync(
    connection: sqlite3.Connection,
    content_item_id: str,
    title: str,
    obsidian_path: str | None,
) -> None:
    if not obsidian_path:
        return
    note_path = Path(obsidian_path).expanduser()
    if not note_path.exists() or not note_path.is_file():
        return
    existing = connection.execute(
        "SELECT id FROM obsidian_sync WHERE content_item_id = ? LIMIT 1",
        (content_item_id,),
    ).fetchone()
    if existing:
        return

    markdown = note_path.read_text(encoding="utf-8", errors="replace")
    draft_path = settings.data_dir / "drafts" / f"{content_item_id}-{_safe_filename(title)}.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(markdown, encoding="utf-8")
    markdown_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    now = utc_now_iso()
    connection.execute(
        """
        INSERT INTO obsidian_sync (
            id, content_item_id, series_id, markdown_draft_path, obsidian_path,
            last_synced_hash, external_hash, sync_status, last_synced_at
        )
        VALUES (?, ?, NULL, ?, ?, ?, ?, 'synced', ?)
        """,
        (
            new_id(),
            content_item_id,
            str(draft_path),
            str(note_path),
            markdown_hash,
            markdown_hash,
            now,
        ),
    )


def _canonical_source_id(*, source_url: str | None, video_info: dict | None) -> str | None:
    info = video_info or {}
    canonical_id = None
    for key in ("id", "bvid", "aid", "aweme_id"):
        value = info.get(key)
        if value:
            canonical_id = str(value)
            break
    canonical_id = canonical_id or source_url
    bilibili_video_id = bilibili_video_id_from_page_url(source_url or "")
    if bilibili_video_id:
        canonical_id = bilibili_video_id
        page_number = requested_page_number(source_url or "")
        if canonical_id and page_number > 1 and not canonical_id.endswith(f":p{page_number}"):
            return f"{canonical_id}:p{page_number}"
    return canonical_id


def _duration_seconds(video_info: dict | None) -> float | None:
    value = (video_info or {}).get("duration")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_filename(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in " -_" else "_" for char in value).strip()
    return (cleaned[:80] or "untitled")
