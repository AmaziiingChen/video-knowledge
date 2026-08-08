"""Safe, Markdown-first adapters for files imported from the local machine.

The original file is an attachment.  The generated Markdown is deliberately
the single source used by preview, search and Q&A so local files follow the
same persistence contract as collected videos and articles.
"""

from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag
from PIL import Image, UnidentifiedImageError

from config import settings
from services.article_preview import normalize_article_html
from services.database import connect, initialize_database, utc_now_iso
from services.knowledge_library import attachments_root
from services.markdown_sync import get_markdown_state, save_markdown_draft_and_sync
from services.paddle_ocr import recognize_document_bytes, recognize_local_image
from services.repository import ContentItemRecord, ContentRepository, new_id
from services.search_index import upsert_source_text_document


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".flv", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
DOCUMENT_EXTENSIONS = {".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx"}
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 4 * 1024 * 1024 * 1024
MAX_AUDIO_BYTES = 2 * 1024 * 1024 * 1024
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
HTML_DOCUMENT_EXTRACTOR_VERSION = 3

_HTML_EXPLICIT_CONTENT_SELECTORS = (
    "[id^='vsb_content']",
    ".v_news_content",
    ".news_conent_two_text",
    ".news_content",
    ".news-content",
    ".article-content",
    ".article_content",
    ".content-detail",
    ".detail-content",
)
_HTML_SEMANTIC_CONTENT_SELECTORS = ("article", "main", "[role='main']")
_HTML_CHROME_TOKEN_RE = re.compile(
    r"(?:^|[-_\\s])(?:nav(?:igation)?|menu|header|footer|sidebar|aside|toolbar|breadcrumb|"
    r"pagination|pager|share|comment|advert(?:isement)?|popup|overlay)(?:$|[-_\\s])",
    re.IGNORECASE,
)


class HtmlDocumentExtraction:
    """One HTML import, represented for both reading and AI/search text."""

    def __init__(self, *, title: str, text: str, body_html: str, raw_html: str, source_url: str = "") -> None:
        self.title = title
        self.text = text
        self.body_html = body_html
        self.raw_html = raw_html
        self.source_url = source_url


def safe_import_filename(filename: str) -> str:
    name = Path(filename or "imported-file").name.strip()
    stem = re.sub(r"[^\w\u4e00-\u9fff .-]+", "_", Path(name).stem).strip(" ._")[:100]
    suffix = Path(name).suffix.lower()
    return f"{stem or 'imported-file'}{suffix}"


def import_kind_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".html", ".htm"}:
        return "html"
    if suffix == ".docx":
        return "docx"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    if suffix == ".txt":
        return "text"
    raise ValueError("暂不支持该文件格式")


def validate_import_upload(filename: str, raw: bytes) -> tuple[str, str]:
    safe_name = safe_import_filename(filename)
    kind = import_kind_for_filename(safe_name)
    if not raw:
        raise ValueError("导入文件为空")
    size_limit = MAX_VIDEO_BYTES if kind == "video" else MAX_AUDIO_BYTES if kind == "audio" else MAX_DOCUMENT_BYTES
    if len(raw) > size_limit:
        raise ValueError("视频不能超过 4 GB" if kind == "video" else "音频不能超过 2 GB" if kind == "audio" else "文档不能超过 50 MB")
    return safe_name, kind


def persist_original_attachment(
    *,
    content_item_id: str,
    filename: str,
    raw: bytes,
    mime_type: str,
) -> Path:
    """Store an imported original under the managed attachment root.

    Only a sanitised basename is ever used for the destination.  The database
    row lets storage management distinguish a user-owned original from a
    disposable cache artifact.
    """
    safe_name = safe_import_filename(filename)
    target_dir = attachments_root() / content_item_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original--{safe_name}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(target)
    _record_original_attachment(
        content_item_id=content_item_id,
        target=target,
        mime_type=mime_type,
        size_bytes=len(raw),
    )
    return target


def persist_original_attachment_from_file(
    *,
    content_item_id: str,
    filename: str,
    source: Path,
    mime_type: str,
    size_bytes: int,
) -> Path:
    """Move a staged large upload without materialising it in memory."""
    safe_name = safe_import_filename(filename)
    target_dir = attachments_root() / content_item_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"original--{safe_name}"
    try:
        source.replace(target)
    except OSError:
        shutil.copy2(source, target)
        source.unlink(missing_ok=True)
    _record_original_attachment(
        content_item_id=content_item_id,
        target=target,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
    return target


def _record_original_attachment(*, content_item_id: str, target: Path, mime_type: str, size_bytes: int) -> None:
    initialize_database()
    with connect() as connection:
        connection.execute(
            "DELETE FROM media_assets WHERE content_item_id=? AND asset_type='original_file'",
            (content_item_id,),
        )
        connection.execute(
            """INSERT INTO media_assets
               (id, content_item_id, asset_type, path, mime_type, size_bytes, retention_policy, expires_at, created_at)
               VALUES (?, ?, 'original_file', ?, ?, ?, 'permanent', NULL, ?)""",
            (new_id(), content_item_id, str(target), mime_type, size_bytes, utc_now_iso()),
        )
        connection.commit()


def original_attachment_path(content_item_id: str) -> Path | None:
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """SELECT path FROM media_assets
               WHERE content_item_id=? AND asset_type='original_file'
               ORDER BY created_at DESC LIMIT 1""",
            (content_item_id,),
        ).fetchone()
    path = Path(str(row["path"])) if row and row["path"] else None
    return path if path and path.is_file() else None


def local_file_metadata(path: Path) -> dict[str, object]:
    """Read lightweight, display-safe metadata from a retained original.

    This is intentionally best-effort: a malformed file or a missing ffprobe
    must never prevent a document from being opened.  Reading on demand also
    backfills metadata for files imported before this capability existed.
    """
    try:
        file_path = path.expanduser().resolve()
        size_bytes = int(file_path.stat().st_size)
        kind = import_kind_for_filename(file_path.name.removeprefix("original--"))
    except (OSError, ValueError):
        return {}

    metadata: dict[str, object] = {
        "file_name": file_path.name.removeprefix("original--"),
        "file_format": file_path.suffix.removeprefix(".").upper() or "文件",
        "file_size_bytes": size_bytes,
    }
    if kind == "image":
        try:
            with Image.open(file_path) as image:
                metadata.update({
                    "width": int(image.width),
                    "height": int(image.height),
                    "image_mode": str(image.mode or ""),
                })
        except (OSError, UnidentifiedImageError, ValueError):
            pass
    elif kind == "pdf":
        page_count = _pdf_page_count(file_path)
        if page_count:
            metadata["page_count"] = page_count
    elif kind == "html":
        original_source_url = _original_source_url_from_html_file(file_path)
        if original_source_url:
            metadata["original_source_url"] = original_source_url
    elif kind in {"audio", "video"}:
        metadata.update(_media_file_metadata(file_path, kind))
    return metadata


def _original_source_url_from_html_file(path: Path) -> str | None:
    """Return an absolute source URL embedded by browser HTML exports, if any."""
    try:
        # Browser "Save page" headers and canonical tags both live near the
        # document head.  Bounded reads keep metadata hydration inexpensive.
        source = path.read_bytes()[:512 * 1024].decode("utf-8", errors="replace")
    except OSError:
        return None
    return _original_source_url_from_html(source)


def _original_source_url_from_html(source: str) -> str | None:
    saved = re.search(r"saved\s+from\s+url=\(\d+\)\s*(https?://[^\s>]+)", source, re.IGNORECASE)
    site_builder_article = re.search(r"(https?://[^\"'\s<>]+/info/\d+/\d+\.htm(?:[?#][^\"'\s<>]*)?)", source, re.IGNORECASE)
    candidates = [html.unescape(saved.group(1))] if saved else []
    if site_builder_article:
        candidates.append(html.unescape(site_builder_article.group(1)))
    try:
        soup = BeautifulSoup(source, "lxml")
        canonical = soup.select_one('link[rel~="canonical"][href]')
        og_url = soup.select_one('meta[property="og:url"][content]')
        candidates.extend([
            canonical.get("href", "") if canonical else "",
            og_url.get("content", "") if og_url else "",
        ])
    except Exception:
        # Metadata is advisory and must never block opening an imported file.
        pass
    for candidate in candidates:
        value = str(candidate or "").strip()
        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value
    return None


def _pdf_page_count(path: Path) -> int | None:
    """Return a conservative page count without adding a second PDF stack."""
    try:
        # A page-tree node is `/Pages`; this expression deliberately excludes
        # it and counts only concrete `/Page` objects.
        count = len(re.findall(rb"/Type\s*/Page\b", path.read_bytes()))
    except OSError:
        return None
    return count or None


def _media_file_metadata(path: Path, kind: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration,bit_rate:stream=codec_name,codec_type,width,height,sample_rate,channels",
                "-of", "json", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {}
        payload = json.loads(result.stdout or "{}")
    except (OSError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return {}

    format_info = payload.get("format") if isinstance(payload, dict) else {}
    streams = payload.get("streams") if isinstance(payload, dict) else []
    if not isinstance(format_info, dict) or not isinstance(streams, list):
        return {}
    metadata: dict[str, object] = {}
    duration = _positive_float(format_info.get("duration"))
    if duration is not None:
        metadata["duration_seconds"] = duration
    bit_rate = _positive_int(format_info.get("bit_rate"))
    if bit_rate is not None:
        metadata["bit_rate"] = bit_rate
    video_stream = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"), None)
    if kind == "video" and video_stream:
        width = _positive_int(video_stream.get("width"))
        height = _positive_int(video_stream.get("height"))
        if width and height:
            metadata.update({"width": width, "height": height})
        if video_stream.get("codec_name"):
            metadata["video_codec"] = str(video_stream["codec_name"])
    if audio_stream:
        if audio_stream.get("codec_name"):
            metadata["audio_codec"] = str(audio_stream["codec_name"])
        sample_rate = _positive_int(audio_stream.get("sample_rate"))
        if sample_rate:
            metadata["sample_rate"] = sample_rate
        channels = _positive_int(audio_stream.get("channels"))
        if channels:
            metadata["channels"] = channels
    return metadata


def _positive_float(value: object) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_int(value: object) -> int | None:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def import_markdown_document(
    item: ContentItemRecord,
    *,
    body: str,
    kind: str,
    original_filename: str,
) -> str:
    attachment = ""
    if original_filename:
        attachment = f"## 原始文件\n\n[打开原始文件]({original_filename})\n\n"
    kind_label = {"html": "HTML 文档", "docx": "Word 文档", "pdf": "PDF 文档", "text": "文本文件"}.get(kind, "Markdown 文档")
    extractor_marker = (
        f"<!-- html-extractor:{HTML_DOCUMENT_EXTRACTOR_VERSION} -->\n\n"
        if kind == "html"
        else ""
    )
    return (
        f"# {item.title}\n\n"
        f"> 外部导入 · {kind_label} · 导入于 {item.created_at}\n\n"
        f"{extractor_marker}"
        f"{attachment}"
        f"## 原文内容\n\n{body.strip()}\n\n"
        "## AI 摘要\n\n<!-- 由应用生成；人工编辑内容将被保留。 -->\n\n"
        "## 追问记录\n"
    )


def save_imported_document(item: ContentItemRecord, *, body: str, kind: str, original_filename: str) -> None:
    # The library tree may be nested. Write once to resolve the canonical
    # Markdown location, then replace the attachment placeholder with a path
    # relative to that exact location rather than assuming a fixed depth.
    markdown = import_markdown_document(item, body=body, kind=kind, original_filename="")
    existing_markdown = ""
    try:
        existing_path = get_markdown_state(item.id).markdown_draft_path
        if existing_path and Path(existing_path).is_file():
            existing_markdown = Path(existing_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        # A first import has no canonical Markdown yet.
        pass
    markdown = _preserve_generated_sections(markdown, existing_markdown)
    save_markdown_draft_and_sync(
        markdown=markdown,
        title=item.title,
        obsidian_path=settings.obsidian_vault / "外部导入" / f"{item.id}.md",
        content_item_id=item.id,
    )
    original = original_attachment_path(item.id)
    if original:
        draft_path = Path(get_markdown_state(item.id).markdown_draft_path)
        relative_original = Path(os.path.relpath(original, start=draft_path.parent)).as_posix()
        markdown = import_markdown_document(
            item,
            body=body,
            kind=kind,
            original_filename=relative_original,
        )
        markdown = _preserve_generated_sections(markdown, existing_markdown)
        save_markdown_draft_and_sync(
            markdown=markdown,
            title=item.title,
            obsidian_path=settings.obsidian_vault / "外部导入" / f"{item.id}.md",
            content_item_id=item.id,
        )
    upsert_source_text_document(content_key=item.id, title=item.title, transcript=markdown)


def imported_html_needs_refresh(content_item_id: str) -> bool:
    """Refresh legacy HTML imports once without discarding generated notes."""
    try:
        markdown_path = get_markdown_state(content_item_id).markdown_draft_path
        if not markdown_path:
            return True
        markdown = Path(markdown_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return True
    return f"<!-- html-extractor:{HTML_DOCUMENT_EXTRACTOR_VERSION} -->" not in markdown


def complete_pending_ocr_import(content_item_id: str, *, body: str) -> None:
    """Materialize a retained PDF/image once PaddleOCR finishes asynchronously.

    The provider job may outlive this process, so its completion cannot depend
    on the foreground import task still being alive.  The original attachment
    is already durable; rebuild the same canonical Markdown and status that an
    inline OCR completion would have produced.
    """
    if not body.strip():
        raise ValueError("OCR 未返回可用正文")
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    if item.source_provider != "local_file" or item.content_type not in {"document", "image"}:
        return
    original = original_attachment_path(item.id)
    if not original:
        raise ValueError("原始文件不存在")
    kind = "image" if original.suffix.lower() in IMAGE_EXTENSIONS else "pdf"
    save_imported_document(item, body=body, kind=kind, original_filename=original.name)
    with connect() as connection:
        ContentRepository(connection).update_status(item.id, "to_read")
        connection.commit()


def extract_document_text(raw: bytes, *, filename: str, kind: str) -> tuple[str, str]:
    """Return the derived text and a user-facing title without rendering raw input."""
    if kind == "markdown":
        text = _decode_text(raw, "Markdown")
        return text, _markdown_title(text, filename)
    if kind == "text":
        text = _decode_text(raw, "文本")
        return text, Path(filename).stem
    if kind == "html":
        extraction = extract_html_document(raw, filename)
        return extraction.text, extraction.title
    if kind == "docx":
        return _extract_docx(raw, filename)
    raise ValueError("该文件需要进入后台解析")


def run_document_import(
    *,
    content_item_id: str,
    original_path: str,
    task_id: str,
    on_update: Callable | None = None,
    cancel_check: Callable[[], bool] | None = None,
):
    """Run the existing OCR flow for a retained PDF or image as a durable task."""
    from services.pipeline_runner import PipelineLog, PipelineResponse, classify_pipeline_error

    def cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    response = PipelineResponse(success=False, task_id=task_id, content_item_id=content_item_id, step="extract")

    def publish(message: str, *, level: str = "info", step: str = "extract", progress: float = 0.0) -> None:
        response.step = step
        response.progress[step] = progress
        response.overall_progress = progress
        response.logs.append(PipelineLog(step=step, message=message, level=level, created_at=utc_now_iso()))
        if on_update:
            on_update(response.model_copy(deep=True))

    try:
        path = Path(original_path).resolve()
        allowed_root = attachments_root().resolve()
        path.relative_to(allowed_root)
        if not path.is_file():
            raise ValueError("原始文件不存在")
        if cancelled():
            raise InterruptedError("任务已取消")
        kind = "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "pdf"
        publish(f"正在识别{'图片' if kind == 'image' else 'PDF'}正文…", progress=10)
        result = (
            recognize_local_image(path, content_item_id=content_item_id)
            if kind == "image"
            else recognize_document_bytes(
                path.read_bytes(),
                url=f"local-file:{content_item_id}",
                filename=path.name,
                content_type="application/pdf",
                content_item_id=content_item_id,
            )
        )
        if cancelled():
            raise InterruptedError("任务已取消")
        if result.status == "not_configured":
            raise ValueError(f"尚未配置 PaddleOCR，无法识别{'图片' if kind == 'image' else 'PDF'}")
        if result.status == "pending":
            # Paddle's job id is persisted independently and will be polled
            # after restart. The foreground task only represents submission;
            # do not turn a durable remote job into a false local failure.
            publish("识别任务已提交，后台继续获取结果…", step="wait_for_ocr", progress=30)
            response.success = True
            response.step = None
            response.overall_progress = 100
            if on_update:
                on_update(response.model_copy(deep=True))
            return response
        if result.status != "succeeded" or not result.text.strip():
            raise ValueError(result.error or f"{'图片' if kind == 'image' else 'PDF'} OCR 未返回可用文本")
        publish("正文识别完成，正在写入资料库…", progress=82)
        initialize_database()
        with connect() as connection:
            item = ContentRepository(connection).get_content_item(content_item_id)
        save_imported_document(item, body=result.text, kind=kind, original_filename=path.name)
        response.transcript = result.text
        response.display_title = item.title
        response.success = True
        response.step = None
        response.overall_progress = 100
        publish(f"{'图片' if kind == 'image' else 'PDF'}已导入，可在右侧继续追问", level="success", step="save", progress=100)
        response.step = None
        if on_update:
            on_update(response.model_copy(deep=True))
        return response
    except InterruptedError as exc:
        response.error = str(exc)
        response.error_info = classify_pipeline_error("cancelled", response.error)
        response.step = "cancelled"
        if on_update:
            on_update(response.model_copy(deep=True))
        return response
    except Exception as exc:
        response.error = str(exc)
        response.error_info = classify_pipeline_error("extract", response.error)
        response.step = "extract"
        if on_update:
            on_update(response.model_copy(deep=True))
        return response


# Kept as a compatibility alias for existing tests and task records created by
# older builds. New callers use the type-neutral name above.
run_pdf_import = run_document_import


def _preserve_generated_sections(next_markdown: str, existing_markdown: str) -> str:
    """Refresh imported source text without discarding a user's summary/Q&A."""
    for heading in ("AI 摘要", "追问记录"):
        pattern = re.compile(rf"^## {re.escape(heading)}\n.*?(?=^## |\Z)", re.MULTILINE | re.DOTALL)
        existing = pattern.search(existing_markdown)
        replacement = pattern.search(next_markdown)
        if existing and replacement:
            next_markdown = next_markdown[:replacement.start()] + existing.group(0).rstrip() + "\n" + next_markdown[replacement.end():]
    return next_markdown


def _decode_text(raw: bytes, label: str) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{label} 文件编码无法识别，请转换为 UTF-8 后重试")


def _markdown_title(markdown: str, filename: str) -> str:
    match = re.search(r"^\s*#\s+(.+?)\s*$", markdown, re.MULTILINE)
    return (match.group(1).strip() if match else Path(filename).stem)[:160]


def extract_html_document(raw: bytes, filename: str) -> HtmlDocumentExtraction:
    """Extract the most article-like HTML region without flattening it first."""
    source = _decode_text(raw, "HTML")
    source_soup = BeautifulSoup(source, "lxml")
    title = source_soup.title
    title_text = title.get_text(" ", strip=True) if title else Path(filename).stem
    source_url = _original_source_url_from_html(source) or ""
    for unwanted in source_soup.select("script, style, noscript, template, svg, canvas, iframe"):
        unwanted.decompose()
    preferred = _best_html_content_container(source_soup)
    body_html = normalize_article_html(
        _resolve_relative_html_urls(str(preferred or source_soup.body or source_soup), source_url=source_url),
        preserve_local_media=False,
    )
    text = _html_node_text(BeautifulSoup(body_html, "lxml"))
    if not text:
        raise ValueError("HTML 中没有可导入的正文")
    return HtmlDocumentExtraction(
        title=title_text[:160] or Path(filename).stem,
        text=text,
        body_html=body_html,
        raw_html=source,
        source_url=source_url,
    )


def _best_html_content_container(soup: BeautifulSoup) -> Tag | None:
    """Choose an article region before considering the full document body.

    Browser-saved pages frequently contain a long navigation tree. Counting
    its link labels as paragraphs made the complete ``body`` outscore an
    explicitly marked article node. Known publisher/CMS containers therefore
    form a higher-priority tier; a cleaned body is only used as a fallback.
    """
    explicit = _html_unique_nodes(soup, _HTML_EXPLICIT_CONTENT_SELECTORS)
    # An explicitly marked publisher container is more trustworthy than a
    # large navigation-heavy body even when the article itself is short.
    viable = [node for node in explicit if _html_node_text(node)]
    if viable:
        return max(viable, key=_html_content_score)

    semantic = _html_unique_nodes(soup, _HTML_SEMANTIC_CONTENT_SELECTORS)
    viable_semantic = [node for node in semantic if _html_content_score(node) > -10_000]
    if viable_semantic:
        return max(viable_semantic, key=_html_content_score)

    # Never return the source body directly: it can contain a site's chrome
    # and browser-extension overlays. Work on a clone so the retained raw
    # HTML source remains faithful for the original-page preview.
    fallback_soup = BeautifulSoup(str(soup.body or soup), "lxml")
    fallback_root = fallback_soup.body or fallback_soup
    _remove_html_chrome(fallback_root)
    fallback_candidates = _html_unique_nodes(fallback_soup, _HTML_SEMANTIC_CONTENT_SELECTORS)
    fallback_candidates.append(fallback_root)
    viable_fallback = [node for node in fallback_candidates if _html_content_score(node) > -10_000]
    return max(viable_fallback, key=_html_content_score, default=None)


def _html_unique_nodes(soup: BeautifulSoup, selectors: tuple[str, ...]) -> list[Tag]:
    candidates: list[Tag] = []
    seen: set[int] = set()
    for selector in selectors:
        for candidate in soup.select(selector):
            identity = id(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(candidate)
    return candidates


def _html_content_score(node: Tag) -> float:
    text = _html_node_text(node)
    if len(text) < 20 or (len(text) < 40 and node.name not in {"article", "main"}):
        return -10_000
    paragraph_count = len(node.find_all(["p", "li", "blockquote", "td", "th"]))
    link_text = sum(len(_html_node_text(link)) for link in node.find_all("a"))
    link_density = link_text / max(len(text), 1)
    if link_density > 0.72 and paragraph_count < 3:
        return -10_000
    sentence_count = len(re.findall(r"[。！？；.!?]", text))
    semantic_bonus = 900 if node.name in {"article", "main"} else 0
    chrome_penalty = 1_800 if _is_html_chrome_node(node) else 0
    return (
        min(len(text), 30_000)
        + paragraph_count * 140
        + min(sentence_count, 80) * 36
        + semantic_bonus
        - link_density * 1_600
        - chrome_penalty
    )


def _remove_html_chrome(root: Tag) -> None:
    for node in list(root.select("header, nav, footer, aside, [role='navigation'], [role='banner'], [role='contentinfo'], [role='complementary']")):
        node.decompose()
    for node in list(root.find_all(True)):
        if _is_html_chrome_node(node):
            node.decompose()


def _is_html_chrome_node(node: Tag) -> bool:
    if node.name in {"nav", "header", "footer", "aside"}:
        return True
    classes = node.get("class") or []
    tokens = " ".join(
        [str(node.get("id") or ""), *(str(value) for value in classes), str(node.get("role") or "")]
    )
    return bool(_HTML_CHROME_TOKEN_RE.search(tokens))


def _resolve_relative_html_urls(fragment: str, *, source_url: str) -> str:
    """Preserve images and links from browser-saved pages in reader mode."""
    if not source_url:
        return fragment
    soup = BeautifulSoup(fragment, "lxml")
    root = soup.body or soup
    for node in root.find_all(["img", "a"]):
        attribute = "data-src" if node.name == "img" and node.get("data-src") else "src" if node.name == "img" else "href"
        value = str(node.get(attribute) or "").strip()
        if value and not value.startswith(("https://", "http://", "data:", "#")):
            node[attribute] = urljoin(source_url, value)
    return "".join(str(node) for node in root.contents)


def _extract_html(raw: bytes, filename: str) -> tuple[str, str]:
    """Compatibility wrapper for callers that only need plain text."""
    extraction = extract_html_document(raw, filename)
    return extraction.text, extraction.title


def _html_node_text(node) -> str:
    if not node:
        return ""
    text = node.get_text("\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def _extract_docx(raw: bytes, filename: str) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if sum(info.file_size for info in infos) > 128 * 1024 * 1024:
                raise ValueError("Word 文档展开后过大，已拒绝导入")
            document_xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("不是有效的 DOCX 文档") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("不是有效的 DOCX 文档") from exc
    root = ElementTree.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_WORD_NS}p"):
        value = "".join(node.text or "" for node in paragraph.iter(f"{_WORD_NS}t")).strip()
        if value:
            paragraphs.append(value)
    text = "\n\n".join(paragraphs).strip()
    if not text:
        raise ValueError("Word 文档没有可读取的文字；图片中的文字暂不自动识别")
    return text, (paragraphs[0][:160] if paragraphs else Path(filename).stem)
