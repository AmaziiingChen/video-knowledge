"""Refresh and persist optional social context for a pipeline run."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from services.bilibili_context import fetch_bilibili_source_context
from services.cache import write_cache_meta
from services.database import connect
from services.douyin_context import fetch_douyin_source_context
from services.repository import ContentRepository
from services.source_context import source_context_is_fresh
from services.source_context_store import save_source_context

SourceContext = dict[str, Any]


def refresh_pipeline_source_context(
    *,
    platform: str,
    url: str,
    source_context: SourceContext,
    use_cache: bool,
    cache_dir: Path | None,
    content_item_id: str | None,
    add_log: Callable[[str, str, str], None],
    check_cancel: Callable[[], None],
    fetch_bilibili: Callable[[str], SourceContext] = fetch_bilibili_source_context,
    fetch_douyin: Callable[[str], SourceContext] = fetch_douyin_source_context,
) -> SourceContext:
    """Best-effort refresh, cache and durable storage without blocking summary."""
    fetcher = {
        "bilibili": fetch_bilibili,
        "douyin": fetch_douyin,
    }.get(platform)

    if fetcher is not None and not source_context_is_fresh(source_context):
        check_cancel()
        try:
            source_context = fetcher(url)
            if use_cache and cache_dir:
                write_cache_meta(cache_dir, {"source_context": source_context})
            sample_count = int(source_context.get("comment_sample_count") or 0)
            add_log("info", f"已采集互动指标与 {sample_count} 条评论样本", "success")
        except Exception as exc:  # noqa: BLE001 - provider failures are non-fatal enrichment gaps
            add_log("info", f"互动与评论采集失败，继续使用正文总结：{exc}", "warn")
        check_cancel()
    elif source_context and use_cache and cache_dir:
        write_cache_meta(cache_dir, {"source_context": source_context})

    if source_context and content_item_id:
        try:
            with connect() as connection:
                item = ContentRepository(connection).get_content_item(content_item_id)
            save_source_context(item, source_context)
        except Exception as exc:  # noqa: BLE001 - persistence must not discard the primary summary
            add_log("info", f"互动数据持久化失败，继续生成总结：{exc}", "warn")

    return source_context
