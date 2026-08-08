from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

from config import settings
from services.content_index import ensure_creator_folder
from services.creator_metadata import save_creator_work_metadata
from services.database import connect, initialize_database, utc_now_iso
from services.network_policy import direct_browser_launch_options
from services.pipeline_runner import PipelineRequest
from services.repository import ContentRepository, new_id
from services.task_manager import task_manager


MAX_CREATOR_SCAN_ITEMS = 500
PAGE_SIZE = 20
CREATOR_PAGE_RESPONSE_WAIT_MS = 5_000
MAX_CREATOR_LOAD_ATTEMPTS = 3
MAX_CREATOR_CAPTURE_RESPONSE_PAGES = 60
ALLOWED_SYNC_INTERVAL_MINUTES = {30, 60, 180, 360, 720, 1440}
CREATOR_PROCESSING_MODES = {"metadata", "transcript", "full"}
DEFAULT_CREATOR_QUEUE_LIMIT = 1
# Only the first subscription has a user-visible discovery breadth. Scheduled
# checks scan back from the newest item until they reach an item already linked
# to this source; this is deliberately not a user-configurable cap.
DEFAULT_CREATOR_SYNC_SCAN_ITEMS = 1
_BILIBILI_SPACE_PATH_RE = re.compile(r"^/(?P<id>\d+)(?:/upload/video)?/?$")
_BILIBILI_LIST_PATH_RE = re.compile(r"^/(?P<mid>\d+)/lists/(?P<id>\d+)/?$")
_BILIBILI_CHANNEL_PATH_RE = re.compile(r"^/(?P<mid>\d+)/channel/(?P<kind>seriesdetail|collectiondetail)/?$")
_BILIBILI_FAVORITES_PATH_RE = re.compile(r"^/(?P<mid>\d+)/favlist/?$")
_BILIBILI_LIKES_PATH_RE = re.compile(r"^/(?P<mid>\d+)/like/?$")
_PERSONAL_SOURCE_KINDS = {"favorites", "likes"}
_DOUYIN_USER_PATH_RE = re.compile(r"^/user/(?P<id>[^/?#]+)/?$")
_DOUYIN_COLLECTION_PATH_RE = re.compile(r"^/collection/(?P<id>\d+)(?:/(?P<position>\d+))?/?$")
_XIAOHONGSHU_PROFILE_PATH_RE = re.compile(r"^/user/profile/(?P<id>[^/?#]+)/?$")
_CREATOR_BROWSER_LOCK = Lock()
_CREATOR_SYNC_LOCK = Lock()
_CREATOR_CAPTURE_STATE_LOCK = Lock()
_CREATOR_CAPTURE_STATE = {
    "active": False,
    "provider": "",
    "stage": "空闲",
    "waiting_count": 0,
    "last_list_checks": {"douyin": {}, "bilibili": {}, "xiaohongshu": {}},
}


class CreatorSyncError(ValueError):
    """An input or upstream-response error safe to show in the UI."""


@dataclass(frozen=True)
class CreatorVideo:
    provider: str
    canonical_id: str
    source_url: str
    title: str
    cover_url: str = ""
    duration_seconds: float | None = None
    published_at: str | None = None
    description: str = ""
    author_name: str = ""
    tags: tuple[str, ...] = ()
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CreatorPreview:
    provider: str
    source_kind: str
    source_url: str
    creator_key: str
    creator_name: str
    videos: list[CreatorVideo]
    creator_avatar_url: str = ""
    creator_description: str = ""
    collection_id: str = ""
    collection_name: str = ""


@dataclass(frozen=True)
class CreatorSyncResult:
    source_id: str
    provider: str
    creator_name: str
    folder_id: str
    discovered_count: int
    created_count: int
    duplicate_count: int
    queued_count: int
    inbox_count: int
    task_ids: list[str]
    content_item_ids: list[str]


def preview_creator_source(
    *,
    source_url: str,
    limit: int = 20,
    published_after: str | None = None,
    published_before: str | None = None,
    allow_personal_sources: bool = False,
    known_item_ids: set[str] | None = None,
) -> CreatorPreview:
    """Read a public creator page through the application's bundled browser."""
    provider, source_kind, creator_key = _parse_creator_url(source_url.strip())
    normalized_url = _canonical_creator_url(provider, source_kind, creator_key)
    capture_url = _creator_capture_url(source_url, provider=provider, source_kind=source_kind, creator_key=creator_key)
    max_items = max(1, min(int(limit), MAX_CREATOR_SCAN_ITEMS))
    # The browser reader stops as soon as it sees one of these IDs.  Use a
    # technical scan ceiling only to protect the desktop from a broken remote
    # pagination loop; reaching it without the anchor is reported as a
    # failure, never treated as a complete check.
    incremental_limit = MAX_CREATOR_CAPTURE_RESPONSE_PAGES * PAGE_SIZE * 3
    scan_limit = incremental_limit if known_item_ids else max_items
    cutoff = _parse_cutoff(published_after)
    before = _parse_cutoff(published_before)
    if before and cutoff and before < cutoff:
        raise CreatorSyncError("结束日期不能早于起始日期")
    if source_kind in _PERSONAL_SOURCE_KINDS and not allow_personal_sources:
        raise CreatorSyncError("访问个人喜欢、收藏前需要明确授权")
    # Prefer the browser already bundled with the desktop application. It lets
    # Douyin generate its current request signatures itself and keeps a user's
    # login state local, rather than copying a fragile signing implementation
    # or asking users to operate a second Docker service.
    if provider == "douyin" and source_kind in {"profile", "profile_compilations"}:
        options = {
            "source_url": normalized_url,
            "creator_key": creator_key,
            "limit": scan_limit,
            "cutoff": cutoff,
            "known_item_ids": known_item_ids,
        }
        if source_kind == "profile_compilations":
            options["compilation_view"] = True
        preview = _preview_douyin_profile_in_browser(**options)
    elif provider == "douyin" and source_kind == "collection":
        collection_options = {
            "source_url": normalized_url,
            "capture_url": capture_url,
            "creator_key": creator_key,
            "limit": scan_limit,
            "cutoff": cutoff,
        }
        if known_item_ids:
            collection_options["known_item_ids"] = known_item_ids
        preview = _preview_douyin_collection_in_browser(
            **collection_options,
        )
    elif provider == "douyin" and source_kind in _PERSONAL_SOURCE_KINDS:
        personal_options = {
            "source_url": normalized_url,
            "creator_key": creator_key,
            "source_kind": source_kind,
            "limit": scan_limit,
            "cutoff": cutoff,
        }
        if known_item_ids:
            personal_options["known_item_ids"] = known_item_ids
        preview = _preview_douyin_personal_source_in_browser(
            **personal_options,
        )
    elif provider == "xiaohongshu" and source_kind == "favorites":
        preview = _preview_xiaohongshu_favorites(
            source_url=normalized_url,
            creator_key=creator_key,
            limit=max_items,
        )
    elif provider == "bilibili":
        bilibili_options = {
            "source_url": normalized_url,
            "creator_key": creator_key,
            "source_kind": source_kind,
            "limit": scan_limit,
            "cutoff": cutoff,
        }
        if known_item_ids:
            bilibili_options["known_item_ids"] = known_item_ids
        preview = _preview_bilibili_source_in_browser(
            **bilibili_options,
        )
    else:
        raise CreatorSyncError("仅支持抖音/B站的主页、合集、收藏夹或喜欢列表，以及小红书“我的收藏”链接")
    return _preview_within_date_range(preview, after=cutoff, before=before)


def sync_creator_source(
    *,
    source_url: str,
    limit: int = DEFAULT_CREATOR_SYNC_SCAN_ITEMS,
    published_after: str | None = None,
    published_before: str | None = None,
    source_id: str | None = None,
    auto_process: bool | None = None,
    sync_interval_minutes: int | None = None,
    processing_mode: str | None = None,
    queue_limit: int | None = None,
    selected_video_ids: list[str] | None = None,
    allow_personal_sources: bool = False,
    known_item_ids: set[str] | None = None,
    retry_existing_items: bool = False,
    execution_mode: Literal["foreground", "background"] = "foreground",
) -> CreatorSyncResult:
    with _CREATOR_SYNC_LOCK:
        preview = preview_creator_source(
            source_url=source_url,
            limit=limit,
            published_after=published_after,
            published_before=published_before,
            allow_personal_sources=allow_personal_sources,
            known_item_ids=known_item_ids,
        )
        initialize_database()
        # Enforce the requested window here as well as in the page reader. It
        # keeps the initial-subscription policy intact for alternate readers
        # and future provider fallbacks that return a larger page.
        if known_item_ids:
            # A known work is a *boundary*, not merely a duplicate to omit.
            # List APIs return an entire page at a time, so keeping the rows
            # after the anchor would silently re-import historical works from
            # that final page.  This applies equally to Bilibili favourites,
            # Douyin likes and ordinary creator feeds.
            videos = _unseen_prefix_before_known_item(preview.videos, known_item_ids)
        else:
            videos = _selected_preview_videos(
                preview.videos[:max(1, min(int(limit), MAX_CREATOR_SCAN_ITEMS))],
                selected_video_ids,
            )
        created_items: list[tuple[str, CreatorVideo, bool]] = []
        recovered_items: list[tuple[str, CreatorVideo, str]] = []
        selected_content_item_ids: list[str] = []
        duplicate_count = 0
        with connect() as connection:
            folder_id = ensure_creator_folder(
                connection,
                preview.provider,
                preview.creator_key,
                preview.creator_name,
            )
            if not folder_id:
                raise CreatorSyncError(f"未能创建 {preview.provider} 内容文件夹")
            now = utc_now_iso()
            identity = _source_identity(preview.provider, preview.source_kind, preview.creator_key)
            source_row = _source_row(connection, source_id=source_id, source_identity=identity)
            if source_id and not source_row:
                raise CreatorSyncError("创作者订阅不存在")
            source_id = str(source_row["id"]) if source_row else new_id()
            effective_mode = _effective_processing_mode(source_row, processing_mode, auto_process)
            effective_auto_process = effective_mode != "metadata"
            interval = _valid_interval(
                sync_interval_minutes if sync_interval_minutes is not None else (
                    source_row["sync_interval_minutes"] if source_row else settings.creator_default_interval_minutes
                )
            )
            # The first import breadth is a source preference. Backfills and
            # scheduled checks must not silently overwrite it.
            sync_limit = (
                int(source_row["sync_limit"])
                if source_row and source_row["sync_limit"] is not None
                else max(1, min(int(limit), MAX_CREATOR_SCAN_ITEMS))
            )
            # Keep each source's background work bounded. Discoveries above
            # the limit remain visible in the inbox for deliberate follow-up.
            effective_queue_limit = _valid_queue_limit(
                queue_limit if queue_limit is not None else (source_row["queue_limit"] if source_row else DEFAULT_CREATOR_QUEUE_LIMIT)
            )
            if source_row:
                connection.execute(
                    """
                    UPDATE creator_sources
                    SET source_url=?, source_kind=?, creator_key=?, creator_name=?,
                        source_identity=?, library_folder_id=?, auto_process=?, processing_mode=?,
                        sync_interval_minutes=?, sync_limit=?, queue_limit=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        preview.source_url,
                        preview.source_kind,
                        preview.creator_key,
                        preview.creator_name,
                        identity,
                        folder_id,
                        int(effective_auto_process),
                        effective_mode,
                        interval,
                        sync_limit,
                        effective_queue_limit,
                        now,
                        source_id,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO creator_sources (
                        id, provider, source_url, source_kind, creator_key, creator_name,
                        source_identity, library_folder_id, enabled, auto_process, processing_mode,
                        sync_interval_minutes, sync_limit, queue_limit, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        preview.provider,
                        preview.source_url,
                        preview.source_kind,
                        preview.creator_key,
                        preview.creator_name,
                        identity,
                        folder_id,
                        int(effective_auto_process),
                        effective_mode,
                        interval,
                        sync_limit,
                        effective_queue_limit,
                        now,
                        now,
                    ),
                )
            repository = ContentRepository(connection)
            for position, video in enumerate(videos):
                existing = repository.find_by_canonical_id(
                    source_provider=video.provider,
                    canonical_source_id=video.canonical_id,
                )
                if existing:
                    duplicate_count += 1
                    selected_content_item_ids.append(existing.id)
                    save_creator_work_metadata(
                        connection,
                        content_item_id=existing.id,
                        provider=preview.provider,
                        creator_key=preview.creator_key,
                        creator_name=preview.creator_name,
                        creator_avatar_url=preview.creator_avatar_url,
                        creator_description=preview.creator_description,
                        collection_id=preview.collection_id,
                        collection_name=preview.collection_name,
                        work_description=video.description,
                        author_name=video.author_name,
                        tags=list(video.tags),
                        stats=video.stats,
                    )
                    _link_creator_source_item(connection, source_id, existing.id, video.canonical_id, now)
                    continue
                item = repository.create_content_item(
                    source_provider=video.provider,
                    source_url=video.source_url,
                    canonical_source_id=video.canonical_id,
                    title=video.title,
                    cover_url=video.cover_url or None,
                    duration_seconds=video.duration_seconds,
                    published_at=video.published_at,
                    source_name=preview.creator_name,
                    source_section=_source_section_label(preview.source_kind, preview.collection_name),
                    library_folder_id=folder_id,
                    sort_order=float(position),
                    status="processing" if effective_auto_process else "inbox",
                )
                save_creator_work_metadata(
                    connection,
                    content_item_id=item.id,
                    provider=preview.provider,
                    creator_key=preview.creator_key,
                    creator_name=preview.creator_name,
                    creator_avatar_url=preview.creator_avatar_url,
                    creator_description=preview.creator_description,
                    collection_id=preview.collection_id,
                    collection_name=preview.collection_name,
                    work_description=video.description,
                    author_name=video.author_name,
                    tags=list(video.tags),
                    stats=video.stats or {},
                )
                _link_creator_source_item(connection, source_id, item.id, video.canonical_id, now)
                should_queue = effective_auto_process
                created_items.append((item.id, video, should_queue))
                selected_content_item_ids.append(item.id)
            if retry_existing_items and effective_auto_process:
                for row in _recoverable_creator_items(
                    connection,
                    source_id=source_id,
                    limit=MAX_CREATOR_SCAN_ITEMS,
                ):
                    item_id = str(row["id"])
                    original_status = str(row["status"])
                    repository.update_status(item_id, "processing")
                    recovered_items.append((
                        item_id,
                        CreatorVideo(
                            provider=preview.provider,
                            canonical_id=str(row["canonical_source_id"]),
                            source_url=str(row["source_url"]),
                            title=str(row["title"]),
                        ),
                        original_status,
                    ))
                    if item_id not in selected_content_item_ids:
                        selected_content_item_ids.append(item_id)
            connection.commit()

        task_ids: list[str] = []
        queued_items = [
            (item_id, video, "new") for item_id, video, should_queue in created_items if should_queue
        ] + [
            (item_id, video, "recovered") for item_id, video, _original_status in recovered_items
        ]
        queued_items = queued_items[:effective_queue_limit]
        queued_new_item_ids = {item_id for item_id, _video, kind in queued_items if kind == "new"}
        deferred_new_item_ids = [
            item_id for item_id, _video, should_queue in created_items
            if should_queue and item_id not in queued_new_item_ids
        ]
        if deferred_new_item_ids:
            with connect() as connection:
                connection.executemany(
                    "UPDATE content_items SET status='inbox', updated_at=? WHERE id=?",
                    [(utc_now_iso(), item_id) for item_id in deferred_new_item_ids],
                )
                connection.commit()
        if queued_items:
            for index, (item_id, video, _kind) in enumerate(queued_items):
                try:
                    task = task_manager.create(
                        PipelineRequest(
                            content_item_id=item_id,
                            share_text=video.source_url,
                            source_url=video.source_url,
                            source_title=video.title,
                            use_cache=True,
                            processing_mode=effective_mode,
                            execution_mode=execution_mode,
                        )
                    )
                except Exception as exc:
                    # These items were created only for this sync attempt and
                    # never received a processing task. Keep them out of the
                    # canonical-id deduplication set so a later scheduled
                    # sync can create and queue them again.
                    _delete_unqueued_items(
                        item_id for item_id, _video, kind in queued_items[index:] if kind == "new"
                    )
                    _restore_recovered_item_statuses(
                        (item_id, original_status)
                        for item_id, _video, original_status in recovered_items
                        if item_id in {pending_id for pending_id, _pending_video, kind in queued_items[index:] if kind == "recovered"}
                    )
                    raise CreatorSyncError(f"创建处理任务失败：{exc}") from exc
                task_ids.append(task.task_id)
        _record_sync_success(
            source_id,
            interval_minutes=interval,
            discovered_count=len(videos),
            created_count=len(created_items),
            last_seen_published_at=_latest_published_at(videos),
        )
        return CreatorSyncResult(
            source_id=source_id,
            provider=preview.provider,
            creator_name=preview.creator_name,
            folder_id=folder_id,
            discovered_count=len(videos),
            created_count=len(created_items),
            duplicate_count=duplicate_count,
            queued_count=len(task_ids),
            inbox_count=max(0, len(created_items) - sum(1 for _id, _video, kind in queued_items if kind == "new")),
            task_ids=task_ids,
            content_item_ids=selected_content_item_ids,
        )


def list_creator_sources() -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, provider, source_url, source_kind, creator_key, creator_name,
                   library_folder_id, enabled, auto_process, processing_mode, sync_interval_minutes,
                   sync_limit, queue_limit, last_sync_at, next_sync_at, last_seen_published_at,
                   last_error, last_error_category, consecutive_failure_count,
                   last_discovered_count, last_created_count,
                   created_at, updated_at
            FROM creator_sources
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [_serialize_source(row) for row in rows]


def get_creator_source(source_id: str) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise LookupError(source_id)
    return _serialize_source(row)


def list_creator_sync_runs(source_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT status, error_category, message, discovered_count, created_count, created_at
               FROM creator_sync_runs WHERE source_id=? ORDER BY created_at DESC LIMIT ?""",
            (source_id, max(1, min(int(limit), 30))),
        ).fetchall()
    return [dict(row) for row in rows]


def update_creator_source(
    source_id: str,
    *,
    enabled: bool | None = None,
    auto_process: bool | None = None,
    processing_mode: str | None = None,
    sync_interval_minutes: int | None = None,
) -> dict[str, Any]:
    if all(value is None for value in (enabled, auto_process, processing_mode, sync_interval_minutes)):
        raise CreatorSyncError("至少提供一个需要更新的订阅设置")
    if sync_interval_minutes is not None:
        _valid_interval(sync_interval_minutes)
    if processing_mode is not None:
        _valid_processing_mode(processing_mode)
    initialize_database()
    with connect() as connection:
        current = connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
        if not current:
            raise LookupError(source_id)
        next_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        next_interval = _valid_interval(sync_interval_minutes if sync_interval_minutes is not None else current["sync_interval_minutes"])
        next_mode = _effective_processing_mode(current, processing_mode, auto_process)
        next_sync_at = utc_now_iso() if enabled is True else current["next_sync_at"]
        connection.execute(
            """UPDATE creator_sources
               SET enabled=?, auto_process=?, processing_mode=?, sync_interval_minutes=?,
                   next_sync_at=?, updated_at=? WHERE id=?""",
            (
                int(next_enabled),
                int(next_mode != "metadata"),
                next_mode,
                next_interval,
                next_sync_at,
                utc_now_iso(),
                source_id,
            ),
        )
        connection.commit()
        row = connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
    return _serialize_source(row)


def delete_creator_source(source_id: str) -> None:
    initialize_database()
    with connect() as connection:
        cursor = connection.execute("DELETE FROM creator_sources WHERE id=?", (source_id,))
        connection.commit()
    if not cursor.rowcount:
        raise LookupError(source_id)


def sync_saved_creator_source(
    source_id: str,
    *,
    retry_existing_items: bool = False,
    execution_mode: Literal["foreground", "background"] = "foreground",
) -> CreatorSyncResult:
    source = get_creator_source(source_id)
    if not source["enabled"]:
        raise CreatorSyncError("该创作者订阅已暂停；恢复后再同步")
    known_item_ids = _creator_source_item_ids(source_id)
    try:
        return sync_creator_source(
            source_url=str(source["source_url"]),
            # Persisted membership remains the primary boundary; the
            # publication watermark is an additional fast path for providers
            # that expose reliable publish timestamps.
            limit=MAX_CREATOR_CAPTURE_RESPONSE_PAGES * PAGE_SIZE * 3,
            published_after=source.get("last_seen_published_at") or None,
            source_id=source_id,
            auto_process=bool(source["auto_process"]),
            sync_interval_minutes=int(source["sync_interval_minutes"]),
            published_before=None,
            processing_mode=str(source.get("processing_mode") or "full"),
            allow_personal_sources=str(source.get("source_kind") or "") in _PERSONAL_SOURCE_KINDS,
            known_item_ids=known_item_ids or None,
            retry_existing_items=retry_existing_items,
            execution_mode=execution_mode,
        )
    except Exception as exc:
        _record_sync_error(source_id, str(exc))
        if isinstance(exc, CreatorSyncError):
            raise
        raise CreatorSyncError(f"创作者同步失败：{exc}") from exc


def sync_due_creator_sources() -> list[str]:
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        rows = connection.execute(
            """SELECT id FROM creator_sources
               WHERE enabled=1 AND (next_sync_at IS NULL OR next_sync_at='' OR next_sync_at<=?)
               ORDER BY COALESCE(next_sync_at, created_at), created_at""",
            (now,),
        ).fetchall()
    from services.task_manager import task_manager

    completed: list[str] = []
    for row in rows:
        source_id = str(row["id"])
        try:
            task_manager.create_source_sync(
                {"kind": "creator_saved", "source_id": source_id},
                source_title="自动检查创作者",
                execution_mode="background",
            )
        except Exception:
            continue
        completed.append(source_id)
    return completed


def creator_capture_status() -> dict[str, Any]:
    with _CREATOR_CAPTURE_STATE_LOCK:
        status = dict(_CREATOR_CAPTURE_STATE)
        status["last_list_checks"] = {
            provider: dict(value) for provider, value in _CREATOR_CAPTURE_STATE["last_list_checks"].items()
        }
        return status


def _source_row(connection, *, source_id: str | None, source_identity: str):
    if source_id:
        return connection.execute("SELECT * FROM creator_sources WHERE id=?", (source_id,)).fetchone()
    return connection.execute("SELECT * FROM creator_sources WHERE source_identity=?", (source_identity,)).fetchone()


def _creator_source_item_ids(source_id: str) -> set[str]:
    """Return the durable membership anchor for an incremental check."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            "SELECT remote_item_id FROM creator_source_items WHERE source_id=?",
            (source_id,),
        ).fetchall()
    return {str(row["remote_item_id"]).strip() for row in rows if str(row["remote_item_id"] or "").strip()}


def _source_identity(provider: str, source_kind: str, creator_key: str) -> str:
    return f"{provider}:{source_kind}:{creator_key}"


def _canonical_creator_url(provider: str, source_kind: str, creator_key: str) -> str:
    if provider == "bilibili":
        if source_kind == "profile":
            # The space root is a personal overview page.  Bilibili can serve
            # it without ever requesting the upload list, which leaves the
            # browser reader with nothing to capture and unnecessarily sends
            # us to the lower-fidelity WBI fallback.  Open the explicit upload
            # tab instead; both URLs retain the same stable creator identity.
            return f"https://space.bilibili.com/{creator_key}/upload/video"
        mid, source_id = creator_key.split(":", 1)
        if source_kind in {"series", "collection"}:
            return f"https://space.bilibili.com/{mid}/lists/{source_id}?type={'series' if source_kind == 'series' else 'season'}"
        if source_kind in {"channel_series", "channel_collection"}:
            kind = "seriesdetail" if source_kind == "channel_series" else "collectiondetail"
            return f"https://space.bilibili.com/{mid}/channel/{kind}?sid={source_id}"
        if source_kind == "favorites":
            # Favorites are ordered by the time they were added.  Explicitly
            # retaining this view makes the personal-favorites sync inspect
            # the newest entries first instead of inheriting a browser's last
            # selected sort order.
            return f"https://space.bilibili.com/{mid}/favlist?fid={source_id}&ftype=create"
        if source_kind == "likes":
            return f"https://space.bilibili.com/{mid}/like"
    if provider == "xiaohongshu" and source_kind == "favorites":
        return f"https://www.xiaohongshu.com/user/profile/{creator_key}?tab=collect"
    if source_kind == "favorites":
        return f"https://www.douyin.com/user/{creator_key}?showSubTab=favorite_folder&showTab=favorite_collection"
    if source_kind == "likes":
        return f"https://www.douyin.com/user/{creator_key}?showTab=like"
    if source_kind == "collection":
        return f"https://www.douyin.com/collection/{creator_key}"
    if source_kind == "profile_compilations":
        return f"https://www.douyin.com/user/{creator_key}?showSubTab=compilation"
    return f"https://www.douyin.com/user/{creator_key}"


def _creator_capture_url(source_url: str, *, provider: str, source_kind: str, creator_key: str) -> str:
    """Keep a validated Douyin collection entry page for browser collection context.

    Douyin redirects ``/collection/<id>/<position>`` to a video URL after it
    has established the collection context.  The position is not part of the
    subscription identity, but stripping it before navigation prevents the
    browser from issuing the collection request in the first place.
    """
    if provider != "douyin" or source_kind != "collection":
        return _canonical_creator_url(provider, source_kind, creator_key)
    parsed = urlparse(source_url)
    match = _DOUYIN_COLLECTION_PATH_RE.fullmatch(parsed.path)
    if match and match.group("id") == creator_key and match.group("position"):
        return f"https://www.douyin.com/collection/{creator_key}/{match.group('position')}"
    return _canonical_creator_url(provider, source_kind, creator_key)


def _valid_interval(value: object) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise CreatorSyncError("检查频率无效") from exc
    if interval not in ALLOWED_SYNC_INTERVAL_MINUTES:
        choices = "、".join(str(item) for item in sorted(ALLOWED_SYNC_INTERVAL_MINUTES))
        raise CreatorSyncError(f"检查频率必须是 {choices} 分钟之一")
    return interval


def _valid_processing_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in CREATOR_PROCESSING_MODES:
        raise CreatorSyncError("处理方式必须是 metadata、transcript 或 full")
    return mode


def _valid_queue_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise CreatorSyncError("每轮入队上限无效") from exc
    if not 1 <= limit <= MAX_CREATOR_SCAN_ITEMS:
        raise CreatorSyncError(f"每轮入队上限必须在 1 到 {MAX_CREATOR_SCAN_ITEMS} 之间")
    return limit


def _effective_processing_mode(source_row, requested_mode: str | None, requested_auto_process: bool | None) -> str:
    if requested_mode is not None:
        return _valid_processing_mode(requested_mode)
    if requested_auto_process is not None:
        return "full" if requested_auto_process else "metadata"
    if source_row:
        stored_mode = source_row["processing_mode"] if "processing_mode" in source_row.keys() else None
        if stored_mode:
            return _valid_processing_mode(stored_mode)
        return "full" if bool(source_row["auto_process"]) else "metadata"
    return "full"


def _selected_preview_videos(videos: list[CreatorVideo], selected_video_ids: list[str] | None) -> list[CreatorVideo]:
    if selected_video_ids is None:
        return videos
    selected = {str(item).strip() for item in selected_video_ids if str(item).strip()}
    if not selected:
        raise CreatorSyncError("请至少选择一条预览作品")
    available = {video.canonical_id for video in videos}
    unknown = selected - available
    if unknown:
        raise CreatorSyncError("所选作品已不在本次预览中，请重新预览后提交")
    return [video for video in videos if video.canonical_id in selected]


def _unseen_prefix_before_known_item(
    videos: list[CreatorVideo],
    known_item_ids: set[str],
) -> list[CreatorVideo]:
    """Keep only remotely newer entries before this source's saved anchor.

    A creator source is ordered by the provider's own newest-first list
    order.  Once any previously linked remote id appears, every later row is
    historical for this subscription and must stay out of a normal check.
    Failing closed when the anchor is absent is important: accepting a partial
    response would turn an upstream pagination change into a bulk reimport.
    """
    if not videos:
        return []
    for index, video in enumerate(videos):
        if video.canonical_id in known_item_ids:
            return videos[:index]
    raise CreatorSyncError("本次检查未找到上次订阅的作品边界，未导入任何内容；请稍后重试")


def _serialize_source(row) -> dict[str, Any]:
    source = dict(row)
    source["enabled"] = bool(source.get("enabled", True))
    source["auto_process"] = bool(source.get("auto_process", True))
    source["processing_mode"] = _valid_processing_mode(source.get("processing_mode") or ("full" if source["auto_process"] else "metadata"))
    source["sync_interval_minutes"] = _valid_interval(
        source.get("sync_interval_minutes", settings.creator_default_interval_minutes)
    )
    # These fields remain in SQLite solely for migration compatibility. They
    # are intentionally not exposed or used by the incremental-sync contract.
    source["consecutive_failure_count"] = max(0, int(source.get("consecutive_failure_count") or 0))
    source["last_discovered_count"] = max(0, int(source.get("last_discovered_count") or 0))
    source["last_created_count"] = max(0, int(source.get("last_created_count") or 0))
    return source


def _record_sync_success(
    source_id: str,
    *,
    interval_minutes: int,
    discovered_count: int,
    created_count: int,
    last_seen_published_at: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    next_sync = now + timedelta(minutes=interval_minutes)
    with connect() as connection:
        connection.execute(
            """UPDATE creator_sources
               SET last_sync_at=?, next_sync_at=?, last_seen_published_at=?, last_error=NULL,
                   last_error_category=NULL, consecutive_failure_count=0,
                   last_discovered_count=?, last_created_count=?, updated_at=?
               WHERE id=?""",
            (
                now.isoformat(),
                next_sync.isoformat(),
                last_seen_published_at,
                max(0, int(discovered_count)),
                max(0, int(created_count)),
                now.isoformat(),
                source_id,
            ),
        )
        connection.execute(
            """INSERT INTO creator_sync_runs
               (id, source_id, status, message, discovered_count, created_count, created_at)
               VALUES (?, ?, 'succeeded', '', ?, ?, ?)""",
            (new_id(), source_id, max(0, int(discovered_count)), max(0, int(created_count)), now.isoformat()),
        )
        connection.commit()


def _latest_published_at(videos: list[CreatorVideo]) -> str | None:
    values = [str(video.published_at).strip() for video in videos if video.published_at]
    return max(values, default=None)


def _record_sync_error(source_id: str, message: str) -> None:
    now = datetime.now(timezone.utc)
    with connect() as connection:
        row = connection.execute(
            "SELECT sync_interval_minutes, consecutive_failure_count FROM creator_sources WHERE id=?", (source_id,)
        ).fetchone()
        if not row:
            return
        category = _creator_error_category(message)
        failures = max(0, int(row["consecutive_failure_count"] or 0)) + 1
        retry_minutes = _creator_retry_minutes(category, failures, _valid_interval(row["sync_interval_minutes"]))
        connection.execute(
            """UPDATE creator_sources
               SET last_error=?, last_error_category=?, consecutive_failure_count=?, next_sync_at=?, updated_at=? WHERE id=?""",
            (str(message or "同步失败")[:500], category, failures, (now + timedelta(minutes=retry_minutes)).isoformat(), now.isoformat(), source_id),
        )
        connection.execute(
            """INSERT INTO creator_sync_runs (id, source_id, status, error_category, message, created_at)
               VALUES (?, ?, 'failed', ?, ?, ?)""",
            (new_id(), source_id, category, str(message or "同步失败")[:500], now.isoformat()),
        )
        connection.commit()


def _creator_error_category(message: str) -> str:
    text = str(message or "").lower()
    # -352 is Bilibili's risk-control response.  The combined browser/WBI
    # error can also mention the saved login state, but that does not mean the
    # session is expired.  Treat it as a transient remote failure so the UI
    # gives an accurate diagnosis and the source retries on the normal path.
    if any(token in text for token in ("错误码 -352", "error code -352", "风控", "风险校验", "risk control")):
        return "remote"
    if any(token in text for token in ("cookie", "登录", "403", "412", "授权")):
        return "authorization"
    if any(token in text for token in ("timeout", "超时", "暂时", "网络", "拒绝")):
        return "remote"
    if any(token in text for token in ("chromium", "浏览器组件", "内置浏览器")):
        return "runtime"
    return "unknown"


def _creator_retry_minutes(category: str, failures: int, configured_interval: int) -> int:
    if category == "authorization":
        return max(configured_interval, 360)
    base = 30 if category == "remote" else 60
    return min(720, max(configured_interval, base * (2 ** min(max(0, failures - 1), 4))))


def _parse_creator_url(source_url: str) -> tuple[str, str, str]:
    parsed = urlparse(source_url)
    if parsed.scheme != "https":
        raise CreatorSyncError("链接必须使用 HTTPS")
    host = (parsed.hostname or "").lower()
    if host == "space.bilibili.com":
        if match := _BILIBILI_SPACE_PATH_RE.fullmatch(parsed.path):
            return "bilibili", "profile", match.group("id")
        query = parse_qs(parsed.query)
        if match := _BILIBILI_LIST_PATH_RE.fullmatch(parsed.path):
            source_kind = "series" if query.get("type", [""])[0] == "series" else "collection"
            return "bilibili", source_kind, f"{match.group('mid')}:{match.group('id')}"
        if match := _BILIBILI_CHANNEL_PATH_RE.fullmatch(parsed.path):
            sid = query.get("sid", [""])[0]
            if sid.isdigit():
                source_kind = "channel_series" if match.group("kind") == "seriesdetail" else "channel_collection"
                return "bilibili", source_kind, f"{match.group('mid')}:{sid}"
        if match := _BILIBILI_FAVORITES_PATH_RE.fullmatch(parsed.path):
            fid = query.get("fid", [""])[0]
            if fid.isdigit():
                return "bilibili", "favorites", f"{match.group('mid')}:{fid}"
        if match := _BILIBILI_LIKES_PATH_RE.fullmatch(parsed.path):
            return "bilibili", "likes", f"{match.group('mid')}:liked"
    if host in {"douyin.com", "www.douyin.com"}:
        if match := _DOUYIN_COLLECTION_PATH_RE.fullmatch(parsed.path):
            return "douyin", "collection", match.group("id")
        if match := _DOUYIN_USER_PATH_RE.fullmatch(parsed.path):
            query = parse_qs(parsed.query)
            active_tab = str(query.get("showTab", [""])[0]).lower()
            active_sub_tab = str(query.get("showSubTab", [""])[0]).lower()
            if active_tab in {"like", "liked"}:
                return "douyin", "likes", match.group("id")
            if active_tab in {"favorite", "favorite_collection"} or active_sub_tab == "favorite_folder":
                return "douyin", "favorites", match.group("id")
            if query.get("showSubTab", [""])[0] == "compilation":
                return "douyin", "profile_compilations", match.group("id")
            return "douyin", "profile", match.group("id")
    if host in {"xiaohongshu.com", "www.xiaohongshu.com"}:
        if match := _XIAOHONGSHU_PROFILE_PATH_RE.fullmatch(parsed.path):
            query = parse_qs(parsed.query)
            active_tab = str(
                query.get("tab", query.get("showTab", query.get("section", [""])))[0]
            ).lower()
            # The web profile currently labels the favorites tab `fav`; older
            # shared links have used the other spellings below.  They all map
            # to the same current-account favorites pipeline.
            if active_tab in {"fav", "collect", "collection", "favorite", "favorites"}:
                return "xiaohongshu", "favorites", match.group("id")
            raise CreatorSyncError("小红书目前仅支持“我的收藏”链接；请从个人主页的收藏页复制链接")
    raise CreatorSyncError("仅支持抖音/B站的主页、合集、收藏夹或喜欢列表，以及小红书“我的收藏”链接")


def _preview_douyin_profile_in_browser(
    *,
    source_url: str,
    creator_key: str,
    limit: int,
    cutoff: datetime | None,
    known_item_ids: set[str] | None = None,
    compilation_view: bool = False,
) -> CreatorPreview:
    payloads, title = _capture_browser_pages(
        source_url=source_url,
        response_matcher=_douyin_compilation_response if compilation_view else _douyin_profile_response,
        limit=limit,
        provider="douyin",
        stop_at=cutoff,
        known_item_ids=known_item_ids,
    )
    videos: list[CreatorVideo] = []
    creator_name = ""
    for payload in payloads:
        page_videos, page_creator_name, _cursor, _has_more = _parse_page(payload, provider="douyin")
        creator_name = creator_name or page_creator_name
        _append_new_videos(videos, page_videos, limit=limit, cutoff=cutoff)
        if len(videos) >= limit:
            break
    # A scheduled incremental check can legitimately find nothing newer than
    # its watermark. That is a successful check, not a scraper failure: the
    # caller must still advance the next scheduled run.
    if not videos and cutoff is None:
        _record_creator_list_check("douyin", state="failed", detail="页面未返回可解析的作品列表")
        if compilation_view:
            raise CreatorSyncError("已读取到抖音主页合集目录，但尚未定位到具体合集作品；请粘贴 /collection/ 开头的合集链接")
        raise CreatorSyncError("未从抖音主页取得作品；请检查抖音 Cookie 是否仍有效")
    preview = CreatorPreview(
        provider="douyin",
        source_kind="profile_compilations" if compilation_view else "profile",
        source_url=source_url,
        creator_key=creator_key,
        creator_name=creator_name or _creator_name_from_page_title(title) or _fallback_creator_name("douyin", creator_key),
        videos=videos,
    )
    _record_creator_list_check("douyin", state="valid", detail=f"取得 {len(videos)} 条作品")
    return preview


def _preview_douyin_collection_in_browser(
    *,
    source_url: str,
    capture_url: str | None = None,
    creator_key: str,
    limit: int,
    cutoff: datetime | None,
    known_item_ids: set[str] | None = None,
) -> CreatorPreview:
    # A collection entry redirects to a video page in normal browser use. The
    # browser capture is the single application-owned implementation.
    options = {
        "source_url": source_url,
        "capture_url": capture_url,
        "creator_key": creator_key,
        "limit": limit,
        "cutoff": cutoff,
    }
    if known_item_ids:
        options["known_item_ids"] = known_item_ids
    return _preview_douyin_collection_via_browser_capture(
        **options,
    )


def _preview_douyin_personal_source_in_browser(
    *,
    source_url: str,
    creator_key: str,
    source_kind: str,
    limit: int,
    cutoff: datetime | None,
    known_item_ids: set[str] | None = None,
) -> CreatorPreview:
    """Read local Douyin favourites or likes through the bundled browser.

    Douyin itself generates the signed list request inside the existing local
    browser session.  This never copies a Cookie into the renderer or asks us
    to recreate a signing algorithm.  Source membership is persisted
    separately from canonical content, so a video in both lists is stored once
    while both subscriptions remain visible and independently checkable.
    """
    matcher = {
        "favorites": lambda url: "listcollection" in url or "/aweme/v1/web/favorite/collection" in url,
        "likes": lambda url: any(marker in url for marker in (
            "/aweme/v1/web/aweme/favorite/",
            "/aweme/v1/web/aweme/like/",
            "/aweme/v1/web/aweme/liked/",
        )),
    }[source_kind]
    payloads, title = _capture_browser_pages(
        source_url=source_url,
        response_matcher=matcher,
        # The collection page has changed endpoint names several times.  Its
        # stable contract is the aweme-list payload, not a particular path.
        # Restrict this fallback to the current personal page's XHR/fetch
        # responses in ``_capture_browser_pages``.
        payload_matcher=_has_douyin_aweme_list,
        limit=limit,
        provider="douyin",
        stop_at=cutoff,
        known_item_ids=known_item_ids,
    )
    videos: list[CreatorVideo] = []
    for payload in payloads:
        page_videos, _page_creator_name, _cursor, _has_more = _parse_page(payload, provider="douyin")
        _append_new_videos(videos, page_videos, limit=limit, cutoff=cutoff)
        if len(videos) >= limit:
            break
    label = "我的抖音收藏" if source_kind == "favorites" else "我的抖音喜欢"
    if not videos and cutoff is None:
        _record_creator_list_check("douyin", state="failed", detail=f"{label}页面未返回可解析的作品列表")
        raise CreatorSyncError(f"未从{label}取得作品；请确认当前抖音登录态可查看该列表")
    _record_creator_list_check("douyin", state="valid", detail=f"{label}取得 {len(videos)} 条作品")
    return CreatorPreview(
        provider="douyin",
        source_kind=source_kind,
        source_url=source_url,
        creator_key=creator_key,
        # Personal likes/favourites contain works authored by other people.
        # Never infer the subscription owner from the first work in that
        # list; use the account page title, with a stable local label only as
        # the fallback when Douyin does not expose it.
        creator_name=_personal_douyin_creator_name(title) or label,
        videos=videos,
    )


def _preview_xiaohongshu_favorites(
    *,
    source_url: str,
    creator_key: str,
    limit: int,
) -> CreatorPreview:
    """Preview the current local XHS account's favourites through one API bridge."""
    from services.xiaohongshu_client import XiaohongshuClientError, fetch_my_favorites_preview

    try:
        notes, account = fetch_my_favorites_preview(limit=limit, profile_user_id=creator_key)
    except XiaohongshuClientError as exc:
        _record_creator_list_check("xiaohongshu", state="failed", detail=str(exc))
        raise CreatorSyncError(str(exc)) from exc
    account_id = str(account.get("user_id") or "").strip()
    if not account_id:
        raise CreatorSyncError("未读取到当前小红书账号，无法确认收藏归属")
    # The local Cookie is used only for authentication. The profile ID in the
    # pasted 收藏 page is the identity expected by the collection endpoint;
    # `user/me` may expose a different identifier for the same XHS account.
    collection_user_id = str(account.get("collection_user_id") or creator_key or account_id).strip()
    videos = [
        CreatorVideo(
            provider="xiaohongshu",
            canonical_id=note.note_id,
            source_url=note.source_url,
            title=note.title,
            cover_url=note.image_urls[0] if note.image_urls else "",
            published_at=note.published_at or None,
            description=note.description,
            author_name=note.author,
            tags=note.tags,
            stats=note.stats,
        )
        for note in notes
    ]
    creator_name = str(account.get("nickname") or "我的小红书收藏")
    _record_creator_list_check("xiaohongshu", state="valid", detail=f"取得 {len(videos)} 条收藏")
    return CreatorPreview(
        provider="xiaohongshu",
        source_kind="favorites",
        source_url=_canonical_creator_url("xiaohongshu", "favorites", collection_user_id),
        creator_key=collection_user_id,
        creator_name=creator_name,
        creator_avatar_url=str(account.get("avatar_url") or ""),
        videos=videos,
    )


def _preview_douyin_collection_via_browser_capture(
    *,
    source_url: str,
    capture_url: str | None = None,
    creator_key: str,
    limit: int,
    cutoff: datetime | None,
    known_item_ids: set[str] | None = None,
) -> CreatorPreview:
    payloads, title = _capture_browser_pages(
        source_url=capture_url or source_url,
        response_matcher=lambda url: "/aweme/v1/web/mix/aweme/" in url,
        limit=limit,
        provider="douyin",
        stop_at=cutoff,
        known_item_ids=known_item_ids,
    )
    videos: list[CreatorVideo] = []
    creator_name = ""
    for payload in payloads:
        page_videos, page_creator_name, _cursor, _has_more = _parse_page(payload, provider="douyin")
        creator_name = creator_name or page_creator_name
        _append_new_videos(videos, page_videos, limit=limit, cutoff=cutoff)
        if len(videos) >= limit:
            break
    # See the profile reader above: an empty incremental result is normal.
    if not videos and cutoff is None:
        _record_creator_list_check("douyin", state="failed", detail="合集入口未返回可解析的作品列表")
        raise CreatorSyncError("未从抖音合集取得作品；页面未返回合集列表，请稍后重试")
    preview = CreatorPreview(
        provider="douyin",
        source_kind="collection",
        source_url=source_url,
        creator_key=creator_key,
        creator_name=creator_name or _creator_name_from_page_title(title) or _fallback_creator_name("douyin", creator_key),
        videos=videos,
    )
    _record_creator_list_check("douyin", state="valid", detail=f"取得 {len(videos)} 条合集作品")
    return preview


def _preview_bilibili_source_in_browser(
    *,
    source_url: str,
    creator_key: str,
    source_kind: str,
    limit: int,
    cutoff: datetime | None,
    known_item_ids: set[str] | None = None,
) -> CreatorPreview:
    matcher = {
        "profile": lambda url: "/x/space/wbi/arc/search" in url,
        "series": lambda url: "/x/series/archives" in url,
        "collection": lambda url: "/x/polymer/web-space/seasons_archives_list" in url,
        "channel_series": lambda url: "/x/polymer/web-space/seasons_archives_list" in url,
        "channel_collection": lambda url: "/x/polymer/web-space/seasons_archives_list" in url,
        "favorites": lambda url: "/x/v3/fav/resource/list" in url,
        "likes": lambda url: "/x/space/like/video" in url,
    }[source_kind]
    try:
        payloads, title = _capture_browser_pages(
            source_url=source_url,
            response_matcher=matcher,
            limit=limit,
            provider="bilibili",
            stop_at=cutoff,
            known_item_ids=known_item_ids,
        )
    except CreatorSyncError as exc:
        if source_kind == "profile":
            return _preview_bilibili_profile_via_wbi(creator_key=creator_key, limit=limit, cutoff=cutoff, browser_error=exc)
        raise
    videos: list[CreatorVideo] = []
    creator_name = ""
    collection_name = ""
    for payload in payloads:
        response_code = _as_int(payload.get("code"))
        if response_code not in {None, 0}:
            if source_kind == "profile":
                return _preview_bilibili_profile_via_wbi(
                    creator_key=creator_key,
                    limit=limit,
                    cutoff=cutoff,
                    browser_error=CreatorSyncError(f"B站浏览器列表接口返回 {response_code}"),
                )
            raise CreatorSyncError(f"B 站暂时拒绝了作品列表请求（错误码 {response_code}）；请在设置中更新 B 站登录 Cookie 后重试")
        page_videos, page_creator_name, _cursor, _has_more = _parse_page(payload, provider="bilibili")
        creator_name = creator_name or page_creator_name
        collection_name = collection_name or _collection_name_from_payload(payload)
        _append_new_videos(videos, page_videos, limit=limit, cutoff=cutoff)
        if len(videos) >= limit:
            break
    # See the profile reader above: an empty incremental result is normal.
    if not videos and cutoff is None:
        _record_creator_list_check("bilibili", state="failed", detail="页面未返回可解析的作品列表")
        raise CreatorSyncError("未从 B 站来源取得作品；请稍后重试、检查链接或 B 站登录态")
    preview = CreatorPreview(
        provider="bilibili",
        source_kind=source_kind,
        source_url=source_url,
        creator_key=creator_key,
        creator_name=creator_name or _creator_name_from_page_title(title) or _fallback_creator_name("bilibili", creator_key.split(":", 1)[0]),
        videos=videos,
        collection_id=creator_key.split(":", 1)[-1] if source_kind != "profile" else "",
        collection_name=collection_name,
    )
    _record_creator_list_check("bilibili", state="valid", detail=f"取得 {len(videos)} 条作品")
    return preview


def _preview_bilibili_profile_via_wbi(
    *, creator_key: str, limit: int, cutoff: datetime | None, browser_error: CreatorSyncError
) -> CreatorPreview:
    """Fallback for a browser XHR rejection; keeps creator collection local."""
    from services.bilibili_creator_api import BilibiliCreatorApiError, fetch_creator_profile_videos

    try:
        rows, profile = fetch_creator_profile_videos(mid=creator_key, limit=limit)
    except BilibiliCreatorApiError as exc:
        raise CreatorSyncError(f"B站主页读取失败（浏览器：{browser_error}；WBI 回退：{exc}）") from exc
    candidates = [video for row in rows if (video := _bilibili_video(row)) is not None]
    videos: list[CreatorVideo] = []
    _append_new_videos(videos, candidates, limit=limit, cutoff=cutoff)
    if not videos and cutoff is None:
        raise CreatorSyncError("B站主页没有返回公开作品；请检查该主页是否公开或稍后重试")
    preview = CreatorPreview(
        provider="bilibili",
        source_kind="profile",
        source_url=_canonical_creator_url("bilibili", "profile", creator_key),
        creator_key=creator_key,
        creator_name=profile.name or _fallback_creator_name("bilibili", creator_key),
        creator_avatar_url=profile.avatar_url,
        creator_description=profile.description,
        videos=videos,
    )
    _record_creator_list_check("bilibili", state="valid", detail=f"WBI 回退取得 {len(videos)} 条作品")
    return preview


def _preview_bilibili_profile_in_browser(
    *, source_url: str, creator_key: str, limit: int, cutoff: datetime | None,
    known_item_ids: set[str] | None = None,
) -> CreatorPreview:
    """Compatibility entry point for the original B站空间采集器 tests."""
    return _preview_bilibili_source_in_browser(
        source_url=source_url,
        creator_key=creator_key,
        source_kind="profile",
        limit=limit,
        cutoff=cutoff,
        known_item_ids=known_item_ids,
    )


def _capture_browser_pages(
    *,
    source_url: str,
    response_matcher,
    payload_matcher=None,
    limit: int,
    provider: str,
    stop_at: datetime | None,
    known_item_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    try:
        from playwright.sync_api import sync_playwright
        from services.bilibili_auth import bilibili_playwright_cookies
        from services.downloader import _load_cookies_for_playwright, browser_executable
    except ImportError as exc:
        raise CreatorSyncError("内置浏览器组件不可用；请在设置中安装 Chromium 后重试") from exc

    executable = browser_executable()
    if not executable:
        raise CreatorSyncError("未找到内置 Chromium；请在设置 > 设备准备中安装后重试")
    pages: list[dict[str, Any]] = []
    bilibili_favorites_page_url = ""
    _wait_for_creator_browser(provider)
    with _CREATOR_BROWSER_LOCK:
        _begin_creator_browser_capture(provider)
        try:
            with sync_playwright() as playwright:
                _set_creator_capture_stage("启动内置浏览器")
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=executable,
                    **direct_browser_launch_options("--disable-blink-features=AutomationControlled"),
                )
                try:
                    # Keep the browser's own UA and network fingerprint in
                    # sync.  The previous fixed Chrome/131 UA diverged from
                    # the bundled Chromium as it was updated, which makes the
                    # request look synthetic to Bilibili's risk controls.
                    context = browser.new_context(
                        locale="zh-CN",
                        viewport={"width": 1440, "height": 1000},
                    )
                    cookies = _load_cookies_for_playwright() + bilibili_playwright_cookies()
                    if cookies:
                        context.add_cookies(cookies)
                    page = context.new_page()
                    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

                    # Douyin and Bilibili both use virtualized grids.  A grid
                    # can prefetch a page without changing document height, so
                    # tying collection to one scroll event loses responses.
                    # Observe every matching API response for this page and
                    # use scrolling only as a nudge to request the next one.
                    def capture_response(response) -> None:
                        nonlocal bilibili_favorites_page_url
                        url_matches = response_matcher(response.url)
                        # A provider may rename a list endpoint without
                        # changing its schema. A caller can opt into a narrow
                        # payload fallback, limited to fetch/XHR traffic so
                        # document and asset responses are never inspected.
                        may_match_payload = bool(
                            payload_matcher
                            and response.request.resource_type in {"fetch", "xhr"}
                        )
                        if not url_matches and not may_match_payload:
                            return
                        try:
                            payload = response.json()
                        except Exception:
                            return
                        payload_matches = bool(
                            payload_matcher
                            and isinstance(payload, dict)
                            and payload_matcher(payload)
                        )
                        if isinstance(payload, dict) and (url_matches or payload_matches):
                            pages.append(payload)
                            if provider == "bilibili":
                                next_url = _next_bilibili_favorites_page_url(response.url)
                                if next_url:
                                    bilibili_favorites_page_url = next_url

                    page.on("response", capture_response)
                    _set_creator_capture_stage("读取创作者页面")
                    page.goto(source_url, wait_until="domcontentloaded", timeout=30_000)
                    if not _wait_for_creator_page_count(page, pages, expected_count=1, timeout_ms=30_000):
                        raise CreatorSyncError("创作者页面没有返回作品列表；请确认链接公开且当前登录态可用")

                    while _should_continue_creator_capture(
                        pages,
                        provider=provider,
                        limit=limit,
                        watermark=stop_at,
                        known_item_ids=known_item_ids,
                    ):
                        _set_creator_capture_stage("加载更多作品")
                        captured_count = len(pages)
                        received_next_page = False
                        for _ in range(MAX_CREATOR_LOAD_ATTEMPTS):
                            if bilibili_favorites_page_url:
                                _request_creator_api_page(page, bilibili_favorites_page_url)
                            else:
                                _nudge_creator_page_load(page)
                            if _wait_for_creator_page_count(
                                page,
                                pages,
                                expected_count=captured_count + 1,
                                timeout_ms=CREATOR_PAGE_RESPONSE_WAIT_MS,
                            ):
                                received_next_page = True
                                break
                        if not received_next_page:
                            break
                    title = page.title()
                    context.close()
                finally:
                    browser.close()
        except CreatorSyncError:
            _record_creator_list_check(provider, state="failed", detail="未取得作品列表")
            raise
        except Exception as exc:
            _record_creator_list_check(provider, state="failed", detail=str(exc))
            raise CreatorSyncError(f"内置浏览器采集失败：{exc}") from exc
        finally:
            _finish_creator_browser_capture()
    return pages, title


def _next_bilibili_favorites_page_url(response_url: str) -> str:
    """Build the next page URL from Bilibili's browser-originated list call."""
    parsed = urlparse(response_url)
    if parsed.path != "/x/v3/fav/resource/list":
        return ""
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    try:
        current_page = max(1, int(query.get("pn") or 1))
    except (TypeError, ValueError):
        current_page = 1
    query["pn"] = str(current_page + 1)
    return parsed._replace(query=urlencode(query)).geturl()


def _request_creator_api_page(page, url: str) -> None:
    """Request a known next page inside the captured browser session."""
    try:
        page.evaluate(
            """(nextUrl) => { void fetch(nextUrl, { credentials: 'include' }); }""",
            url,
        )
    except Exception:
        # The usual scroll nudge on the following retry is the compatible
        # fallback when a navigation briefly invalidates the page context.
        _nudge_creator_page_load(page)


def _wait_for_creator_page_count(page, pages: list[dict[str, Any]], *, expected_count: int, timeout_ms: int) -> bool:
    """Wait for a response event without relying on a scrollable document."""
    elapsed_ms = 0
    while elapsed_ms < timeout_ms:
        if len(pages) >= expected_count:
            return True
        page.wait_for_timeout(250)
        elapsed_ms += 250
    return len(pages) >= expected_count


def _nudge_creator_page_load(page) -> None:
    """Ask both ordinary and virtualized creator grids to load their next page."""
    try:
        page.mouse.wheel(0, 900)
        page.evaluate(
            """() => {
                window.scrollBy(0, Math.max(720, window.innerHeight * 0.9));
                window.scrollTo(0, document.documentElement.scrollHeight || document.body.scrollHeight);
                // Douyin keeps the profile grid in an overflow container;
                // scrolling window alone never reaches its intersection
                // sentinel.  Class names are hashed, so identify the few
                // actual vertical scroll containers structurally instead.
                const containers = [...document.querySelectorAll('*')]
                    .filter((node) => {
                        const style = getComputedStyle(node);
                        return (style.overflowY === 'auto' || style.overflowY === 'scroll')
                            && node.scrollHeight > node.clientHeight + 24;
                    })
                    .sort((left, right) => right.clientHeight - left.clientHeight)
                    .slice(0, 3);
                for (const container of containers) {
                    container.scrollTop = container.scrollHeight;
                    container.dispatchEvent(new Event('scroll', { bubbles: true }));
                }
            }"""
        )
    except Exception:
        # A navigation or a grid re-render can invalidate the frame briefly.
        # The response wait remains authoritative and a later nudge retries.
        return


def _should_continue_creator_capture(
    pages: list[dict[str, Any]],
    *,
    provider: str,
    limit: int,
    watermark: datetime | None,
    known_item_ids: set[str] | None = None,
) -> bool:
    if not pages:
        return True
    latest = pages[-1]
    latest_videos, _creator_name, _cursor, has_more = _parse_page(latest, provider=provider)
    if known_item_ids and any(video.canonical_id in known_item_ids for video in latest_videos):
        return False
    if len(pages) >= MAX_CREATOR_CAPTURE_RESPONSE_PAGES:
        if known_item_ids:
            raise CreatorSyncError("本次检查尚未找到上次订阅的作品边界，已停止以避免遗漏；请稍后重试")
        return False
    if not has_more:
        if known_item_ids:
            raise CreatorSyncError("本次检查未找到上次订阅的作品边界，未导入任何内容；请稍后重试")
        return False
    if _page_reaches_watermark(latest, provider=provider, watermark=watermark):
        return False
    captured_ids = {
        video.canonical_id
        for payload in pages
        for video in _parse_page(payload, provider=provider)[0]
    }
    return len(captured_ids) < limit


def _wait_for_creator_browser(provider: str) -> None:
    with _CREATOR_CAPTURE_STATE_LOCK:
        _CREATOR_CAPTURE_STATE["waiting_count"] += 1
        if not _CREATOR_CAPTURE_STATE["active"]:
            _CREATOR_CAPTURE_STATE["provider"] = provider
            _CREATOR_CAPTURE_STATE["stage"] = "等待内置浏览器"


def _begin_creator_browser_capture(provider: str) -> None:
    with _CREATOR_CAPTURE_STATE_LOCK:
        _CREATOR_CAPTURE_STATE["waiting_count"] = max(0, int(_CREATOR_CAPTURE_STATE["waiting_count"]) - 1)
        _CREATOR_CAPTURE_STATE["active"] = True
        _CREATOR_CAPTURE_STATE["provider"] = provider
        _CREATOR_CAPTURE_STATE["stage"] = "准备采集"


def _set_creator_capture_stage(stage: str) -> None:
    with _CREATOR_CAPTURE_STATE_LOCK:
        if _CREATOR_CAPTURE_STATE["active"]:
            _CREATOR_CAPTURE_STATE["stage"] = stage


def _finish_creator_browser_capture() -> None:
    with _CREATOR_CAPTURE_STATE_LOCK:
        _CREATOR_CAPTURE_STATE["active"] = False
        _CREATOR_CAPTURE_STATE["provider"] = ""
        _CREATOR_CAPTURE_STATE["stage"] = "等待内置浏览器" if _CREATOR_CAPTURE_STATE["waiting_count"] else "空闲"


def _record_creator_list_check(provider: str, *, state: str, detail: str) -> None:
    if provider not in {"douyin", "bilibili"}:
        return
    with _CREATOR_CAPTURE_STATE_LOCK:
        _CREATOR_CAPTURE_STATE["last_list_checks"][provider] = {
            "state": state,
            "detail": str(detail)[:300],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }


def _page_reaches_watermark(payload: dict[str, Any], *, provider: str, watermark: datetime | None) -> bool:
    if not watermark:
        return False
    videos, _creator_name, _cursor, _has_more = _parse_page(payload, provider=provider)
    dated = [_parse_timestamp(video.published_at) for video in videos if video.published_at]
    return bool(dated) and min(dated) <= watermark


def _append_new_videos(
    destination: list[CreatorVideo],
    candidates: list[CreatorVideo],
    *,
    limit: int,
    cutoff: datetime | None,
) -> None:
    known_ids = {video.canonical_id for video in destination}
    for video in candidates:
        if cutoff and video.published_at and _parse_timestamp(video.published_at) < cutoff:
            continue
        if video.canonical_id not in known_ids:
            destination.append(video)
            known_ids.add(video.canonical_id)
        if len(destination) >= limit:
            return


def _preview_within_date_range(
    preview: CreatorPreview,
    *,
    after: datetime | None,
    before: datetime | None,
) -> CreatorPreview:
    """Apply the selected date range consistently after provider pagination."""
    if not after and not before:
        return preview
    # Date-only values are inclusive from the UI perspective.
    inclusive_before = before + timedelta(days=1) if before else None
    videos = [
        video for video in preview.videos
        if video.published_at
        and (after is None or _parse_timestamp(video.published_at) >= after)
        and (inclusive_before is None or _parse_timestamp(video.published_at) < inclusive_before)
    ]
    return CreatorPreview(
        provider=preview.provider,
        source_kind=preview.source_kind,
        source_url=preview.source_url,
        creator_key=preview.creator_key,
        creator_name=preview.creator_name,
        videos=videos,
        creator_avatar_url=preview.creator_avatar_url,
        creator_description=preview.creator_description,
        collection_id=preview.collection_id,
        collection_name=preview.collection_name,
    )


def _creator_name_from_page_title(title: str) -> str:
    cleaned = (title or "").replace(" - 抖音", "").replace(" - 哔哩哔哩", "").strip()
    return cleaned.removesuffix("的抖音").strip()


def _personal_douyin_creator_name(title: str) -> str:
    """Return the signed-in account name from a personal Douyin page title."""
    candidate = _creator_name_from_page_title(title)
    # Generic page titles are not account names and would make the source
    # label unstable or misleading when a login interstitial is shown.
    return "" if candidate.lower() in {"", "抖音", "douyin", "我的"} else candidate


def _has_douyin_aweme_list(payload: dict[str, Any]) -> bool:
    """Recognise a Douyin work-list response independent of its endpoint URL."""
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    rows = root.get("aweme_list") or root.get("aweme_list_data")
    return isinstance(rows, list)


def _douyin_profile_response(url: str) -> bool:
    return any(marker in url for marker in ("/aweme/v1/web/aweme/post/", "/aweme/v1/web/aweme/list/"))


def _douyin_compilation_response(url: str) -> bool:
    return _douyin_profile_response(url) or any(
        marker in url for marker in ("/aweme/v1/web/mix/aweme/", "/aweme/v1/web/mix/list/")
    )


def _source_section_label(source_kind: str, collection_name: str) -> str:
    if source_kind == "profile_compilations":
        return collection_name or "主页合集"
    if source_kind in {"collection", "series", "channel_series", "channel_collection"}:
        return collection_name or "合集"
    if source_kind == "favorites":
        return "我的收藏"
    if source_kind == "likes":
        return "我的喜欢"
    return "主页作品"


def _link_creator_source_item(connection, source_id: str, content_item_id: str, remote_item_id: str, created_at: str) -> None:
    """Keep source membership without duplicating a library content item."""
    connection.execute(
        """INSERT OR IGNORE INTO creator_source_items
           (source_id, content_item_id, remote_item_id, created_at)
           VALUES (?, ?, ?, ?)""",
        (source_id, content_item_id, remote_item_id, created_at),
    )


def _parse_page(payload: dict[str, Any], *, provider: str) -> tuple[list[CreatorVideo], str, int | None, bool]:
    if provider == "douyin":
        payload = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        rows = payload.get("aweme_list") or payload.get("aweme_list_data") or []
        if not isinstance(rows, list):
            rows = []
        videos = [_douyin_video(row) for row in rows if isinstance(row, dict)]
        videos = [video for video in videos if video is not None]
        author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        creator_name = str(author.get("nickname") or "")
        if not creator_name and rows and isinstance(rows[0], dict):
            creator_name = str(((rows[0].get("author") or {}).get("nickname")) or "")
        next_cursor = _as_int(payload.get("max_cursor") or payload.get("cursor"))
        return videos, creator_name, next_cursor, bool(payload.get("has_more"))

    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    data = root.get("list") if isinstance(root.get("list"), dict) else root
    rows = data.get("vlist") or data.get("list") or data.get("archives") or data.get("medias") or root.get("archives") or root.get("medias") or []
    if not isinstance(rows, list):
        rows = []
    videos = [_bilibili_video(row) for row in rows if isinstance(row, dict)]
    videos = [video for video in videos if video is not None]
    meta = root.get("meta") if isinstance(root.get("meta"), dict) else {}
    creator_name = str(data.get("owner_name") or data.get("name") or meta.get("owner_name") or meta.get("author") or "")
    if not creator_name and rows and isinstance(rows[0], dict):
        creator_name = _bilibili_author_name(rows[0])
    page_info = data.get("page") if isinstance(data.get("page"), dict) else {}
    page_number = int(page_info.get("pn") or 1)
    page_size = int(page_info.get("ps") or len(rows) or PAGE_SIZE)
    total_items = int(page_info.get("count") or 0)
    explicit_has_more = data.get("has_more")
    has_more = bool(explicit_has_more) if isinstance(explicit_has_more, (bool, int)) else bool(rows) and (not total_items or page_number * page_size < total_items)
    return videos, creator_name, None, has_more


def _douyin_video(row: dict[str, Any]) -> CreatorVideo | None:
    video_id = str(row.get("aweme_id") or row.get("id") or "").strip()
    if not video_id:
        return None
    video = row.get("video") if isinstance(row.get("video"), dict) else {}
    cover = video.get("cover") if isinstance(video.get("cover"), dict) else {}
    cover_list = cover.get("url_list") if isinstance(cover.get("url_list"), list) else []
    published = _timestamp_iso(row.get("create_time"))
    author = row.get("author") if isinstance(row.get("author"), dict) else {}
    statistics = row.get("statistics") if isinstance(row.get("statistics"), dict) else {}
    return CreatorVideo(
        provider="douyin",
        canonical_id=video_id,
        source_url=f"https://www.douyin.com/video/{video_id}",
        title=str(row.get("desc") or video_id),
        cover_url=str(cover_list[0]) if cover_list else "",
        duration_seconds=_as_float(video.get("duration"), scale=1000),
        published_at=published,
        description=str(row.get("desc") or ""),
        author_name=str(author.get("nickname") or ""),
        tags=tuple(_douyin_tags(row)),
        stats=_normalized_stats(statistics, {
            "play": "play_count", "like": "digg_count", "comment": "comment_count",
            "favorite": "collect_count", "share": "share_count",
        }),
    )


def _bilibili_video(row: dict[str, Any]) -> CreatorVideo | None:
    video_id = str(row.get("bvid") or row.get("bv_id") or "").strip()
    if not video_id:
        return None
    cover = row.get("pic") or row.get("cover")
    if isinstance(cover, str) and cover.startswith("//"):
        cover = f"https:{cover}"
    stats_source = dict(row)
    if isinstance(row.get("stat"), dict):
        stats_source.update(row["stat"])
    return CreatorVideo(
        provider="bilibili",
        canonical_id=video_id,
        source_url=f"https://www.bilibili.com/video/{video_id}",
        title=str(row.get("title") or video_id),
        cover_url=str(cover or ""),
        duration_seconds=_duration_from_bilibili(row),
        published_at=_timestamp_iso(row.get("created") or row.get("pubdate")),
        description=str(row.get("description") or row.get("desc") or ""),
        author_name=_bilibili_author_name(row),
        tags=tuple(_string_list(row.get("tags"))),
        stats=_normalized_stats(
            stats_source,
            {
                "play": ("view", "play"), "like": "like", "coin": "coin", "favorite": "favorite",
                "share": "share", "comment": ("reply", "video_review", "comment"), "danmaku": "danmaku",
            },
        ),
    )


def _bilibili_author_name(row: dict[str, Any]) -> str:
    owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
    author = row.get("author")
    return str(owner.get("name") or author or row.get("owner_name") or "")


def _douyin_tags(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    challenge = row.get("cha_list") or row.get("challenge")
    if isinstance(challenge, list):
        values.extend(str(item.get("cha_name") or item.get("title") or "") for item in challenge if isinstance(item, dict))
    if isinstance(challenge, dict):
        values.append(str(challenge.get("cha_name") or challenge.get("title") or ""))
    return _string_list(values)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item.get("name") or item.get("tag_name") or "") if isinstance(item, dict) else str(item or "")
        if text.strip() and text.strip() not in result:
            result.append(text.strip())
    return result[:40]


def _normalized_stats(raw: Any, aliases: dict[str, str | tuple[str, ...]]) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    values: dict[str, int] = {}
    for name, aliases_for_value in aliases.items():
        keys = (aliases_for_value,) if isinstance(aliases_for_value, str) else aliases_for_value
        value = next((parsed for key in keys if (parsed := _as_int(source.get(key))) is not None and parsed >= 0), None)
        if value is not None:
            values[name] = value
    return values


def _collection_name_from_payload(payload: dict[str, Any]) -> str:
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    meta = root.get("meta") if isinstance(root.get("meta"), dict) else {}
    for value in (meta.get("name"), meta.get("title"), root.get("season_name"), root.get("title")):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _duration_from_bilibili(row: dict[str, Any]) -> float | None:
    raw = row.get("length") or row.get("duration")
    if isinstance(raw, str) and ":" in raw:
        try:
            seconds = 0
            for part in raw.split(":"):
                seconds = seconds * 60 + int(part)
            return float(seconds)
        except ValueError:
            return None
    return _as_float(raw)


def _as_float(value: Any, *, scale: float = 1) -> float | None:
    try:
        return float(value) / scale if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_iso(value: Any) -> str | None:
    timestamp = _as_int(value)
    if timestamp is None or timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _parse_cutoff(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CreatorSyncError("起始日期格式无效") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _fallback_creator_name(provider: str, creator_key: str) -> str:
    prefix = "抖音创作者" if provider == "douyin" else "B站创作者"
    return f"{prefix} {creator_key[-8:]}"


def _delete_unqueued_items(item_ids) -> None:
    ids = list(item_ids)
    if not ids:
        return
    initialize_database()
    with connect() as connection:
        for item_id in ids:
            connection.execute("DELETE FROM content_items WHERE id=?", (item_id,))
        connection.commit()


def _recoverable_creator_items(
    connection,
    *,
    source_id: str,
    limit: int,
):
    """Return failed items belonging to exactly one creator subscription."""
    if limit <= 0:
        return []
    return connection.execute(
        """
        SELECT content_items.id, content_items.canonical_source_id, content_items.source_url,
               content_items.title, content_items.status
        FROM content_items
        JOIN creator_source_items
          ON creator_source_items.content_item_id = content_items.id
        WHERE creator_source_items.source_id=?
          AND content_items.status='failed'
          AND content_items.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM tasks
              WHERE tasks.content_item_id = content_items.id
                AND tasks.status IN ('queued', 'running', 'paused')
          )
        ORDER BY COALESCE(content_items.published_at, content_items.created_at) DESC
        LIMIT ?
        """,
        (source_id, limit),
    ).fetchall()


def _restore_recovered_item_statuses(items) -> None:
    statuses = list(items)
    if not statuses:
        return
    initialize_database()
    with connect() as connection:
        for item_id, status in statuses:
            connection.execute(
                "UPDATE content_items SET status=?, updated_at=? WHERE id=?",
                (status, utc_now_iso(), item_id),
            )
        connection.commit()
