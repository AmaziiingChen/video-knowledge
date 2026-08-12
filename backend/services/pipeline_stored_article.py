"""Prepare already-persisted articles for the summary pipeline."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from services.content_source_text import ContentSourceText, load_content_source_text
from services.database import connect
from services.pipeline_contracts import PipelineCancelled, PipelineResponse, TextSourceInfo
from services.pipeline_progress_rules import elapsed
from services.pipeline_run_reporter import PipelineRunReporter
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


def run_prepared_stored_article(
    prepared: PreparedStoredArticle,
    *,
    response: PipelineResponse,
    reporter: PipelineRunReporter,
    fail: Callable[[str, str], PipelineResponse],
    processing_mode: str,
    api_key_configured: bool,
    ai_model: str | None,
    total_started_at: float,
    summarize_article: Callable[..., tuple[str, str]],
    set_content_status: Callable[[str, str], None],
    set_content_title: Callable[[str, str], None],
    replace_summary: Callable[[str, str], Any],
    update_search: Callable[..., None],
    cancel_check: Callable[[], None] | None = None,
) -> PipelineResponse:
    """Finish transcript-only or summarized processing for a stored article."""
    item = prepared.item
    transcript = prepared.transcript
    source_context = prepared.source_context
    response.url = item.source_url
    response.platform = item.source_provider
    response.transcript = transcript
    response.text_source = TextSourceInfo(
        kind="article",
        source=item.source_provider,
        detail="已入库文章正文",
    )
    reporter.set_many_complete(["parse", "info", "download", "extract_audio", "transcribe"])
    reporter.add_log("info", f"正文已就绪（{len(transcript)} 字）", "success")

    if processing_mode == "transcript":
        reporter.set_many_complete(["summarize", "save"])
        set_content_status(item.id, "to_read")
        response.display_title = item.title
        response.success = True
        response.timings["total"] = elapsed(total_started_at)
        reporter.add_log("save", "正文已保存，未调用 AI 总结", "success")
        response.step = None
        reporter.publish()
        return response

    if not api_key_configured:
        return fail("summarize", "未配置所选文本模型 API Key（请在设置 → AI 服务中填写）")

    summarize_started_at = time.perf_counter()
    reporter.add_log("summarize", "调用所选文本模型生成文章总结...")
    try:
        ai_title, summary = summarize_article(
            transcript,
            item.title,
            model=ai_model,
            task_type="article_summary",
            task_id=response.task_id,
            content_item_id=item.id,
            ai_call_callback=reporter.remember_ai_call("summary"),
            source_context=source_context,
            on_delta=reporter.publish_summary_delta,
            on_reasoning_delta=reporter.publish_reasoning_delta,
            cancel_check=cancel_check,
        )
    except PipelineCancelled:
        raise
    except Exception as exc:  # noqa: BLE001 - provider errors use the pipeline failure contract
        return fail("summarize", str(exc))
    if not summary:
        return fail("summarize", "总结生成失败")

    response.summary = summary
    response.display_title = ai_title or item.title
    reporter.complete_stage("summarize")
    set_content_title(item.id, response.display_title)
    replace_summary(item.id, summary)
    set_content_status(item.id, "to_read")
    try:
        update_search(
            content_key=item.id,
            title=response.display_title,
            summary=summary,
            transcript=transcript,
            source_context=source_context,
        )
    except Exception as exc:  # noqa: BLE001 - search indexing is best effort
        reporter.add_log("save", f"搜索索引更新失败：{exc}", "warn")
    reporter.complete_stage("save")
    response.timings["summarize"] = elapsed(summarize_started_at)
    response.timings["total"] = elapsed(total_started_at)
    response.success = True
    reporter.add_log("save", "文章总结已保存", "success")
    response.step = None
    reporter.publish()
    return response


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
