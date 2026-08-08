from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import sqlite3

from services.article_fetcher import (
    ArticleFetchResult,
    enrich_cached_article_image_ocr,
    fetch_article,
    parse_wechat_article_html,
)
from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.cache import (
    cache_dir_for_url,
    read_cache_meta,
    read_cached_subtitle_transcript,
    read_cached_transcript,
    write_cache_meta,
)
from services.database import connect, ensure_database_initialized
from services.markdown_sync import get_markdown_state
from services.repository import ContentItemRecord, ContentRepository
from services.search_index import upsert_source_text_document
from services.paddle_ocr import is_paddle_ocr_configured
from services.published_at import PUBLISHED_AT_PARSER_VERSION
from services.knowledge_library import materialize_source_document
from services.xiaohongshu_cache import xiaohongshu_cache_dir


logger = logging.getLogger(__name__)
SUPPORTED_ARTICLE_PROVIDERS = {"wechat", "campus", "rss"}
_INTERRUPTED_ARTICLE_PREPARATION_PREFIX = "cannot schedule new futures after"


@dataclass(frozen=True)
class ContentSourceText:
    """The source material that can be sent to the AI for a content item."""

    content_item_id: str
    title: str
    source_url: str
    text: str
    source_kind: str
    fetched_now: bool = False


@dataclass(frozen=True)
class ContentTextReadiness:
    """A cache-only description of whether a content item can be asked about."""

    status: str
    label: str
    detail: str
    source_kind: str | None
    can_ask_ai: bool
    retryable: bool = False


def load_content_source_text(
    content_item_id: str,
    *,
    refresh: bool = False,
    include_image_ocr: bool = True,
) -> ContentSourceText:
    """Load reusable source text without starting the full analysis pipeline.

    Article text is fetched and cached lazily because it does not require
    an AI call. Video content deliberately only uses existing subtitle/ASR cache:
    a manual question must never silently re-download or transcribe a video.
    """
    ensure_database_initialized()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)

    source_url = str(item.source_url or "").strip()
    if _is_local_markdown_document(item):
        source = _load_local_markdown_document(item)
    elif _is_forum_capture_document(item):
        source = _load_forum_capture_document(item)
    elif _is_generated_report(item):
        source = _load_generated_report(item)
    elif not source_url:
        raise ValueError("该内容缺少来源链接，无法取得可分析正文")
    elif _is_forum_post(item):
        source = _load_forum_post(item)
    elif _is_rss_article(item):
        source = _load_article(
            item.id,
            item.title,
            source_url,
            cache_dir_for_url(source_url),
            platform="rss",
            refresh=refresh,
            include_image_ocr=include_image_ocr,
        )
    elif item.source_provider == "xiaohongshu" and item.content_type == "article":
        source = _load_xiaohongshu_article(item)
    else:
        cache_dir = cache_dir_for_url(source_url)
        if _is_supported_article(item):
            source = _load_article(
                item.id,
                item.title,
                source_url,
                cache_dir,
                platform=item.source_provider,
                refresh=refresh,
                include_image_ocr=include_image_ocr,
            )
        else:
            source = _load_video_transcript(item.id, item.title, source_url, cache_dir)
    _index_source_text(source)
    # Markdown is the durable source record.  This is a local filesystem write
    # only; loading text still returns the same material to avoid changing the
    # existing analysis/report pipeline in this storage migration.
    # A generated report already *is* its canonical Markdown document. Routing
    # it through the generic source-document template would overwrite the
    # report body on first Q&A, so reports are indexed but never rematerialized.
    if not _is_generated_report(item) and not _is_local_markdown_document(item):
        try:
            materialize_source_document(item, source)
        except OSError:
            logger.warning("Unable to materialize Markdown source document for %s", item.id, exc_info=True)
    # Cross-document indexing is now owned by the explicit V2 knowledge-set
    # builder.  Opening a source must not recreate the retired whole-document
    # index, nor make a newly collected article queryable before its complete
    # structural/FTS/vector pipeline has finished.
    return source


def inspect_content_text_readiness(item: ContentItemRecord) -> ContentTextReadiness:
    """Inspect local metadata only; this must not make network or AI calls."""
    if _is_local_markdown_document(item):
        return _local_markdown_document_readiness(item.id)
    if _is_forum_capture_document(item):
        return _forum_capture_document_readiness(item.id)
    if _is_generated_report(item):
        return _generated_report_readiness(item.id)
    source_url = str(item.source_url or "").strip()
    if not source_url:
        return ContentTextReadiness(
            status="unavailable",
            label="缺少来源链接",
            detail="没有来源链接，无法取得可供 AI 分析的文本。",
            source_kind=None,
            can_ask_ai=False,
        )

    cache_dir = (
        xiaohongshu_cache_dir(source_url)
        if item.source_provider == "xiaohongshu" and item.content_type == "article"
        else cache_dir_for_url(source_url)
    )
    cache_meta = read_cache_meta(cache_dir)
    if _is_forum_post(item):
        return _forum_post_readiness(item.id)
    if item.source_provider == "xiaohongshu" and item.content_type == "article":
        info = _mapping(cache_meta.get("article_info"))
        text = str(info.get("body_text") or "").strip()
        return ContentTextReadiness(
            status="ready" if text else "pending",
            label="正文已就绪" if text else "等待图文采集",
            detail="小红书图文正文与图片文字已本机缓存。" if text else "正在读取小红书图文与图片。",
            source_kind="article" if text else None,
            can_ask_ai=bool(text),
            retryable=not bool(text),
        )
    if _is_supported_article(item):
        return _article_text_readiness(cache_meta)
    return _video_text_readiness(cache_dir, cache_meta)


def _load_xiaohongshu_article(item: ContentItemRecord) -> ContentSourceText:
    from services.xiaohongshu_ingest import refresh_xiaohongshu_ocr

    info = refresh_xiaohongshu_ocr(item)
    text = str(info.get("body_text") or "").strip()
    if not text:
        raise ValueError("小红书图文尚未采集完成")
    return ContentSourceText(
        content_item_id=item.id,
        title=str(info.get("title") or item.title or "小红书图文"),
        source_url=str(item.source_url or ""),
        text=text,
        source_kind="article",
        fetched_now=False,
    )


def cache_preloaded_wechat_article(
    content_item_id: str,
    source_url: str,
    page_html: str,
    *,
    fallback_title: str = "",
) -> dict:
    """Persist a verified WeChat response as the article's local snapshot."""
    cache_dir = cache_dir_for_url(source_url)
    existing = _mapping(read_cache_meta(cache_dir).get("article_info"))
    if str(existing.get("body_text") or "").strip():
        return existing
    article = parse_wechat_article_html(
        source_url,
        page_html,
        content_item_id=content_item_id,
        include_image_ocr=False,
    )
    article_info = _article_info_from_fetch_result(
        article,
        platform="wechat",
        fallback_title=fallback_title,
    )
    _write_article_snapshot(cache_dir, source_url, "wechat", article_info)
    _sync_fetched_article_metadata(content_item_id, article_info)
    return article_info


def _load_article(
    content_item_id: str,
    item_title: str,
    source_url: str,
    cache_dir: Path,
    *,
    platform: str,
    refresh: bool,
    include_image_ocr: bool,
) -> ContentSourceText:
    article_info = _mapping(read_cache_meta(cache_dir).get("article_info"))
    body_text = str(article_info.get("body_text") or "").strip()
    fetched_now = False

    captured_platform = str(article_info.get("platform") or platform).strip()
    needs_ocr_refresh = captured_platform in SUPPORTED_ARTICLE_PROVIDERS and _article_needs_ocr_refresh(article_info)
    needs_rss_full_text = platform == "rss" and _rss_full_text_pending(content_item_id, article_info)
    needs_procurement_pdf_refresh = platform == "campus" and _is_legacy_procurement_placeholder(body_text)
    needs_document_ocr_refresh = platform == "campus" and _document_ocr_needs_refresh(article_info)
    if body_text and needs_ocr_refresh and include_image_ocr and not refresh:
        article_info = _enrich_cached_article_ocr(
            content_item_id,
            item_title,
            source_url,
            cache_dir,
            article_info,
        )
        body_text = str(article_info.get("body_text") or "").strip()
    elif (
        not body_text
        or refresh
        or (include_image_ocr and needs_ocr_refresh)
        or needs_procurement_pdf_refresh
        or needs_document_ocr_refresh
        or needs_rss_full_text
    ):
        try:
            article = fetch_article(
                source_url,
                platform,
                content_item_id=content_item_id,
                include_image_ocr=include_image_ocr,
            )
        except Exception as exc:
            updates = {
                "article_capture": {
                    "last_attempt_at": _utc_now_iso(),
                    "last_error": str(exc),
                }
            }
            if platform == "rss" and body_text:
                # A feed summary remains useful when the linked page is
                # paywalled, deleted, or blocks automated access. Keep it and
                # avoid retrying the same failing page on every open.
                updates["article_info"] = {**article_info, "rss_full_text_status": "failed"}
                write_cache_meta(cache_dir, updates)
            else:
                write_cache_meta(cache_dir, updates)
                raise
        else:
            article_info = _article_info_from_fetch_result(
                article,
                platform=platform,
                fallback_title=item_title,
                previous_article_info=article_info,
            )
            _write_article_snapshot(cache_dir, source_url, platform, article_info)
            _sync_fetched_article_metadata(content_item_id, article_info)
            body_text = str(article_info.get("body_text") or "").strip()
            fetched_now = True

    if not body_text:
        raise ValueError("文章正文为空，暂时无法进行 AI 分析")

    return ContentSourceText(
        content_item_id=content_item_id,
        title=str(article_info.get("title") or item_title or "未命名文章"),
        source_url=source_url,
        text=body_text,
        source_kind="article",
        fetched_now=fetched_now,
    )


def _article_info_from_fetch_result(
    article: ArticleFetchResult,
    *,
    platform: str,
    fallback_title: str = "",
    previous_article_info: dict | None = None,
) -> dict:
    # Some WeChat text-share pages carry their complete body in
    # ``window.title`` rather than a real title. Retain the known list title
    # instead of replacing it with the parser's generic marker.
    resolved_title = article.title
    if resolved_title == "未命名公众号文章":
        resolved_title = fallback_title or resolved_title
    previous = previous_article_info or {}
    return {
        "title": resolved_title,
        "platform": article.platform,
        "author": article.author,
        "published_at": article.published_at,
        "published_at_parser_version": PUBLISHED_AT_PARSER_VERSION,
        "body_text": article.body_text,
        "body_html": article.body_html,
        "normalized_html": normalize_article_html(article.body_html),
        "normalized_html_version": ARTICLE_NORMALIZER_VERSION,
        "images": article.images,
        "image_ocr": article.image_ocr,
        "document_ocr": article.document_ocr,
        "document_markdown": article.document_markdown,
        "attachments": article.attachments,
        **({
            "rss_body_source": "web_full",
            "rss_full_text_status": "fetched",
            "rss_feed_summary": str(previous.get("rss_feed_summary") or ""),
        } if platform == "rss" else {}),
    }


def _write_article_snapshot(cache_dir: Path, source_url: str, platform: str, article_info: dict) -> None:
    write_cache_meta(
        cache_dir,
        {
            "source_url": source_url,
            "platform": platform,
            "cache_key": cache_dir.name,
            "article_info": article_info,
            "article_capture": {
                "last_attempt_at": _utc_now_iso(),
                "last_error": "",
            },
        },
    )


def _enrich_cached_article_ocr(
    content_item_id: str,
    item_title: str,
    source_url: str,
    cache_dir: Path,
    article_info: dict,
) -> dict:
    """OCR a captured snapshot without re-fetching its source page."""
    body_html = str(article_info.get("body_html") or "").strip()
    if not body_html:
        return article_info
    body_text, enriched_html, images, image_ocr = enrich_cached_article_image_ocr(
        body_html,
        article_url=source_url,
        content_item_id=content_item_id,
    )
    if not body_text:
        raise ValueError("文章正文为空，暂时无法进行 AI 分析")
    enriched = {
        **article_info,
        "title": str(article_info.get("title") or item_title or "未命名文章"),
        "body_text": body_text,
        "body_html": enriched_html,
        "normalized_html": normalize_article_html(enriched_html),
        "normalized_html_version": ARTICLE_NORMALIZER_VERSION,
        "images": images,
        "image_ocr": image_ocr,
    }
    write_cache_meta(
        cache_dir,
        {
            "source_url": source_url,
            "cache_key": cache_dir.name,
            "article_info": enriched,
            "article_capture": {
                "last_attempt_at": _utc_now_iso(),
                "last_error": "",
            },
        },
    )
    return enriched


def _sync_fetched_article_metadata(content_item_id: str, article_info: dict) -> None:
    """Replace incomplete list-page metadata with authoritative detail-page values."""
    fetched_title = str(article_info.get("title") or "").strip()
    fetched_published_at = str(article_info.get("published_at") or "").strip()
    if not fetched_title and not fetched_published_at:
        return

    try:
        with connect() as connection:
            repository = ContentRepository(connection)
            current = repository.get_content_item(content_item_id)
            repository.update_source_metadata(
                content_item_id,
                title=fetched_title or current.title,
                published_at=fetched_published_at or current.published_at,
                source_name=current.source_name,
                source_section=current.source_section,
            )
            connection.commit()
    except (LookupError, OSError, sqlite3.Error) as exc:
        # The fetched capture is still usable even if a concurrent deletion or
        # a short-lived database failure prevents this metadata refinement.
        logger.warning("Unable to update fetched article metadata for %s: %s", content_item_id, exc)


def _article_needs_ocr_refresh(article_info: dict) -> bool:
    """Backfill article captures made before image OCR was enabled locally."""
    if not is_paddle_ocr_configured():
        return False
    images = article_info.get("images")
    if not isinstance(images, list) or not images:
        return False
    image_ocr = article_info.get("image_ocr")
    if not isinstance(image_ocr, dict) or not bool(image_ocr.get("attempted")):
        return True
    if int(image_ocr.get("pending_count") or 0) > 0:
        return True
    # Versions before the cloud-only policy could mark a Chinese table or
    # poster as "text_below_threshold" using macOS Vision Fast. Those images
    # were never sent to PaddleOCR, so refresh the snapshot once.
    local_filter_counts = image_ocr.get("local_filter_counts")
    if isinstance(local_filter_counts, dict):
        try:
            if int(local_filter_counts.get("text_below_threshold") or 0) > 0:
                return True
        except (TypeError, ValueError):
            pass
    # A previous all-failed capture contains no OCR material and must not be
    # treated as permanently complete. The next explicit content load retries
    # it after the application has been updated or the provider has recovered.
    return (
        int(image_ocr.get("recognized_count") or 0) == 0
        and int(image_ocr.get("failed_count") or 0) > 0
        and not str(image_ocr.get("attempted_at") or "").strip()
    )


def _is_legacy_procurement_placeholder(body_text: str) -> bool:
    """Refresh the short CMS-only capture after PDF detail support lands."""
    return "正文暂未由该公开接口返回，请通过原始链接查看。" in str(body_text or "")


def _document_ocr_needs_refresh(article_info: dict) -> bool:
    metadata = _mapping(article_info.get("document_ocr"))
    if not is_paddle_ocr_configured() or not metadata:
        return False
    if not bool(metadata.get("attempted")):
        return True
    # Captures made before document Markdown was retained cannot preserve the
    # OCR model's heading and list boundaries in the reader. Refresh them once
    # through the existing OCR cache/pipeline.
    return str(metadata.get("status") or "") == "succeeded" and not str(article_info.get("document_markdown") or "").strip()


def _wechat_article_needs_ocr_refresh(article_info: dict) -> bool:
    """Backward-compatible name for callers that only handled WeChat before."""
    return _article_needs_ocr_refresh(article_info)


def _load_video_transcript(
    content_item_id: str,
    item_title: str,
    source_url: str,
    cache_dir: Path,
) -> ContentSourceText:
    transcript = read_cached_subtitle_transcript(cache_dir)
    if not transcript:
        transcript = _read_cached_asr_transcript(cache_dir)
    if not transcript:
        raise ValueError("尚未获得可供 AI 分析的字幕或转写文本；请先完成字幕获取或转写")

    cache_meta = read_cache_meta(cache_dir)
    video_info = _mapping(cache_meta.get("video_info"))
    return ContentSourceText(
        content_item_id=content_item_id,
        title=str(video_info.get("title") or item_title or "未命名视频"),
        source_url=source_url,
        text=transcript,
        source_kind="video",
    )


def _load_forum_post(item: ContentItemRecord) -> ContentSourceText:
    ensure_database_initialized()
    with connect() as connection:
        post = connection.execute(
            "SELECT id, body_text FROM forum_posts WHERE content_item_id = ?",
            (item.id,),
        ).fetchone()
        comments = (
            connection.execute(
                """
                SELECT author_label, display_time, body_text
                FROM forum_comments
                WHERE post_id = ?
                ORDER BY first_seen_at, id
                """,
                (post["id"],),
            ).fetchall()
            if post
            else []
        )
    if not post or not str(post["body_text"] or "").strip():
        raise ValueError("该论坛帖子尚未识别出可分析的正文")
    parts = [str(post["body_text"]).strip()]
    if comments:
        parts.extend(["", "评论："])
        for comment in comments:
            prefix = " · ".join(
                value
                for value in (
                    str(comment["author_label"] or ""),
                    str(comment["display_time"] or ""),
                )
                if value
            )
            body = str(comment["body_text"] or "").strip()
            if body:
                parts.append(f"- {prefix + '：' if prefix else ''}{body}")
    return ContentSourceText(
        content_item_id=item.id,
        title=item.title or "校园论坛帖子",
        source_url=str(item.source_url or ""),
        text="\n".join(parts).strip(),
        source_kind="forum_post",
    )


def _load_forum_capture_document(item: ContentItemRecord) -> ContentSourceText:
    markdown = get_markdown_state(item.id).markdown.strip()
    if "<!-- post-id:" not in markdown:
        raise ValueError("该次小程序采集文档尚未采到帖子")
    return ContentSourceText(
        content_item_id=item.id,
        title=item.title or "猹话会采集",
        source_url="",
        text=markdown,
        source_kind="forum_capture",
    )


def _load_local_markdown_document(item: ContentItemRecord) -> ContentSourceText:
    """Use any imported local document's Markdown as the durable AI source."""
    try:
        markdown = get_markdown_state(item.id).markdown.strip()
    except (LookupError, OSError, ValueError) as exc:
        raise ValueError("该外部导入资料暂不可用") from exc
    if not markdown:
        raise ValueError("该外部导入资料暂无可用正文，暂时无法进行 AI 分析")
    return ContentSourceText(
        content_item_id=item.id,
        title=item.title or "未命名外部资料",
        source_url=item.source_url or f"local-file:{item.id}",
        text=markdown,
        source_kind="local_document",
    )


def _load_generated_report(item: ContentItemRecord) -> ContentSourceText:
    """Use the canonical report Markdown as the Q&A source material.

    Reports intentionally have no external source URL: their durable source is
    the local Markdown document created by the reporting pipeline.  Exclude
    previous Q&A records so a new question is grounded in the report itself,
    rather than recursively reading earlier answers.
    """
    try:
        markdown = get_markdown_state(item.id).markdown
    except (LookupError, OSError, ValueError) as exc:
        raise ValueError("该报告的 Markdown 文档暂不可用") from exc
    text = _report_body_from_markdown(markdown)
    if not text:
        raise ValueError("该报告内容为空，暂时无法进行 AI 追问")
    return ContentSourceText(
        content_item_id=item.id,
        title=item.title or "未命名报告",
        source_url="",
        text=text,
        source_kind="report",
    )


def _report_body_from_markdown(markdown: str) -> str:
    text = str(markdown or "").strip()
    text = re.sub(r"\A---\s*\n[\s\S]*?\n---\s*\n?", "", text, count=1)
    text = re.sub(r"\n## 追问记录\s*$[\s\S]*\Z", "", text, flags=re.MULTILINE)
    return text.strip()


def _read_cached_asr_transcript(cache_dir: Path) -> str | None:
    transcript_metadata = read_cache_meta(cache_dir).get("transcripts") or {}
    metadata_models = transcript_metadata.keys() if isinstance(transcript_metadata, dict) else []
    candidate_models = list(reversed(list(metadata_models)))
    candidate_models.extend(
        path.name.removeprefix("transcript_").removesuffix(".txt")
        for path in sorted(cache_dir.glob("transcript_*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
        if path.name != "transcript_subtitle.txt"
    )

    seen: set[str] = set()
    for model_name in candidate_models:
        if not model_name or model_name == "subtitle" or model_name in seen:
            continue
        seen.add(model_name)
        transcript = read_cached_transcript(cache_dir, model_name)
        if transcript:
            return transcript
    return None


def _index_source_text(source: ContentSourceText) -> None:
    """Make locally available source text searchable without blocking AI use."""
    try:
        upsert_source_text_document(
            content_key=source.content_item_id,
            title=source.title,
            transcript=source.text,
        )
    except Exception:
        logger.warning(
            "Unable to update source-text search index for content item %s",
            source.content_item_id,
            exc_info=True,
        )


def _article_text_readiness(cache_meta: dict) -> ContentTextReadiness:
    article_info = _mapping(cache_meta.get("article_info"))
    body_text = str(article_info.get("body_text") or "").strip()
    if article_info.get("rss_body_source") == "feed_summary" and article_info.get("rss_full_text_status") == "pending":
        return ContentTextReadiness(
            status="needs_fetch",
            label="正文待补全",
            detail="RSS 仅提供摘要，正在读取原文链接；暂时仍可使用摘要。",
            source_kind="article",
            can_ask_ai=True,
            retryable=True,
        )
    if article_info.get("rss_body_source") == "feed_summary" and article_info.get("rss_full_text_status") == "failed":
        return ContentTextReadiness(
            status="ready",
            label="仅 RSS 摘要",
            detail="原文链接暂时不可获取，当前保留 RSS 提供的摘要。",
            source_kind="article",
            can_ask_ai=True,
            retryable=True,
        )
    if _is_legacy_procurement_placeholder(body_text):
        return ContentTextReadiness(
            status="needs_fetch",
            label="正文待更新",
            detail="这条采购公告保存的是旧版占位内容；可重新获取 PDF 正文。",
            source_kind="article",
            can_ask_ai=True,
            retryable=True,
        )
    if _document_ocr_needs_refresh(article_info):
        return ContentTextReadiness(
            status="needs_fetch",
            label="正文待优化",
            detail="这条采购公告使用了旧版 OCR 缓存；重新读取后会保留标题、列表和表格结构。",
            source_kind="article",
            can_ask_ai=True,
            retryable=True,
        )
    if body_text:
        return ContentTextReadiness(
            status="ready",
            label="正文已就绪",
            detail="已缓存完整正文，可直接在右侧提问。",
            source_kind="article",
            can_ask_ai=True,
        )

    capture = cache_meta.get("article_capture") or {}
    last_error = str(capture.get("last_error") or "").strip() if isinstance(capture, dict) else ""
    if not last_error:
        last_error = str(cache_meta.get("pipeline_error") or "").strip()
    if last_error:
        return ContentTextReadiness(
            status="unavailable",
            label="正文暂不可用",
            detail=last_error,
            source_kind="article",
            can_ask_ai=False,
            retryable=True,
        )
    return ContentTextReadiness(
        status="needs_fetch",
        label="正文待获取",
        detail="打开文章或在右侧提问时会抓取正文，不会调用 AI。",
        source_kind="article",
        can_ask_ai=True,
        retryable=True,
    )


def should_resume_article_preparation(readiness: ContentTextReadiness) -> bool:
    """Return whether startup may safely resume a previously queued article.

    Fresh captures can always be resumed.  For captured failures, restrict the
    automatic recovery path to the known executor-shutdown residue left by an
    application restart.  Other failures stay available for an explicit user
    retry, but are not retried on every startup when a link was deleted,
    expired, or otherwise unavailable upstream.
    """
    if readiness.status == "needs_fetch":
        return True
    return (
        readiness.status == "unavailable"
        and readiness.retryable
        and _INTERRUPTED_ARTICLE_PREPARATION_PREFIX in readiness.detail.lower()
        and "shutdown" in readiness.detail.lower()
    )


def should_prepare_article_in_background(item: ContentItemRecord) -> bool:
    """Return whether an article still needs snapshot capture or OCR enrichment."""
    readiness = inspect_content_text_readiness(item)
    if should_resume_article_preparation(readiness):
        return True
    if readiness.status != "ready" or not _is_supported_article(item):
        return False
    cache_meta = read_cache_meta(cache_dir_for_url(str(item.source_url or "").strip()))
    return _article_needs_ocr_refresh(_mapping(cache_meta.get("article_info")))


def _is_supported_article(item: ContentItemRecord) -> bool:
    return item.content_type == "article" and item.source_provider in SUPPORTED_ARTICLE_PROVIDERS


def _is_rss_article(item: ContentItemRecord) -> bool:
    return item.content_type == "article" and item.source_provider == "rss"


def _rss_full_text_pending(content_item_id: str, article_info: dict) -> bool:
    if article_info.get("rss_body_source") == "feed_summary":
        return article_info.get("rss_full_text_status") == "pending"
    # Existing installations did not record whether feed body was full text.
    # Recover summary-only cached entries when their stored feed summary and
    # displayed body are materially the same, without refetching known-full
    # entries just because they predate this feature.
    if article_info.get("rss_body_source"):
        return False
    body_text = _rss_comparable_text(article_info.get("body_text"))
    if not body_text:
        return False
    try:
        with connect() as connection:
            row = connection.execute(
                "SELECT source_summary FROM rss_source_items WHERE content_item_id=?",
                (content_item_id,),
            ).fetchone()
    except sqlite3.Error:
        return False
    return bool(row and _rss_comparable_text(row["source_summary"]) == body_text)


def _rss_comparable_text(value: object) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", str(value or "")).split())


def _is_forum_post(item: ContentItemRecord) -> bool:
    return item.content_type == "forum_post" and item.source_provider == "wechat_miniprogram"


def _is_forum_capture_document(item: ContentItemRecord) -> bool:
    # ``report`` is retained here only for historical records that have not
    # yet passed the startup repair. Capture batches are source documents,
    # never generated reports.
    return item.content_type in {"forum_capture", "report"} and item.source_provider == "wechat_miniprogram"


def _is_local_markdown_document(item: ContentItemRecord) -> bool:
    return item.source_provider in {"local_markdown", "local_file"} and item.content_type in {"document", "image"}


def _is_generated_report(item: ContentItemRecord) -> bool:
    return item.content_type == "report" and item.source_provider == "wechat_report"


def _generated_report_readiness(content_item_id: str) -> ContentTextReadiness:
    try:
        text = _report_body_from_markdown(get_markdown_state(content_item_id).markdown)
    except (LookupError, OSError, ValueError):
        text = ""
    if text:
        return ContentTextReadiness(
            status="ready",
            label="报告已就绪",
            detail="日报、周报或区间报告已保存，可直接在右侧提问。",
            source_kind="report",
            can_ask_ai=True,
        )
    return ContentTextReadiness(
        status="unavailable",
        label="报告内容暂不可用",
        detail="报告 Markdown 尚未保存或内容为空，暂时无法进行追问。",
        source_kind="report",
        can_ask_ai=False,
    )


def _local_markdown_document_readiness(content_item_id: str) -> ContentTextReadiness:
    try:
        markdown = get_markdown_state(content_item_id).markdown.strip()
    except (LookupError, OSError, ValueError):
        markdown = ""
    if markdown:
        return ContentTextReadiness(
            status="ready",
            label="外部资料已就绪",
            detail="已导入并生成资料 Markdown，可直接在右侧提问。",
            source_kind="local_document",
            can_ask_ai=True,
        )
    return ContentTextReadiness(
        status="unavailable",
        label="外部资料正在准备",
        detail="正在读取、转写或识别原始文件；正文就绪后即可在右侧提问。",
        source_kind="local_document",
        can_ask_ai=False,
    )


def _forum_capture_document_readiness(content_item_id: str) -> ContentTextReadiness:
    try:
        markdown = get_markdown_state(content_item_id).markdown.strip()
    except (LookupError, OSError, ValueError):
        markdown = ""
    if "<!-- post-id:" in markdown:
        return ContentTextReadiness(
            status="ready",
            label="采集文档已就绪",
            detail="本轮帖子和评论已写入文件树文档，可直接分析。",
            source_kind="forum_capture",
            can_ask_ai=True,
        )
    return ContentTextReadiness(
        status="pending",
        label="等待采集内容",
        detail="采到首篇帖子后会自动写入该文档。",
        source_kind="forum_capture",
        can_ask_ai=False,
    )


def _forum_post_readiness(content_item_id: str) -> ContentTextReadiness:
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            "SELECT body_text, capture_complete FROM forum_posts WHERE content_item_id = ?",
            (content_item_id,),
        ).fetchone()
    if row and str(row["body_text"] or "").strip():
        complete = bool(row["capture_complete"])
        return ContentTextReadiness(
            status="ready",
            label="帖子已采集" if complete else "帖子正文可用",
            detail="正文和评论已保存，可直接分析。" if complete else "正文已保存；评论可能仍在补采。",
            source_kind="forum_post",
            can_ask_ai=True,
            retryable=False,
        )
    return ContentTextReadiness(
        status="unavailable",
        label="帖子识别未完成",
        detail="保留了原始截图，但暂未识别出可分析正文。",
        source_kind="forum_post",
        can_ask_ai=False,
        retryable=False,
    )


def _video_text_readiness(cache_dir: Path, cache_meta: dict) -> ContentTextReadiness:
    if read_cached_subtitle_transcript(cache_dir):
        return ContentTextReadiness(
            status="ready",
            label="字幕已就绪",
            detail="已缓存字幕，可直接在右侧提问。",
            source_kind="subtitle",
            can_ask_ai=True,
        )
    if _read_cached_asr_transcript(cache_dir):
        return ContentTextReadiness(
            status="ready",
            label="转写已就绪",
            detail="已缓存转写文本，可直接在右侧提问。",
            source_kind="transcript",
            can_ask_ai=True,
        )

    pipeline_error = str(cache_meta.get("pipeline_error") or "").strip()
    if pipeline_error:
        return ContentTextReadiness(
            status="unavailable",
            label="缺少字幕或转写",
            detail=pipeline_error,
            source_kind=None,
            can_ask_ai=False,
        )
    return ContentTextReadiness(
        status="pending",
        label="等待字幕或转写",
        detail="完成字幕获取或视频转写后，即可在右侧进行手动分析。",
        source_kind=None,
        can_ask_ai=False,
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}
