from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Any, Literal

from config import settings
from services.content_index import ensure_creator_folder
from services.creator_capture_status import creator_capture_status, record_creator_list_check as _record_creator_list_check
from services.creator_metadata import save_creator_work_metadata
from services.creator_sync_models import CreatorPreview, CreatorSyncError, CreatorSyncResult, CreatorVideo
from services.creator_sync_policy import (
    creator_error_category as _creator_error_category,
    creator_retry_minutes as _creator_retry_minutes,
    effective_processing_mode as _effective_processing_mode,
    valid_interval as _valid_interval,
    valid_queue_limit as _valid_queue_limit,
)
from services.creator_source_registry import (
    creator_source_item_ids as _creator_source_item_ids,
    delete_creator_source,
    due_creator_source_ids,
    get_creator_source,
    list_creator_sync_runs,
    list_creator_sources,
    record_sync_error as _record_sync_error,
    record_sync_success as _record_sync_success,
    source_identity as _source_identity,
    source_row as _source_row,
    update_creator_source,
)
from services.creator_source_urls import (
    PERSONAL_SOURCE_KINDS as _PERSONAL_SOURCE_KINDS,
    canonical_creator_url as _canonical_creator_url,
    creator_capture_url as _creator_capture_url,
    parse_creator_url as _parse_creator_url,
)
from services.creator_remote_payloads import (
    as_int as _as_int,
    bilibili_video as _bilibili_video,
    collection_name_from_payload as _collection_name_from_payload,
    douyin_video as _douyin_video,
    parse_creator_page as _parse_page,
)
from services.creator_browser_capture import (
    capture_creator_browser_pages,
    next_bilibili_favorites_page_url as _next_bilibili_favorites_page_url,
)
from services.creator_sync_selection import (
    MAX_CREATOR_CAPTURE_RESPONSE_PAGES,
    append_new_videos as _append_new_videos,
    latest_published_at as _latest_published_at,
    parse_cutoff as _parse_cutoff,
    preview_within_date_range as _preview_within_date_range,
    selected_preview_videos as _selected_preview_videos,
    should_continue_creator_capture as _should_continue_creator_capture,
    unseen_prefix_before_known_item as _unseen_prefix_before_known_item,
)
from services.database import connect, initialize_database, utc_now_iso
from services.pipeline_runner import PipelineRequest
from services.repository import ContentRepository, new_id
from services.task_manager import task_manager


MAX_CREATOR_SCAN_ITEMS = 500
PAGE_SIZE = 20
DEFAULT_CREATOR_QUEUE_LIMIT = 1
# Only the first subscription has a user-visible discovery breadth. Scheduled
# checks scan back from the newest item until they reach an item already linked
# to this source; this is deliberately not a user-configurable cap.
DEFAULT_CREATOR_SYNC_SCAN_ITEMS = 1
_CREATOR_SYNC_LOCK = Lock()


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
    if provider == "xiaohongshu":
        from services.xiaohongshu_capability import require_xiaohongshu_collector

        require_xiaohongshu_collector()
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


def sync_saved_creator_source(
    source_id: str,
    *,
    retry_existing_items: bool = False,
    execution_mode: Literal["foreground", "background"] = "foreground",
) -> CreatorSyncResult:
    source = get_creator_source(source_id)
    if source.get("provider") == "xiaohongshu":
        from services.xiaohongshu_capability import require_xiaohongshu_collector

        require_xiaohongshu_collector()
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
    source_ids = due_creator_source_ids(utc_now_iso())
    from services.task_manager import task_manager
    from services.xiaohongshu_capability import xiaohongshu_collector_capability

    completed: list[str] = []
    for source_id in source_ids:
        try:
            source = get_creator_source(source_id)
            if source.get("provider") == "xiaohongshu" and not xiaohongshu_collector_capability()["available"]:
                continue
            task_manager.create_source_sync(
                {"kind": "creator_saved", "source_id": source_id},
                source_title="自动检查创作者",
                execution_mode="background",
            )
        except Exception:
            continue
        completed.append(source_id)
    return completed


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
    return capture_creator_browser_pages(
        source_url=source_url,
        response_matcher=response_matcher,
        payload_matcher=payload_matcher,
        limit=limit,
        provider=provider,
        stop_at=stop_at,
        known_item_ids=known_item_ids,
        should_continue=_should_continue_creator_capture,
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
