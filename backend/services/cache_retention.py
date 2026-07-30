from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread

from config import settings
from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.cache import directory_size, read_cache_meta, write_cache_meta
from services.database import connect, initialize_database


logger = logging.getLogger(__name__)
DEFAULT_RETENTION_DAYS = 14
RETENTION_CHECK_INTERVAL_SECONDS = 6 * 60 * 60
RETENTION_INITIAL_DELAY_SECONDS = 60


@dataclass(frozen=True)
class CachePruneResult:
    scanned: int = 0
    pruned: int = 0
    freed_bytes: int = 0


def prune_stale_cache(
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
) -> CachePruneResult:
    """Remove large artifacts while retaining a compact, readable document."""
    initialize_database()
    retention_days = max(1, retention_days if retention_days is not None else settings.video_cache_retention_days)
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=retention_days)
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT item.source_url, item.created_at
            FROM content_items AS item
            WHERE item.source_url IS NOT NULL
              AND TRIM(item.source_url) <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM tasks
                  WHERE tasks.content_item_id = item.id
                    AND tasks.status IN ('queued', 'running', 'paused')
              )
            """
        ).fetchall()

    created_by_url = {
        str(row["source_url"]): _parse_timestamp(str(row["created_at"] or ""))
        for row in rows
    }
    cache_root = settings.data_dir / "cache"
    if not cache_root.exists():
        return CachePruneResult()

    scanned = 0
    pruned = 0
    freed_bytes = 0
    for cache_dir in cache_root.iterdir():
        if not cache_dir.is_dir():
            continue
        scanned += 1
        meta = read_cache_meta(cache_dir)
        created_at = created_by_url.get(str(meta.get("source_url") or ""))
        video_expires_at = _parse_timestamp(str(meta.get("video_cache_expires_at") or ""))
        due_for_prune = video_expires_at <= current_time if video_expires_at else bool(created_at and created_at <= cutoff)
        if not due_for_prune:
            continue
        before = directory_size(cache_dir)
        _prune_cache_directory(cache_dir, meta=meta, retention_days=retention_days)
        after = directory_size(cache_dir)
        if after < before:
            pruned += 1
            freed_bytes += before - after

    return CachePruneResult(scanned=scanned, pruned=pruned, freed_bytes=freed_bytes)


def _prune_cache_directory(cache_dir: Path, *, meta: dict, retention_days: int) -> None:
    had_video = any(path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".flv"} for path in cache_dir.iterdir())
    article_info = meta.get("article_info")
    if isinstance(article_info, dict):
        compact_article = dict(article_info)
        body_html = str(compact_article.get("body_html") or "").strip()
        normalized_html = str(compact_article.get("normalized_html") or "").strip()
        normalized_version = _parse_integer(compact_article.get("normalized_html_version"))
        if body_html and normalized_version != ARTICLE_NORMALIZER_VERSION:
            normalized_html = body_html
        compact_article["normalized_html"] = normalize_article_html(
            normalized_html,
            preserve_local_media=False,
        )
        compact_article["normalized_html_version"] = ARTICLE_NORMALIZER_VERSION
        compact_article["body_html"] = ""
        compact_article.pop("raw_body_html", None)
        compact_article["images"] = []
        image_ocr = compact_article.get("image_ocr")
        if isinstance(image_ocr, dict):
            compact_article["image_ocr"] = {**image_ocr, "cached_image_count": 0}
        meta_update = {
            "article_info": compact_article,
            "retention_pruned_at": datetime.now(timezone.utc).isoformat(),
            "retention_policy": f"large-assets-after-{retention_days}-days",
        }
    else:
        meta_update = {
            "retention_pruned_at": datetime.now(timezone.utc).isoformat(),
            "retention_policy": f"large-assets-after-{retention_days}-days",
        }

    if had_video:
        meta_update.update({
            "video_cache_status": "expired",
            "video_cache_expired_at": datetime.now(timezone.utc).isoformat(),
        })

    for path in list(cache_dir.iterdir()):
        if _preserve_cache_asset(path):
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    write_cache_meta(cache_dir, meta_update)


def _preserve_cache_asset(path: Path) -> bool:
    if path.name == "metadata.json":
        return True
    return path.is_file() and path.name.startswith("transcript_") and path.suffix in {".txt", ".json"}


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CacheRetentionScheduler:
    def __init__(self) -> None:
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, name="cache-retention", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self) -> None:
        # Let startup indexing and the first library paint finish before any
        # cache directory can be compacted in the background.
        if self._stop_event.wait(RETENTION_INITIAL_DELAY_SECONDS):
            return
        while not self._stop_event.is_set():
            try:
                result = prune_stale_cache()
                if result.pruned:
                    logger.info(
                        "Pruned %s stale cache entries and freed %s bytes",
                        result.pruned,
                        result.freed_bytes,
                    )
            except Exception:
                logger.exception("Automatic cache retention failed")
            self._stop_event.wait(RETENTION_CHECK_INTERVAL_SECONDS)


cache_retention_scheduler = CacheRetentionScheduler()
