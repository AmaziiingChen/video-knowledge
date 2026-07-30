from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from services.cache import cache_dir_for_url, read_cache_meta, write_cache_meta
from services.database import connect, ensure_database_initialized, utc_now_iso
from services.repository import ContentItemRecord, ContentRepository
from services.xiaohongshu_cache import promote_xiaohongshu_cache, xiaohongshu_cache_dir


SUPPORTED_SOURCE_CONTEXT_PROVIDERS = frozenset({"bilibili", "douyin", "xiaohongshu"})


@dataclass(frozen=True)
class SourceContextRecord:
    content_item_id: str
    provider: str
    status: str
    context: dict[str, object]
    comment_sample_count: int
    comment_total: int | None
    comments_complete: bool
    last_attempt_at: str | None
    last_success_at: str | None
    last_error: str
    updated_at: str


def get_source_context_record(content_item_id: str) -> SourceContextRecord | None:
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM content_source_contexts WHERE content_item_id = ?",
            (content_item_id,),
        ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(str(row["context_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        value = {}
    context = value if isinstance(value, dict) else {}
    return SourceContextRecord(
        content_item_id=str(row["content_item_id"]),
        provider=str(row["provider"] or ""),
        status=str(row["status"] or "pending"),
        context=context,
        comment_sample_count=int(row["comment_sample_count"] or 0),
        comment_total=int(row["comment_total"]) if row["comment_total"] is not None else None,
        comments_complete=bool(row["comments_complete"]),
        last_attempt_at=str(row["last_attempt_at"]) if row["last_attempt_at"] else None,
        last_success_at=str(row["last_success_at"]) if row["last_success_at"] else None,
        last_error=str(row["last_error"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


def load_source_context(content_item_id: str) -> dict[str, object]:
    record = get_source_context_record(content_item_id)
    if record and record.context:
        return dict(record.context)
    ensure_database_initialized()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(content_item_id)
        except LookupError:
            return {}
    return _cached_source_context(item)


def mark_source_context_running(item: ContentItemRecord) -> None:
    _validate_item(item)
    now = utc_now_iso()
    ensure_database_initialized()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO content_source_contexts (
                content_item_id, provider, status, context_json,
                comment_sample_count, comment_total, comments_complete,
                last_attempt_at, last_success_at, last_error, created_at, updated_at
            ) VALUES (?, ?, 'running', '{}', 0, NULL, 0, ?, NULL, '', ?, ?)
            ON CONFLICT(content_item_id) DO UPDATE SET
                provider=excluded.provider,
                status='running',
                last_attempt_at=excluded.last_attempt_at,
                last_error='',
                updated_at=excluded.updated_at
            """,
            (item.id, item.source_provider, now, now, now),
        )
        connection.commit()


def save_source_context(item: ContentItemRecord, context: dict[str, object]) -> SourceContextRecord:
    _validate_item(item)
    normalized = dict(context or {})
    now = utc_now_iso()
    sample_count = _non_negative_int(normalized.get("comment_sample_count")) or 0
    comment_total = _non_negative_int(normalized.get("comment_total"))
    comments_complete = bool(normalized.get("comments_complete"))
    ensure_database_initialized()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO content_source_contexts (
                content_item_id, provider, status, context_json,
                comment_sample_count, comment_total, comments_complete,
                last_attempt_at, last_success_at, last_error, created_at, updated_at
            ) VALUES (?, ?, 'ready', ?, ?, ?, ?, ?, ?, '', ?, ?)
            ON CONFLICT(content_item_id) DO UPDATE SET
                provider=excluded.provider,
                status='ready',
                context_json=excluded.context_json,
                comment_sample_count=excluded.comment_sample_count,
                comment_total=excluded.comment_total,
                comments_complete=excluded.comments_complete,
                last_attempt_at=excluded.last_attempt_at,
                last_success_at=excluded.last_success_at,
                last_error='',
                updated_at=excluded.updated_at
            """,
            (
                item.id,
                item.source_provider,
                json.dumps(normalized, ensure_ascii=False),
                sample_count,
                comment_total,
                int(comments_complete),
                now,
                now,
                now,
                now,
            ),
        )
        connection.commit()
    _write_context_cache(item, normalized, status="ready", error="")
    record = get_source_context_record(item.id)
    if record is None:
        raise RuntimeError("互动数据保存失败")
    return record


def mark_source_context_failed(item: ContentItemRecord, error: BaseException | str) -> SourceContextRecord:
    _validate_item(item)
    now = utc_now_iso()
    safe_error = sanitize_source_context_error(error)
    ensure_database_initialized()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO content_source_contexts (
                content_item_id, provider, status, context_json,
                comment_sample_count, comment_total, comments_complete,
                last_attempt_at, last_success_at, last_error, created_at, updated_at
            ) VALUES (?, ?, 'failed', '{}', 0, NULL, 0, ?, NULL, ?, ?, ?)
            ON CONFLICT(content_item_id) DO UPDATE SET
                provider=excluded.provider,
                status='failed',
                last_attempt_at=excluded.last_attempt_at,
                last_error=excluded.last_error,
                updated_at=excluded.updated_at
            """,
            (item.id, item.source_provider, now, safe_error, now, now),
        )
        connection.commit()
    _write_context_cache(item, None, status="failed", error=safe_error)
    record = get_source_context_record(item.id)
    if record is None:
        raise RuntimeError("互动数据失败状态保存失败")
    return record


def source_context_cache_dir(item: ContentItemRecord) -> Path:
    source_url = str(item.source_url or "")
    if item.source_provider == "xiaohongshu":
        return xiaohongshu_cache_dir(source_url)
    return cache_dir_for_url(source_url)


def _cached_source_context(item: ContentItemRecord) -> dict[str, object]:
    metadata = read_cache_meta(source_context_cache_dir(item))
    value = metadata.get("source_context")
    if not isinstance(value, dict):
        article_info = metadata.get("article_info") if isinstance(metadata.get("article_info"), dict) else {}
        value = article_info.get("source_context")
    if not isinstance(value, dict):
        video_info = metadata.get("video_info") if isinstance(metadata.get("video_info"), dict) else {}
        value = video_info.get("source_context")
    return dict(value) if isinstance(value, dict) else {}


def _write_context_cache(
    item: ContentItemRecord,
    context: dict[str, object] | None,
    *,
    status: str,
    error: str,
) -> None:
    source_url = str(item.source_url or "")
    cache_dir = (
        promote_xiaohongshu_cache(source_url)
        if item.source_provider == "xiaohongshu"
        else cache_dir_for_url(source_url)
    )
    metadata = read_cache_meta(cache_dir)
    now = utc_now_iso()
    capture = dict(metadata.get("source_context_capture") or {})
    capture.update(
        {
            "status": status,
            "last_attempt_at": now,
            "last_error": error,
        }
    )
    updates: dict[str, object] = {"source_context_capture": capture}
    if context is not None:
        capture["last_success_at"] = now
        updates["source_context"] = context
        if item.source_provider == "xiaohongshu":
            article_info = dict(metadata.get("article_info") or {})
            if article_info:
                article_info["source_context"] = context
                updates["article_info"] = article_info
    write_cache_meta(cache_dir, updates)


def _validate_item(item: ContentItemRecord) -> None:
    if item.source_provider not in SUPPORTED_SOURCE_CONTEXT_PROVIDERS or not item.source_url:
        raise ValueError("该内容来源不支持互动数据采集")


def sanitize_source_context_error(error: BaseException | str) -> str:
    text = " ".join(str(error or "互动数据采集失败").split())
    text = re.sub(
        r"(?i)((?:xsec_token|cookie|authorization|token)=)[^&\s]+",
        r"\1[已隐藏]",
        text,
    )
    return text[:300] or "互动数据采集失败"


def _non_negative_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
