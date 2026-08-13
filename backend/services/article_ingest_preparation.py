"""Prepare article snapshots quickly, then enrich their images with OCR."""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from services.cache import cache_dir_for_url, read_cache_meta
from services.content_source_text import (
    load_content_source_text,
    should_prepare_article_in_background,
)
from services.database import connect, initialize_database
from services.paddle_ocr import is_paddle_ocr_configured
from services.repository import ContentRepository
from services.wechat_browser import next_wechat_public_request_in_seconds

logger = logging.getLogger(__name__)

# A readable HTML snapshot is the product's first priority.  OCR has its own
# global image-level cap in paddle_ocr, so article-level workers can wait for it
# without preventing unrelated webpages from entering the local cache.
_WEB_CAPTURE_WORKERS = 8
_WECHAT_CAPTURE_WORKERS = 1
_OCR_WORKERS = 4


def _new_executors() -> tuple[ThreadPoolExecutor, ThreadPoolExecutor, ThreadPoolExecutor]:
    return (
        ThreadPoolExecutor(max_workers=_WEB_CAPTURE_WORKERS, thread_name_prefix="article-web-capture"),
        ThreadPoolExecutor(max_workers=_WECHAT_CAPTURE_WORKERS, thread_name_prefix="article-wechat-capture"),
        ThreadPoolExecutor(max_workers=_OCR_WORKERS, thread_name_prefix="article-ocr-enrich"),
    )


_web_capture_executor, _wechat_capture_executor, _ocr_executor = _new_executors()
_executor_lock = Lock()
_accepting_work = True

_pending_ids: set[str] = set()
_web_capture_queued_ids: deque[str] = deque()
_wechat_capture_queued_ids: deque[str] = deque()
_ocr_queued_ids: deque[str] = deque()
_pending_lock = Lock()
_active_web_capture_ids: set[str] = set()
_active_wechat_capture_ids: set[str] = set()
_active_ocr_ids: set[str] = set()
_priority_ocr_ids: set[str] = set()
_completed_count = 0
_failed_count = 0


def enqueue_article_source_preparation(content_item_id: str) -> bool:
    """Queue a fast local body capture followed by optional image OCR."""
    if not content_item_id:
        return False
    with _executor_lock:
        if not _accepting_work:
            return False
    is_wechat = _is_wechat_article(content_item_id)
    queue = _wechat_capture_queued_ids if is_wechat else _web_capture_queued_ids
    with _executor_lock:
        if not _accepting_work:
            return False
        executor = _wechat_capture_executor if is_wechat else _web_capture_executor
    with _pending_lock:
        if content_item_id in _pending_ids:
            return False
        _pending_ids.add(content_item_id)
        queue.append(content_item_id)
    try:
        executor.submit(_capture, content_item_id, is_wechat=is_wechat)
    except Exception:
        with _pending_lock:
            _pending_ids.discard(content_item_id)
            _discard(queue, content_item_id)
        with _executor_lock:
            stopping = not _accepting_work
        if stopping:
            return False
        raise
    return True


def _capture(content_item_id: str, *, is_wechat: bool) -> None:
    queue = _wechat_capture_queued_ids if is_wechat else _web_capture_queued_ids
    active = _active_wechat_capture_ids if is_wechat else _active_web_capture_ids
    with _pending_lock:
        _discard(queue, content_item_id)
        active.add(content_item_id)
    try:
        # A historical backfill or a duplicate event can sit in the in-memory
        # queue while another path finishes the snapshot.  Re-check durable
        # readiness immediately before doing any network work so completed
        # articles do not keep the status bar in a perpetual “processing”.
        if not _preparation_is_still_required(content_item_id):
            _finish(content_item_id, succeeded=True)
            return
        load_content_source_text(content_item_id, include_image_ocr=False)
    except Exception:
        _finish(content_item_id, succeeded=False)
        logger.info("Article body capture failed for %s", content_item_id, exc_info=True)
        return
    finally:
        with _pending_lock:
            active.discard(content_item_id)

    with _executor_lock:
        if not _accepting_work:
            _finish(content_item_id, succeeded=True)
            return
        executor = _ocr_executor
    with _pending_lock:
        if content_item_id in _priority_ocr_ids:
            _ocr_queued_ids.appendleft(content_item_id)
        else:
            _ocr_queued_ids.append(content_item_id)
    try:
        executor.submit(_enrich_ocr, content_item_id)
    except Exception:
        with _pending_lock:
            _discard(_ocr_queued_ids, content_item_id)
        _finish(content_item_id, succeeded=False)
        logger.info("Article OCR enrichment could not be scheduled for %s", content_item_id, exc_info=True)


def start_article_source_preparation() -> None:
    """Accept background preparation work for the current app lifecycle."""
    global _web_capture_executor, _wechat_capture_executor, _ocr_executor, _accepting_work
    with _executor_lock:
        if _accepting_work:
            return
        _web_capture_executor, _wechat_capture_executor, _ocr_executor = _new_executors()
        _accepting_work = True


def shutdown_article_source_preparation(*, wait: bool = True) -> None:
    """Stop accepting work and close every preparation executor idempotently."""
    global _accepting_work
    with _executor_lock:
        if not _accepting_work:
            return
        _accepting_work = False
        executors = (_web_capture_executor, _wechat_capture_executor, _ocr_executor)
    with _pending_lock:
        _pending_ids.clear()
        _web_capture_queued_ids.clear()
        _wechat_capture_queued_ids.clear()
        _ocr_queued_ids.clear()
        _priority_ocr_ids.clear()
    for executor in executors:
        executor.shutdown(wait=wait, cancel_futures=True)


def _enrich_ocr(content_item_id: str) -> None:
    with _pending_lock:
        _discard(_ocr_queued_ids, content_item_id)
        _active_ocr_ids.add(content_item_id)
    succeeded = False
    try:
        # The body capture or a direct preview request may have completed OCR
        # before this worker gets a slot.  Treat that stale task as completed
        # without parsing the article a second time.
        if not _preparation_is_still_required(content_item_id):
            succeeded = True
            return
        # Cached bodies that have no meaningful images return immediately.
        # When OCR is configured, this enriches the existing HTML snapshot
        # rather than downloading the source page again.
        load_content_source_text(content_item_id, include_image_ocr=True)
        succeeded = True
    except Exception:
        logger.info("Article image OCR enrichment failed for %s", content_item_id, exc_info=True)
    finally:
        with _pending_lock:
            _active_ocr_ids.discard(content_item_id)
        _finish(content_item_id, succeeded=succeeded)


def _finish(content_item_id: str, *, succeeded: bool) -> None:
    global _completed_count, _failed_count
    with _pending_lock:
        _pending_ids.discard(content_item_id)
        _priority_ocr_ids.discard(content_item_id)
        if succeeded:
            _completed_count += 1
        else:
            _failed_count += 1
    if succeeded:
        try:
            from services.completion_notifications import record_content_ready
            record_content_ready(content_item_id, after_analysis=False)
        except Exception:
            logger.info("Could not record article-ready notification", exc_info=True)


def _preparation_is_still_required(content_item_id: str) -> bool:
    """Return whether a queued article still needs local capture or OCR.

    Missing metadata is left to the normal worker path so the job records an
    ordinary failure instead of silently hiding a storage error.  This also
    keeps the low-level worker usable in isolated tests.
    """
    item = _article_item(content_item_id)
    return item is None or should_prepare_article_in_background(item)


def _is_wechat_article(content_item_id: str) -> bool:
    try:
        with connect() as connection:
            item = ContentRepository(connection).get_content_item(content_item_id)
        return item.source_provider == "wechat"
    except Exception:
        # If its metadata disappears concurrently, the following capture will
        # report the ordinary per-item failure without blocking the queue.
        return False


def _discard(queue: deque[str], content_item_id: str) -> None:
    try:
        queue.remove(content_item_id)
    except ValueError:
        pass


def prioritize_article_image_ocr(content_item_id: str) -> dict[str, object]:
    """Move one article's capture/OCR work to the front without duplicating it."""
    status = article_image_ocr_status(content_item_id)
    if status["status"] in {"completed", "not_applicable", "not_configured", "unavailable"}:
        return status

    enqueue_needed = False
    with _pending_lock:
        _priority_ocr_ids.add(content_item_id)
        if content_item_id in _ocr_queued_ids:
            _discard(_ocr_queued_ids, content_item_id)
            _ocr_queued_ids.appendleft(content_item_id)
        elif content_item_id in _web_capture_queued_ids:
            _discard(_web_capture_queued_ids, content_item_id)
            _web_capture_queued_ids.appendleft(content_item_id)
        elif content_item_id in _wechat_capture_queued_ids:
            _discard(_wechat_capture_queued_ids, content_item_id)
            _wechat_capture_queued_ids.appendleft(content_item_id)
        elif content_item_id not in _pending_ids:
            # ``enqueue`` performs repository access and must not run under
            # this lock.  Marking priority first makes its newly queued OCR
            # phase jump ahead once the local snapshot is available.
            enqueue_needed = True
        else:
            enqueue_needed = False
    if enqueue_needed:
        enqueue_article_source_preparation(content_item_id)
        with _pending_lock:
            _move_capture_to_front(content_item_id)
    return article_image_ocr_status(content_item_id)


def _move_capture_to_front(content_item_id: str) -> None:
    for queue in (_web_capture_queued_ids, _wechat_capture_queued_ids):
        if content_item_id in queue:
            _discard(queue, content_item_id)
            queue.appendleft(content_item_id)
            return


def article_image_ocr_status(content_item_id: str) -> dict[str, object]:
    """Describe OCR readiness for one article using only local state/cache."""
    item = _article_item(content_item_id)
    if item is None or item.content_type != "article" or item.source_provider not in {"wechat", "campus", "rss"}:
        return {"status": "unavailable", "has_images": False, "priority": False}
    source_url = str(item.source_url or "").strip()
    article_info = read_cache_meta(cache_dir_for_url(source_url)).get("article_info") if source_url else {}
    article_info = article_info if isinstance(article_info, dict) else {}
    images = article_info.get("images")
    image_ocr = article_info.get("image_ocr")
    image_ocr = image_ocr if isinstance(image_ocr, dict) else {}
    has_images = bool(images) if isinstance(images, list) else bool(image_ocr.get("image_count"))
    # Captures made before cloud-only OCR can claim completion even though the
    # old local Vision prefilter skipped a real content image. Surface these as
    # pending so one explicit priority request can repair the snapshot.
    local_filter_counts = image_ocr.get("local_filter_counts")
    try:
        legacy_local_skip = isinstance(local_filter_counts, dict) and int(
            local_filter_counts.get("text_below_threshold") or 0
        ) > 0
    except (TypeError, ValueError):
        legacy_local_skip = False
    ocr_completed = (
        bool(image_ocr.get("attempted"))
        and not legacy_local_skip
        and int(image_ocr.get("pending_count") or 0) == 0
    )
    with _pending_lock:
        priority = content_item_id in _priority_ocr_ids
        capture_active = content_item_id in _active_web_capture_ids or content_item_id in _active_wechat_capture_ids
        capture_queued = content_item_id in _web_capture_queued_ids or content_item_id in _wechat_capture_queued_ids
        ocr_active = content_item_id in _active_ocr_ids
        ocr_queued = content_item_id in _ocr_queued_ids
        # A previous OCR attempt may have completed while a duplicate task was
        # still waiting in memory. The durable cache is
        # authoritative: drop the no-op task so the UI cannot remain stuck in
        # “parsing” and the worker is not wasted later.
        if ocr_completed and has_images and not ocr_active and ocr_queued:
            _discard(_ocr_queued_ids, content_item_id)
            ocr_queued = False
            if not capture_active and not capture_queued:
                _pending_ids.discard(content_item_id)
                _priority_ocr_ids.discard(content_item_id)
                priority = False
    if ocr_completed and has_images and not ocr_active:
        status = "completed"
    elif ocr_active:
        status = "running"
    elif ocr_queued:
        status = "queued"
    elif capture_active:
        status = "capturing"
    elif capture_queued or not article_info:
        status = "capture_pending"
    elif not has_images:
        status = "not_applicable"
    elif not is_paddle_ocr_configured():
        status = "not_configured"
    else:
        status = "pending"
    return {
        "status": status,
        "has_images": has_images,
        "priority": priority,
        "recognized_count": int(image_ocr.get("recognized_count") or 0),
        "image_count": int(image_ocr.get("image_count") or len(images or [])),
    }


def _article_item(content_item_id: str):
    if not content_item_id:
        return None
    try:
        with connect() as connection:
            return ContentRepository(connection).get_content_item(content_item_id)
    except (LookupError, OSError, sqlite3.Error):
        return None


def article_source_preparation_status() -> dict[str, int | str | float]:
    """Return independent body-capture and OCR queue progress for the UI."""
    with _pending_lock:
        web_capture_active = len(_active_web_capture_ids)
        wechat_capture_active = len(_active_wechat_capture_ids)
        capture_active = web_capture_active + wechat_capture_active
        ocr_active = len(_active_ocr_ids)
        web_capture_queued = len(_web_capture_queued_ids)
        wechat_capture_queued = len(_wechat_capture_queued_ids)
        capture_queued = web_capture_queued + wechat_capture_queued
        ocr_queued = len(_ocr_queued_ids)
        return {
            "active_content_item_id": next(iter(_active_web_capture_ids | _active_wechat_capture_ids | _active_ocr_ids), ""),
            "active_count": capture_active + ocr_active,
            "queued_count": capture_queued + ocr_queued,
            "pending_count": len(_pending_ids),
            "capture_active_count": capture_active,
            "capture_queued_count": capture_queued,
            "web_capture_active_count": web_capture_active,
            "web_capture_queued_count": web_capture_queued,
            "wechat_capture_active_count": wechat_capture_active,
            "wechat_capture_queued_count": wechat_capture_queued,
            "ocr_active_count": ocr_active,
            "ocr_queued_count": ocr_queued,
            "completed_count": _completed_count,
            "failed_count": _failed_count,
            "next_wechat_slot_in_seconds": next_wechat_public_request_in_seconds(),
        }


def enqueue_pending_article_preparation(*, limit: int = 1000) -> int:
    """Resume incomplete local snapshots and OCR after an application restart."""
    initialize_database()
    with connect() as connection:
        items = ContentRepository(connection).list_content_items(limit=max(1, limit))
    queued = 0
    for item in items:
        if item.content_type != "article" or item.source_provider not in {"wechat", "campus", "rss"}:
            continue
        if not should_prepare_article_in_background(item):
            continue
        if enqueue_article_source_preparation(item.id):
            queued += 1
    return queued
