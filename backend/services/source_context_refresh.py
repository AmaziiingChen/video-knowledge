from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services.bilibili_context import fetch_bilibili_source_context
from services.cache import read_cache_meta
from services.content_source_text import ContentSourceText, load_content_source_text
from services.database import connect, ensure_database_initialized
from services.douyin_context import fetch_douyin_source_context
from services.knowledge_library import (
    materialize_source_document,
    update_source_context_section,
)
from services.repository import ContentItemRecord, ContentRepository
from services.search_index import upsert_source_context_document
from services.source_context import build_source_context
from services.source_context_store import (
    SUPPORTED_SOURCE_CONTEXT_PROVIDERS,
    mark_source_context_failed,
    mark_source_context_running,
    sanitize_source_context_error,
    save_source_context,
    source_context_cache_dir,
)
from services.xiaohongshu_client import fetch_note


ProgressCallback = Callable[[str, float, str], None]
CancelCheck = Callable[[], bool]


def refresh_source_context(
    content_item_id: str,
    *,
    comment_limit: int = 60,
    comment_pages: int = 3,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    ensure_database_initialized()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    _validate_item(item)
    if item.source_provider == "xiaohongshu":
        from services.xiaohongshu_capability import require_xiaohongshu_collector

        require_xiaohongshu_collector()
    _check_cancel(cancel_check)
    mark_source_context_running(item)
    _report(on_progress, "source_context", 20, "正在读取互动指标")
    try:
        if item.source_provider == "bilibili":
            context = fetch_bilibili_source_context(
                str(item.source_url),
                comment_limit=comment_limit,
                comment_pages=comment_pages,
            )
        elif item.source_provider == "douyin":
            context = fetch_douyin_source_context(
                str(item.source_url),
                comment_limit=comment_limit,
                comment_pages=comment_pages,
            )
        else:
            context = _xiaohongshu_source_context(
                str(item.source_url),
                comment_limit=comment_limit,
                comment_pages=comment_pages,
            )
        _check_cancel(cancel_check)
        record = save_source_context(item, context)
    except Exception as exc:
        mark_source_context_failed(item, exc)
        raise
    _report(
        on_progress,
        "source_context",
        80,
        f"已保存 {record.comment_sample_count} 条评论样本",
    )
    document_updated = _refresh_local_outputs(item, context)
    return {
        "content_item_id": item.id,
        "provider": item.source_provider,
        "status": record.status,
        "comment_sample_count": record.comment_sample_count,
        "comment_total": record.comment_total,
        "comments_complete": record.comments_complete,
        "last_success_at": record.last_success_at,
        "document_updated": document_updated,
    }


def backfill_source_contexts(
    *,
    limit: int = 50,
    include_ready: bool = False,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    bounded_limit = max(1, min(int(limit), 200))
    ensure_database_initialized()
    from services.xiaohongshu_capability import xiaohongshu_collector_capability

    where_ready = "" if include_ready else "AND (context.status IS NULL OR context.status != 'ready')"
    provider_clause = (
        "('bilibili', 'douyin', 'xiaohongshu')"
        if xiaohongshu_collector_capability()["available"]
        else "('bilibili', 'douyin')"
    )
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT content.id
            FROM content_items AS content
            LEFT JOIN content_source_contexts AS context
              ON context.content_item_id = content.id
            WHERE content.deleted_at IS NULL
              AND content.source_url IS NOT NULL
              AND content.source_provider IN {provider_clause}
              {where_ready}
            ORDER BY content.updated_at DESC, content.id
            LIMIT ?
            """,
            (bounded_limit,),
        ).fetchall()
    item_ids = [str(row["id"]) for row in rows]
    summary: dict[str, Any] = {
        "total": len(item_ids),
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "comments_saved": 0,
        "failures": [],
    }
    for index, item_id in enumerate(item_ids, start=1):
        _check_cancel(cancel_check)
        _report(
            on_progress,
            "source_context_backfill",
            5 + (index - 1) / max(1, len(item_ids)) * 90,
            f"正在补采 {index}/{len(item_ids)}",
        )
        try:
            result = refresh_source_context(
                item_id,
                on_progress=None,
                cancel_check=cancel_check,
            )
        except Exception as exc:
            summary["failed"] += 1
            summary["failures"].append(
                {
                    "content_item_id": item_id,
                    "error": _safe_result_error(exc),
                }
            )
        else:
            summary["succeeded"] += 1
            summary["comments_saved"] += int(result.get("comment_sample_count") or 0)
        summary["completed"] += 1
    return summary


def _xiaohongshu_source_context(
    source_url: str,
    *,
    comment_limit: int,
    comment_pages: int,
) -> dict[str, object]:
    note = fetch_note(
        source_url,
        comment_limit=comment_limit,
        comment_pages=comment_pages,
    )
    return build_source_context(
        provider="xiaohongshu",
        author=note.author,
        published_at=note.published_at,
        engagement={
            "like": note.stats.get("liked"),
            "comment": note.stats.get("comment"),
            "collect": note.stats.get("collected"),
            "share": note.stats.get("shared"),
        },
        comments=note.comment_sample,
        comment_total=note.stats.get("comment"),
        comments_complete=note.comments_complete,
        topics=note.tags,
        description=note.description,
    )


def _refresh_local_outputs(
    item: ContentItemRecord,
    context: dict[str, object],
) -> bool:
    document_updated = update_source_context_section(item.id, context)
    try:
        if not document_updated and item.source_provider == "xiaohongshu":
            metadata = read_cache_meta(source_context_cache_dir(item))
            article_info = metadata.get("article_info") if isinstance(metadata.get("article_info"), dict) else {}
            body_text = str(article_info.get("body_text") or "").strip()
            if body_text:
                materialize_source_document(
                    item,
                    ContentSourceText(
                        content_item_id=item.id,
                        title=str(article_info.get("title") or item.title),
                        source_url=str(item.source_url or ""),
                        text=body_text,
                        source_kind="article",
                    ),
                )
                document_updated = update_source_context_section(item.id, context)
        elif not document_updated:
            load_content_source_text(item.id)
            document_updated = update_source_context_section(item.id, context)
    except (LookupError, OSError, ValueError):
        document_updated = False
    upsert_source_context_document(
        content_key=item.id,
        title=item.title,
        source_context=context,
    )
    return document_updated


def _validate_item(item: ContentItemRecord) -> None:
    if item.source_provider not in SUPPORTED_SOURCE_CONTEXT_PROVIDERS or not item.source_url:
        raise ValueError("该内容来源不支持互动数据采集")


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise ValueError("互动数据采集已取消")


def _report(
    callback: ProgressCallback | None,
    stage: str,
    progress: float,
    message: str,
) -> None:
    if callback:
        callback(stage, max(0.0, min(100.0, progress)), message)


def _safe_result_error(error: BaseException) -> str:
    return sanitize_source_context_error(error)[:160]
