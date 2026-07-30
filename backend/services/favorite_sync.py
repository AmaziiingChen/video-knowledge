"""Incremental sync for a user's own Douyin and Bilibili favorite folders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
from typing import Any

from services.creator_sync import (
    CreatorSyncError,
    CreatorVideo,
    _append_new_videos,
    _capture_browser_pages,
    _parse_creator_url,
    _parse_page,
    preview_creator_source,
)
from services.database import connect, initialize_database, utc_now_iso
from services.content_index import ensure_managed_folder
from services.pipeline_runner import PipelineRequest
from services.repository import ContentRepository, new_id
from services.task_manager import task_manager


DOUYIN_FAVORITES_URL = "https://www.douyin.com/user/self?showSubTab=favorite_folder&showTab=favorite_collection"
FAVORITE_SYNC_LIMIT = 5
DEFAULT_SYNC_INTERVAL_MINUTES = 360
ALLOWED_SYNC_INTERVAL_MINUTES = {30, 60, 180, 360, 720, 1440}


class FavoriteSyncError(ValueError):
    """A favorite-source error that can be displayed directly in the UI."""


@dataclass(frozen=True)
class FavoritePreview:
    provider: str
    source_url: str
    title: str
    videos: list[CreatorVideo]


_SYNC_LOCK = Lock()


def enable_douyin_favorites(*, auto_analyze: bool = True) -> dict[str, Any]:
    """Create (or refresh) the single private Douyin favorites source."""
    return _save_and_sync(
        _preview_douyin_favorites(),
        source_id=None,
        auto_analyze=auto_analyze,
    )


def add_bilibili_favorite(*, source_url: str, auto_analyze: bool = True) -> dict[str, Any]:
    provider, source_kind, _creator_key = _parse_creator_url(source_url.strip())
    if provider != "bilibili" or source_kind != "favorites":
        raise FavoriteSyncError("请输入 B 站收藏夹链接，例如 https://space.bilibili.com/用户ID/favlist?fid=收藏夹ID")
    try:
        preview = preview_creator_source(
            source_url=source_url,
            limit=FAVORITE_SYNC_LIMIT,
            allow_personal_sources=True,
        )
    except CreatorSyncError as exc:
        raise FavoriteSyncError(str(exc)) from exc
    title = preview.collection_name or f"B站收藏夹 {preview.collection_id}"
    return _save_and_sync(
        FavoritePreview("bilibili", preview.source_url, title, preview.videos),
        source_id=None,
        auto_analyze=auto_analyze,
    )


def sync_saved_favorite(source_id: str) -> dict[str, Any]:
    source = get_favorite_source(source_id)
    if not source["enabled"]:
        raise FavoriteSyncError("该个人收藏已暂停；恢复后再检查")
    try:
        preview = _preview_for_source(source)
        return _save_and_sync(preview, source_id=source_id, auto_analyze=bool(source["auto_analyze"]))
    except Exception as exc:
        _record_sync_error(source_id, str(exc))
        if isinstance(exc, FavoriteSyncError):
            raise
        raise FavoriteSyncError(f"个人收藏检查失败：{exc}") from exc


def sync_due_favorites() -> list[str]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT id FROM favorite_sources
               WHERE enabled=1 AND (next_sync_at IS NULL OR next_sync_at='' OR next_sync_at<=?)
               ORDER BY COALESCE(next_sync_at, created_at), created_at""",
            (utc_now_iso(),),
        ).fetchall()
    from services.task_manager import task_manager

    completed: list[str] = []
    for row in rows:
        try:
            source_id = str(row["id"])
            task_manager.create_source_sync(
                {"kind": "favorite_saved", "source_id": source_id},
                source_title="自动检查个人收藏",
                execution_mode="background",
            )
            completed.append(source_id)
        except Exception:
            continue
    return completed


def list_favorite_sources() -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute("SELECT * FROM favorite_sources ORDER BY provider, created_at").fetchall()
    return [_serialize_source(row) for row in rows]


def get_favorite_source(source_id: str) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT * FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise LookupError(source_id)
    return _serialize_source(row)


def update_favorite_source(
    source_id: str,
    *,
    enabled: bool | None = None,
    auto_analyze: bool | None = None,
    sync_interval_minutes: int | None = None,
) -> dict[str, Any]:
    if enabled is None and auto_analyze is None and sync_interval_minutes is None:
        raise FavoriteSyncError("至少提供一个需要更新的个人收藏设置")
    initialize_database()
    with connect() as connection:
        current = connection.execute("SELECT * FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
        if not current:
            raise LookupError(source_id)
        interval = _valid_interval(sync_interval_minutes if sync_interval_minutes is not None else current["sync_interval_minutes"])
        next_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        next_auto_analyze = bool(current["auto_analyze"]) if auto_analyze is None else bool(auto_analyze)
        next_sync_at = utc_now_iso() if enabled is True else current["next_sync_at"]
        connection.execute(
            """UPDATE favorite_sources
               SET enabled=?, auto_analyze=?, sync_interval_minutes=?, next_sync_at=?, updated_at=?
               WHERE id=?""",
            (int(next_enabled), int(next_auto_analyze), interval, next_sync_at, utc_now_iso(), source_id),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
    return _serialize_source(row)


def process_pending_favorite_items(source_id: str) -> dict[str, Any]:
    """Queue this favorite source's unprocessed items for full analysis.

    A source can have been added before automatic analysis was enabled. Keep
    recovery explicit and scoped to that source; never requeue an item that
    already has an active task.
    """
    with _SYNC_LOCK:
        initialize_database()
        recovered: list[tuple[str, CreatorVideo, str]] = []
        with connect() as connection:
            source = connection.execute("SELECT * FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
            if not source:
                raise LookupError(source_id)
            rows = connection.execute(
                """
                SELECT content_items.id, content_items.canonical_source_id, content_items.source_url,
                       content_items.title, content_items.status
                FROM content_items
                JOIN favorite_source_items
                  ON favorite_source_items.content_item_id = content_items.id
                WHERE favorite_source_items.source_id=?
                  AND content_items.status IN ('failed', 'inbox')
                  AND content_items.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM tasks
                      WHERE tasks.content_item_id = content_items.id
                        AND tasks.status IN ('queued', 'running', 'paused')
                  )
                ORDER BY COALESCE(content_items.published_at, content_items.created_at) DESC
                """,
                (source_id,),
            ).fetchall()
            repository = ContentRepository(connection)
            for row in rows:
                item_id = str(row["id"])
                repository.update_status(item_id, "processing")
                recovered.append((
                    item_id,
                    CreatorVideo(
                        provider=str(source["provider"]),
                        canonical_id=str(row["canonical_source_id"] or ""),
                        source_url=str(row["source_url"] or ""),
                        title=str(row["title"]),
                    ),
                    str(row["status"]),
                ))
            connection.commit()

        task_ids: list[str] = []
        try:
            for index, (item_id, video, _original_status) in enumerate(recovered):
                task = task_manager.create(
                    PipelineRequest(
                        content_item_id=item_id,
                        share_text=video.source_url,
                        source_url=video.source_url,
                        source_title=video.title,
                        use_cache=True,
                        processing_mode="full",
                        execution_mode="background",
                    )
                )
                task_ids.append(task.task_id)
        except Exception as exc:
            # Tasks created before this failure are already durable and may
            # already be running. Restore only records that never received a
            # task, so their content status remains consistent with the queue.
            _restore_favorite_item_statuses(recovered[index:])
            raise FavoriteSyncError(f"创建补处理任务失败：{exc}") from exc
    return {
        "queued_count": len(task_ids),
        "task_ids": task_ids,
        "content_item_ids": [item_id for item_id, _video, _status in recovered],
    }


def delete_favorite_source(source_id: str) -> None:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT id FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise LookupError(source_id)
        # Imported content belongs to the user and remains available.
        connection.execute("DELETE FROM favorite_sources WHERE id=?", (source_id,))
        connection.commit()


def list_favorite_sync_runs(source_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT status, message, discovered_count, created_count, created_at
               FROM favorite_sync_runs WHERE source_id=? ORDER BY created_at DESC LIMIT ?""",
            (source_id, max(1, min(int(limit), 30))),
        ).fetchall()
    return [dict(row) for row in rows]


def _preview_for_source(source: dict[str, Any]) -> FavoritePreview:
    if source["provider"] == "douyin":
        return _preview_douyin_favorites()
    try:
        preview = preview_creator_source(
            source_url=str(source["source_url"]),
            limit=FAVORITE_SYNC_LIMIT,
            allow_personal_sources=True,
        )
    except CreatorSyncError as exc:
        raise FavoriteSyncError(str(exc)) from exc
    return FavoritePreview(
        "bilibili",
        preview.source_url,
        preview.collection_name or str(source["title"]),
        preview.videos,
    )


def _preview_douyin_favorites() -> FavoritePreview:
    try:
        payloads, _title = _capture_browser_pages(
            source_url=DOUYIN_FAVORITES_URL,
            response_matcher=lambda url: "listcollection" in url,
            limit=FAVORITE_SYNC_LIMIT,
            provider="douyin",
            stop_at=None,
        )
    except CreatorSyncError as exc:
        raise FavoriteSyncError(str(exc)) from exc
    videos: list[CreatorVideo] = []
    for payload in payloads:
        page_videos, _name, _cursor, _has_more = _parse_page(payload, provider="douyin")
        _append_new_videos(videos, page_videos, limit=FAVORITE_SYNC_LIMIT, cutoff=None)
        if len(videos) >= FAVORITE_SYNC_LIMIT:
            break
    if not videos:
        raise FavoriteSyncError("未从抖音“我的收藏”取得作品；请检查 Cookie 是否仍有效，并确认页面中已有收藏视频")
    return FavoritePreview("douyin", DOUYIN_FAVORITES_URL, "我的抖音收藏", videos)


def _save_and_sync(preview: FavoritePreview, *, source_id: str | None, auto_analyze: bool) -> dict[str, Any]:
    with _SYNC_LOCK:
        initialize_database()
        videos = preview.videos[:FAVORITE_SYNC_LIMIT]
        created: list[tuple[str, CreatorVideo]] = []
        with connect() as connection:
            source_row = (
                connection.execute("SELECT * FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
                if source_id
                else connection.execute(
                    "SELECT * FROM favorite_sources WHERE provider=? AND source_url=?",
                    (preview.provider, preview.source_url),
                ).fetchone()
            )
            if source_id and not source_row:
                raise LookupError(source_id)
            source_id = str(source_row["id"]) if source_row else new_id()
            folder_id = _ensure_source_folder(
                connection,
                source_id,
                preview.title,
                preferred_folder_id=str(source_row["library_folder_id"] or "") if source_row else None,
            )
            now = utc_now_iso()
            if source_row:
                connection.execute(
                    """UPDATE favorite_sources SET source_url=?, title=?, library_folder_id=?, updated_at=? WHERE id=?""",
                    (preview.source_url, preview.title, folder_id, now, source_id),
                )
                source_auto_analyze = bool(source_row["auto_analyze"])
                interval = _valid_interval(source_row["sync_interval_minutes"])
            else:
                source_auto_analyze = bool(auto_analyze)
                interval = DEFAULT_SYNC_INTERVAL_MINUTES
                connection.execute(
                    """INSERT INTO favorite_sources (
                        id, provider, source_url, title, library_folder_id, enabled, auto_analyze,
                        sync_interval_minutes, sync_limit, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
                    (source_id, preview.provider, preview.source_url, preview.title, folder_id, int(source_auto_analyze), interval, FAVORITE_SYNC_LIMIT, now, now),
                )
            repository = ContentRepository(connection)
            for position, video in enumerate(videos):
                mapped = connection.execute(
                    "SELECT content_item_id FROM favorite_source_items WHERE source_id=? AND remote_video_id=?",
                    (source_id, video.canonical_id),
                ).fetchone()
                if mapped:
                    continue
                item = repository.find_by_canonical_id(source_provider=video.provider, canonical_source_id=video.canonical_id)
                if item is None:
                    item = repository.create_content_item(
                        source_provider=video.provider,
                        source_url=video.source_url,
                        canonical_source_id=video.canonical_id,
                        title=video.title,
                        cover_url=video.cover_url or None,
                        duration_seconds=video.duration_seconds,
                        published_at=video.published_at,
                        source_name="个人收藏",
                        source_section=preview.title,
                        library_folder_id=folder_id,
                        sort_order=float(position),
                        status="processing" if source_auto_analyze else "inbox",
                    )
                    created.append((item.id, video))
                connection.execute(
                    """INSERT OR IGNORE INTO favorite_source_items (source_id, content_item_id, remote_video_id, created_at)
                       VALUES (?, ?, ?, ?)""",
                    (source_id, item.id, video.canonical_id, now),
                )
            _record_sync_success(connection, source_id, interval, len(videos), len(created))
            connection.commit()
            source = connection.execute("SELECT * FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
        task_ids: list[str] = []
        if source_auto_analyze:
            for item_id, video in created:
                task = task_manager.create(
                    PipelineRequest(
                        content_item_id=item_id,
                        share_text=video.source_url,
                        source_url=video.source_url,
                        source_title=video.title,
                        processing_mode="full",
                        execution_mode="background",
                    )
                )
                task_ids.append(task.task_id)
        return {
            "source": _serialize_source(source),
            "discovered_count": len(videos),
            "created_count": len(created),
            "duplicate_count": len(videos) - len(created),
            "task_ids": task_ids,
            "content_item_ids": [item_id for item_id, _video in created],
        }


def _ensure_source_folder(
    connection,
    source_id: str,
    title: str,
    *,
    preferred_folder_id: str | None = None,
) -> str:
    bound = connection.execute(
        """SELECT binding.folder_id
           FROM library_source_folder_bindings binding
           JOIN library_folders folder ON folder.id=binding.folder_id AND folder.deleted_at IS NULL
           WHERE binding.source_type='favorite_source' AND binding.source_key=?""",
        (source_id,),
    ).fetchone()
    if bound:
        return str(bound["folder_id"])

    if preferred_folder_id:
        active = connection.execute(
            "SELECT id FROM library_folders WHERE id=? AND deleted_at IS NULL",
            (preferred_folder_id,),
        ).fetchone()
        if active:
            now = utc_now_iso()
            connection.execute(
                """INSERT INTO library_source_folder_bindings (source_type, source_key, folder_id, created_at, updated_at)
                   VALUES ('favorite_source', ?, ?, ?, ?)
                   ON CONFLICT(source_type, source_key) DO UPDATE SET folder_id=excluded.folder_id, updated_at=excluded.updated_at""",
                (source_id, preferred_folder_id, now, now),
            )
            return preferred_folder_id

    root_id = ensure_managed_folder(
        connection,
        source_type="favorite_source_root",
        source_key="default",
        name="个人收藏",
        sort_order=6,
    )
    base_name = title[:120] or "未命名收藏夹"
    name, suffix = base_name, 2
    while connection.execute(
        "SELECT 1 FROM library_folders WHERE parent_folder_id=? AND name=? AND deleted_at IS NULL LIMIT 1",
        (root_id, name),
    ).fetchone():
        name = f"{base_name} ({suffix})"
        suffix += 1
    folder_id, now = new_id(), utc_now_iso()
    connection.execute(
        "INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (folder_id, name, root_id, now, now),
    )
    connection.execute(
        """INSERT INTO library_source_folder_bindings (source_type, source_key, folder_id, created_at, updated_at)
           VALUES ('favorite_source', ?, ?, ?, ?)
           ON CONFLICT(source_type, source_key) DO UPDATE SET folder_id=excluded.folder_id, updated_at=excluded.updated_at""",
        (source_id, folder_id, now, now),
    )
    return folder_id


def _record_sync_success(connection, source_id: str, interval: int, discovered: int, created: int) -> None:
    now = utc_now_iso()
    next_sync = (datetime_from_iso(now) + timedelta(minutes=interval)).isoformat()
    connection.execute(
        """UPDATE favorite_sources SET last_sync_at=?, next_sync_at=?, last_error=NULL,
           consecutive_failure_count=0, last_discovered_count=?, last_created_count=?, updated_at=? WHERE id=?""",
        (now, next_sync, discovered, created, now, source_id),
    )
    connection.execute(
        """INSERT INTO favorite_sync_runs (id, source_id, status, message, discovered_count, created_count, created_at)
           VALUES (?, ?, 'success', '', ?, ?, ?)""",
        (new_id(), source_id, discovered, created, now),
    )


def _record_sync_error(source_id: str, message: str) -> None:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT sync_interval_minutes, consecutive_failure_count FROM favorite_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return
        failures = int(row["consecutive_failure_count"] or 0) + 1
        minutes = min(1440, _valid_interval(row["sync_interval_minutes"]) * (2 ** min(failures, 3)))
        now = utc_now_iso()
        next_sync = (datetime_from_iso(now) + timedelta(minutes=minutes)).isoformat()
        text = str(message)[:1000]
        connection.execute(
            """UPDATE favorite_sources SET last_error=?, consecutive_failure_count=?, next_sync_at=?, updated_at=? WHERE id=?""",
            (text, failures, next_sync, now, source_id),
        )
        connection.execute(
            """INSERT INTO favorite_sync_runs (id, source_id, status, message, discovered_count, created_count, created_at)
               VALUES (?, ?, 'failed', ?, 0, 0, ?)""",
            (new_id(), source_id, text, now),
        )
        connection.commit()


def _restore_favorite_item_statuses(items: list[tuple[str, CreatorVideo, str]]) -> None:
    if not items:
        return
    with connect() as connection:
        repository = ContentRepository(connection)
        for item_id, _video, status in items:
            repository.update_status(item_id, status)
        connection.commit()


def _valid_interval(value: object) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise FavoriteSyncError("同步频率无效") from exc
    if interval not in ALLOWED_SYNC_INTERVAL_MINUTES:
        raise FavoriteSyncError("同步频率必须为 30 分钟至每天之间的预设值")
    return interval


def _serialize_source(row) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "provider": str(row["provider"]), "source_url": str(row["source_url"]),
        "title": str(row["title"]), "library_folder_id": str(row["library_folder_id"] or ""),
        "enabled": bool(row["enabled"]), "auto_analyze": bool(row["auto_analyze"]),
        "sync_interval_minutes": int(row["sync_interval_minutes"]), "sync_limit": FAVORITE_SYNC_LIMIT,
        "last_sync_at": row["last_sync_at"], "next_sync_at": row["next_sync_at"], "last_error": row["last_error"],
        "last_discovered_count": int(row["last_discovered_count"] or 0), "last_created_count": int(row["last_created_count"] or 0),
    }


def datetime_from_iso(value: str):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
