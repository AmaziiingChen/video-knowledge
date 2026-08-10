"""Prepare already-persisted articles for the summary pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.content_source_text import ContentSourceText, load_content_source_text
from services.database import connect
from services.repository import ContentItemRecord, ContentRepository
from services.source_context_store import save_source_context

SUPPORTED_STORED_ARTICLE_PROVIDERS = {"campus", "rss", "xiaohongshu"}
PROVIDER_LABELS = {
    "campus": "校园官网",
    "rss": "RSS",
    "xiaohongshu": "小红书",
}


class StoredArticlePreparationError(RuntimeError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


@dataclass(frozen=True)
class PreparedStoredArticle:
    item: ContentItemRecord
    transcript: str
    source_context: dict[str, Any]


def _load_and_repair_item(content_item_id: str) -> tuple[ContentItemRecord | None, bool]:
    with connect() as connection:
        try:
            repository = ContentRepository(connection)
            item = repository.get_content_item(content_item_id)
        except LookupError:
            return None, False
        if item.source_provider == "xiaohongshu" and item.content_type != "article":
            item = repository.update_content_type(item.id, "article")
            connection.commit()
            return item, True
        return item, False


def _reload_item(content_item_id: str) -> ContentItemRecord | None:
    with connect() as connection:
        try:
            return ContentRepository(connection).get_content_item(content_item_id)
        except LookupError:
            return None


def _capture_xiaohongshu_note(content_item_id: str) -> dict[str, Any]:
    from services.xiaohongshu_ingest import capture_xiaohongshu_note

    return capture_xiaohongshu_note(content_item_id)


def prepare_stored_article(
    content_item_id: str | None,
    *,
    add_log: Callable[..., None],
    load_and_repair_item: Callable[[str], tuple[ContentItemRecord | None, bool]] = _load_and_repair_item,
    reload_item: Callable[[str], ContentItemRecord | None] = _reload_item,
    capture_xiaohongshu: Callable[[str], dict[str, Any]] = _capture_xiaohongshu_note,
    load_source: Callable[[str], ContentSourceText] = load_content_source_text,
    persist_source_context: Callable[[ContentItemRecord, dict[str, Any]], None] = save_source_context,
) -> PreparedStoredArticle | None:
    """Return a ready stored article, or ``None`` for media/unknown items."""
    if not content_item_id:
        return None

    item, repaired_legacy_type = load_and_repair_item(content_item_id)
    if item is None:
        return None

    if repaired_legacy_type:
        add_log("parse", "已修复旧小红书图文类型，正在按图文采集…")

    source_context: dict[str, Any] = {}
    if item.content_type == "article" and item.source_provider == "xiaohongshu":
        add_log("parse", "正在读取小红书图文与图片…")
        try:
            captured = capture_xiaohongshu(item.id)
            source_context = dict(captured.get("source_context") or {})
        except Exception as exc:
            raise StoredArticlePreparationError("info", f"小红书图文采集失败：{exc}") from exc
        if source_context:
            try:
                persist_source_context(item, source_context)
            except Exception as exc:  # noqa: BLE001 - enrichment persistence is non-fatal
                add_log("info", f"互动数据持久化失败，继续使用图文正文：{exc}", "warn")
        captured_item_id = item.id
        item = reload_item(captured_item_id)
        if item is None:
            # Match the repository's existing deletion-race contract instead
            # of silently turning an invariant breach into a normal provider
            # failure.
            raise LookupError(f"content item not found: {captured_item_id}")
        add_log("info", "图文素材已缓存，正在整理图片文字", "success")

    if item.content_type != "article" or item.source_provider not in SUPPORTED_STORED_ARTICLE_PROVIDERS:
        return None

    add_log("parse", f"读取已入库的{PROVIDER_LABELS[item.source_provider]}文章", "success")
    try:
        source = load_source(item.id)
    except Exception as exc:
        raise StoredArticlePreparationError("info", f"读取文章正文失败：{exc}") from exc
    transcript = source.text.strip()
    if not transcript:
        raise StoredArticlePreparationError("info", "文章正文为空")
    return PreparedStoredArticle(
        item=item,
        transcript=transcript,
        source_context=source_context,
    )
