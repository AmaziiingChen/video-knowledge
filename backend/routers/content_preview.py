"""User-triggered reading previews for locally captured articles."""

from __future__ import annotations

import html
import re
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from services.article_preview import (
    ARTICLE_NORMALIZER_VERSION,
    build_local_article_html,
    build_local_html_source_preview,
)
from services.cache import cache_dir_for_url, read_cache_meta
from services.campus_sources import render_document_markdown_html
from services.content_preview_models import (
    ArticlePreviewResponse,
    is_legacy_document_markdown_preview,
    safe_article_attachments,
    xiaohongshu_description_from_html,
)
from services.content_source_text import (
    inspect_content_text_readiness,
    load_content_source_text,
)
from services.database import connect, initialize_database
from services.document_formatter import request_document_formatting
from services.local_file_imports import (
    extract_html_document,
    import_kind_for_filename,
    imported_html_needs_refresh,
    original_attachment_path,
    save_imported_document,
)
from services.published_at import PUBLISHED_AT_PARSER_VERSION
from services.repository import ContentRepository
from services.xiaohongshu_cache import xiaohongshu_cache_dir
from services.xiaohongshu_ingest import render_xiaohongshu_description_html

router = APIRouter()


@router.get("/content/{item_id}/article-preview", response_model=ArticlePreviewResponse)
def get_article_preview(
    item_id: str,
    request: Request,
):
    """Return the captured article body as safe, locally styled reading HTML."""
    initialize_database()
    with connect() as connection:
        try:
            item = ContentRepository(connection).get_content_item(item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc

    if item.content_type == "forum_post" and item.source_provider == "wechat_miniprogram":
        try:
            source = load_content_source_text(item.id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with connect() as connection:
            post = connection.execute(
                "SELECT author_label, display_time FROM forum_posts WHERE content_item_id = ?",
                (item.id,),
            ).fetchone()
        body_html = "".join(
            f"<p>{html.escape(paragraph)}</p>"
            for paragraph in source.text.splitlines()
            if paragraph.strip()
        )
        return ArticlePreviewResponse(
            content_item_id=item.id,
            title=item.title or "校园论坛帖子",
            author=str(post["author_label"] or "") if post else "",
            published_at=str(post["display_time"] or "") if post else "",
            html=build_local_article_html(body_html, media_base_url=f"{str(request.base_url).rstrip('/')}/api/media"),
            attachments=[],
        )

    if item.source_provider == "local_file" and item.content_type == "document":
        original = original_attachment_path(item.id)
        if not original:
            raise HTTPException(status_code=404, detail="找不到保留的原始 HTML 文件")
        try:
            kind = import_kind_for_filename(original.name.removeprefix("original--"))
            if kind != "html":
                raise HTTPException(status_code=404, detail="该本地文档没有可用的 HTML 预览")
            extraction = extract_html_document(original.read_bytes(), original.name)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=404, detail="读取原始 HTML 文件失败") from exc
        if imported_html_needs_refresh(item.id):
            # Existing imports stored only flattened text. Upgrade the source
            # once on first open, while save_imported_document keeps any AI
            # summary and Q&A sections the user already has.
            save_imported_document(
                item,
                body=extraction.text,
                kind="html",
                original_filename=original.name.removeprefix("original--"),
            )
        media_base_url = f"{str(request.base_url).rstrip('/')}/api/media"
        return ArticlePreviewResponse(
            content_item_id=item.id,
            title=extraction.title or item.title or "未命名 HTML 文档",
            html=build_local_article_html(extraction.body_html, media_base_url=media_base_url),
            source_html=build_local_html_source_preview(
                extraction.raw_html,
                source_url=extraction.source_url,
            ),
        )

    if item.source_provider == "xiaohongshu" and item.content_type == "article" and item.source_url:
        # XHS share URLs carry short-lived xsec tokens. The ingest pipeline
        # promotes each note to its stable note-id cache directory. Reading the
        # legacy full-URL cache here can omit its image gallery.
        article_info = read_cache_meta(xiaohongshu_cache_dir(item.source_url)).get("article_info") or {}
        if not article_info:
            raise HTTPException(status_code=404, detail="小红书图文尚未采集完成")
        media_base_url = f"{str(request.base_url).rstrip('/')}/api/media"
        gallery = []
        for entry in list(article_info.get("xhs_gallery") or []):
            if not isinstance(entry, dict):
                continue
            local_path = str(entry.get("cached_path") or "")
            gallery.append({
                "index": int(entry.get("index") or len(gallery) + 1),
                "url": f"{media_base_url}?path={quote(local_path, safe='')}" if local_path else str(entry.get("source_url") or ""),
                "ocr_status": str(entry.get("ocr_status") or ""),
                "ocr_text": str(entry.get("ocr_text") or ""),
            })
        body_html = str(article_info.get("body_html") or "").strip()
        # Tags belong to the author-written description, never OCR sidecars.
        description = str(article_info.get("description") or xiaohongshu_description_from_html(body_html)).strip()
        body_html = render_xiaohongshu_description_html(description)
        return ArticlePreviewResponse(
            content_item_id=item.id,
            title=str(article_info.get("title") or item.title or "小红书图文"),
            author=str(article_info.get("author") or item.source_name or ""),
            published_at=str(article_info.get("published_at") or item.published_at or ""),
            html=build_local_article_html(body_html or "<p>这篇笔记未提供文字描述。</p>", media_base_url=media_base_url),
            gallery=gallery,
            stats={key: int(value or 0) for key, value in dict(article_info.get("stats") or {}).items()},
            tags=[str(tag) for tag in list(article_info.get("tags") or []) if str(tag).strip()],
        )

    if item.content_type != "article" or item.source_provider not in {"wechat", "campus", "rss"} or not item.source_url:
        raise HTTPException(status_code=404, detail="该内容没有可用的文章预览")

    cache_dir = cache_dir_for_url(item.source_url)
    article_info = read_cache_meta(cache_dir).get("article_info") or {}
    body_html = str(article_info.get("body_html") or "").strip()
    normalized_html = str(article_info.get("normalized_html") or "").strip()
    readiness = inspect_content_text_readiness(item)
    needs_capture = not body_html and not normalized_html
    needs_document_refresh = readiness.label in {"正文待更新", "正文待优化"}
    if needs_capture or needs_document_refresh:
        try:
            # Opening an imported article is a direct user action. Fetching its
            # body here avoids requiring the full AI pipeline first.
            load_content_source_text(item.id)
        except ValueError as exc:
            # Attachment-only notices may have usable HTML even if their text
            # is insufficient for analysis.
            article_info = read_cache_meta(cache_dir).get("article_info") or {}
            has_captured_html = any(
                str(article_info.get(key) or "").strip()
                for key in ("body_html", "normalized_html")
            )
            if not has_captured_html:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        article_info = read_cache_meta(cache_dir).get("article_info") or {}
        body_html = str(article_info.get("body_html") or "").strip()
        normalized_html = str(article_info.get("normalized_html") or "").strip()

    body_text = str(article_info.get("body_text") or "").strip()
    document_markdown = str(article_info.get("document_markdown") or "").strip()
    formatting_status = "not_applicable"
    formatting_detail = ""
    normalized_version = article_info.get("normalized_html_version")
    if document_markdown:
        formatting = request_document_formatting(item.id, item.source_url, document_markdown)
        formatting_status = str(formatting.get("status") or "not_applicable")
        formatting_detail = str(formatting.get("detail") or "")
        preview_markdown = str(formatting.get("formatted_markdown") or document_markdown)
        preview_html = render_document_markdown_html(preview_markdown)
    elif is_legacy_document_markdown_preview(article_info, body_html):
        # Older procurement captures escaped PaddleOCR's Markdown line by
        # line. Re-render without another OCR call.
        preview_html = render_document_markdown_html(body_text)
    elif body_html and normalized_version != ARTICLE_NORMALIZER_VERSION:
        # Old captures are normalized by the renderer on demand. Avoid writing
        # from this GET because OCR or a refresh may update the same metadata.
        preview_html = body_html
    else:
        preview_html = normalized_html or body_html

    if not preview_html:
        if not body_text:
            raise HTTPException(status_code=404, detail="未找到可预览的文章正文")
        preview_html = "".join(
            f"<p>{html.escape(paragraph)}</p>"
            for paragraph in body_text.splitlines()
            if paragraph.strip()
        )

    published_at = str(article_info.get("published_at") or "")
    if (
        item.source_provider == "wechat"
        and article_info.get("published_at_parser_version") != PUBLISHED_AT_PARSER_VERSION
        and re.fullmatch(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", published_at)
    ):
        # Older captures always preferred a hidden epoch timestamp, even though
        # the visible article UI only exposed minute precision.
        published_at = published_at[:16]

    return ArticlePreviewResponse(
        content_item_id=item.id,
        title=str(article_info.get("title") or item.title or "未命名文章"),
        author=str(article_info.get("author") or ""),
        published_at=published_at,
        html=build_local_article_html(
            preview_html,
            media_base_url=f"{str(request.base_url).rstrip('/')}/api/media",
        ),
        attachments=safe_article_attachments(
            article_info.get("attachments"),
            filter_campus_navigation=item.source_provider == "campus",
        ),
        formatting_status=formatting_status,
        formatting_detail=formatting_detail,
    )
