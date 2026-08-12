"""Persist XHS image-note captures using the application's article contract."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import httpx

from services.article_image_storage import write_article_image_preview
from services.cache import write_cache_meta
from services.database import connect, initialize_database
from services.paddle_ocr import is_paddle_ocr_configured, recognize_local_image
from services.repository import ContentItemRecord, ContentRepository
from services.repository import new_id
from services.source_context import build_source_context
from services.task_manager import task_manager
from services.content_index import ensure_managed_folder
from services.database import utc_now_iso
from services.xiaohongshu_cache import promote_xiaohongshu_cache, xiaohongshu_cache_dir
from services.xiaohongshu_client import XiaohongshuClientError, fetch_note
from services.xiaohongshu_capability import require_xiaohongshu_collector, xiaohongshu_collector_capability


_SYNC_LOCK = Lock()
_DEFAULT_SYNC_INTERVAL_MINUTES = 360
_XHS_TAG_RE = re.compile(r"(?<![\w#])#(?P<tag>[\w\-\u4e00-\u9fff]{1,32})(?:\[[^\]\r\n]{1,32}\])?#?")


def capture_xiaohongshu_note(content_item_id: str) -> dict[str, object]:
    require_xiaohongshu_collector()
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).get_content_item(content_item_id)
    if item.source_provider != "xiaohongshu" or item.content_type != "article" or not item.source_url:
        raise XiaohongshuClientError("不是可处理的小红书图文")

    note = fetch_note(item.source_url)
    cache_dir = promote_xiaohongshu_cache(note.source_url)
    image_dir = cache_dir / "article_images"
    gallery = [_capture_image(url, index=index, image_dir=image_dir, content_item_id=item.id) for index, url in enumerate(note.image_urls, start=1)]
    body_text = _source_text(note.description, gallery)
    body_html = render_xiaohongshu_description_html(note.description)
    if not body_html:
        body_html = "<p>这篇图文笔记未提供文字描述。</p>"

    source_context = build_source_context(
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
    article_info = {
        "title": note.title,
        "platform": "xiaohongshu",
        "author": note.author,
        "author_url": note.author_url,
        "avatar_url": note.avatar_url,
        "published_at": note.published_at,
        "description": note.description,
        "body_text": body_text,
        "body_html": body_html,
        "normalized_html": body_html,
        "xhs_gallery": gallery,
        "tags": list(note.tags),
        "stats": note.stats,
        "ip_location": note.ip_location,
        "source_context": source_context,
    }
    write_cache_meta(cache_dir, {"source_url": note.source_url, "platform": "xiaohongshu", "article_info": article_info})
    with connect() as connection:
        repository = ContentRepository(connection)
        repository.update_source_metadata(
            item.id,
            title=note.title,
            published_at=note.published_at or None,
            source_name=note.author,
            source_section="小红书图文",
        )
        connection.commit()
    return article_info


def refresh_xiaohongshu_ocr(item: ContentItemRecord) -> dict[str, object]:
    """Merge completed OCR cache results into an existing XHS source record."""
    from services.cache import read_cache_meta

    cache_dir = xiaohongshu_cache_dir(str(item.source_url or ""))
    info = dict(read_cache_meta(cache_dir).get("article_info") or {})
    gallery = [dict(entry) for entry in list(info.get("xhs_gallery") or []) if isinstance(entry, dict)]
    changed = False
    if is_paddle_ocr_configured():
        for entry in gallery:
            path = Path(str(entry.get("cached_path") or ""))
            if not path.is_file():
                continue
            result = recognize_local_image(path, content_item_id=item.id)
            if result.text.strip() and entry.get("ocr_text") != result.text.strip():
                entry["ocr_text"] = result.text.strip()
                changed = True
            entry["ocr_status"] = result.status
    if changed:
        info["xhs_gallery"] = gallery
        info["body_text"] = _source_text(str(info.get("description") or _text_from_html(str(info.get("body_html") or ""))), gallery)
        write_cache_meta(cache_dir, {"article_info": info})
    return info


def sync_xiaohongshu_favorites(*, auto_analyze: bool = True, source_id: str | None = None) -> dict[str, object]:
    """Low-frequency, deduplicated sync for the current account's favorites."""
    from services.xiaohongshu_client import fetch_my_favorites
    from services.pipeline_runner import PipelineRequest

    require_xiaohongshu_collector()
    initialize_database()
    with _SYNC_LOCK:
        with connect() as connection:
            row = _find_favorite_source(connection, source_id)
            if source_id and not row:
                raise XiaohongshuClientError("小红书收藏同步不存在")
            if row and not bool(row["enabled"]):
                raise XiaohongshuClientError("小红书“我的收藏”已暂停；恢复后再检查")
        try:
            notes = fetch_my_favorites(limit=5)
        except Exception as exc:
            if row:
                _record_favorite_error(str(row["id"]), str(exc))
            raise
        with connect() as connection:
            row = _find_favorite_source(connection, source_id)
            now = utc_now_iso()
            identifier = str(row["id"]) if row else new_id()
            folder_id = ensure_managed_folder(
                connection,
                source_type="xiaohongshu_favorite_source",
                source_key=identifier,
                name="我的小红书收藏",
            )
            if row:
                should_analyze = bool(row["auto_analyze"])
                interval = _valid_interval(row["sync_interval_minutes"])
                connection.execute(
                    "UPDATE xiaohongshu_favorite_sources SET library_folder_id=?, last_sync_at=?, next_sync_at=?, last_error=NULL, updated_at=? WHERE id=?",
                    (folder_id, now, _next_sync_at(interval), now, identifier),
                )
            else:
                should_analyze = bool(auto_analyze)
                interval = _DEFAULT_SYNC_INTERVAL_MINUTES
                connection.execute(
                    """INSERT INTO xiaohongshu_favorite_sources
                       (id, library_folder_id, auto_analyze, sync_interval_minutes, sync_limit, last_sync_at, next_sync_at, created_at, updated_at)
                       VALUES (?, ?, ?, ?, 5, ?, ?, ?, ?)""",
                    (identifier, folder_id, int(should_analyze), interval, now, _next_sync_at(interval), now, now),
                )
            repository = ContentRepository(connection)
            created: list[ContentItemRecord] = []
            for position, note in enumerate(notes):
                item = repository.find_by_canonical_id(source_provider="xiaohongshu", canonical_source_id=note.note_id)
                if item is not None and item.source_url != note.source_url:
                    promote_xiaohongshu_cache(item.source_url)
                    item = repository.update_source_url(item.id, note.source_url)
                mapped = connection.execute(
                    "SELECT 1 FROM xiaohongshu_favorite_items WHERE source_id=? AND note_id=?",
                    (identifier, note.note_id),
                ).fetchone()
                if mapped:
                    continue
                if item is None:
                    item = repository.create_content_item(
                        source_provider="xiaohongshu",
                        content_type="article",
                        source_url=note.source_url,
                        canonical_source_id=note.note_id,
                        title=note.title,
                        cover_url=note.image_urls[0] if note.image_urls else None,
                        status="processing" if should_analyze else "inbox",
                        library_folder_id=folder_id,
                        source_name="个人收藏",
                        source_section="我的小红书收藏",
                        published_at=note.published_at or None,
                        sort_order=float(position),
                    )
                    created.append(item)
                connection.execute(
                    "INSERT OR IGNORE INTO xiaohongshu_favorite_items (source_id, content_item_id, note_id, created_at) VALUES (?, ?, ?, ?)",
                    (identifier, item.id, note.note_id, now),
                )
            connection.commit()
    task_ids = []
    if should_analyze:
        for item in created:
            task = task_manager.create(PipelineRequest(
                content_item_id=item.id,
                share_text=item.source_url,
                source_url=item.source_url,
                source_title=item.title,
                processing_mode="full",
                execution_mode="background",
            ))
            task_ids.append(task.task_id)
    return {"source_id": identifier, "discovered_count": len(notes), "created_count": len(created), "duplicate_count": len(notes) - len(created), "task_ids": task_ids, "content_item_ids": [item.id for item in created]}


def get_xiaohongshu_favorite_source() -> dict[str, object] | None:
    initialize_database()
    with connect() as connection:
        row = _find_favorite_source(connection, None)
    return _serialize_favorite_source(row) if row else None


def update_xiaohongshu_favorite_source(*, enabled: bool | None = None, auto_analyze: bool | None = None) -> dict[str, object]:
    if enabled is None and auto_analyze is None:
        raise XiaohongshuClientError("至少提供一个需要更新的收藏设置")
    initialize_database()
    with connect() as connection:
        row = _find_favorite_source(connection, None)
        if not row:
            raise LookupError("xiaohongshu")
        next_enabled = bool(row["enabled"]) if enabled is None else bool(enabled)
        next_auto_analyze = bool(row["auto_analyze"]) if auto_analyze is None else bool(auto_analyze)
        next_sync = utc_now_iso() if enabled is True else row["next_sync_at"]
        connection.execute(
            "UPDATE xiaohongshu_favorite_sources SET enabled=?, auto_analyze=?, next_sync_at=?, updated_at=? WHERE id=?",
            (int(next_enabled), int(next_auto_analyze), next_sync, utc_now_iso(), row["id"]),
        )
        connection.commit()
        row = _find_favorite_source(connection, str(row["id"]))
    return _serialize_favorite_source(row)


def sync_due_xiaohongshu_favorites() -> list[str]:
    if not xiaohongshu_collector_capability()["available"]:
        return []
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT id FROM xiaohongshu_favorite_sources
               WHERE enabled=1 AND (next_sync_at IS NULL OR next_sync_at='' OR next_sync_at<=?)""",
            (utc_now_iso(),),
        ).fetchall()
    queued: list[str] = []
    for row in rows:
        source_id = str(row["id"])
        try:
            task_manager.create_source_sync(
                {"kind": "favorite_xiaohongshu", "source_id": source_id},
                source_title="自动检查小红书收藏",
                execution_mode="background",
            )
            queued.append(source_id)
        except Exception:
            continue
    return queued


def _find_favorite_source(connection, source_id: str | None):
    if source_id:
        return connection.execute("SELECT * FROM xiaohongshu_favorite_sources WHERE id=?", (source_id,)).fetchone()
    return connection.execute("SELECT * FROM xiaohongshu_favorite_sources ORDER BY created_at LIMIT 1").fetchone()


def _next_sync_at(interval: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=interval)).isoformat()


def _valid_interval(value: object) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = _DEFAULT_SYNC_INTERVAL_MINUTES
    return max(30, min(interval, 1440))


def _record_favorite_error(source_id: str, message: str) -> None:
    now = utc_now_iso()
    with connect() as connection:
        row = _find_favorite_source(connection, source_id)
        if not row:
            return
        connection.execute(
            "UPDATE xiaohongshu_favorite_sources SET last_error=?, next_sync_at=?, updated_at=? WHERE id=?",
            (str(message)[:500], _next_sync_at(min(60, _valid_interval(row["sync_interval_minutes"]))), now, source_id),
        )
        connection.commit()


def _serialize_favorite_source(row) -> dict[str, object]:
    return {
        "id": str(row["id"]), "title": str(row["title"]), "enabled": bool(row["enabled"]),
        "auto_analyze": bool(row["auto_analyze"]), "sync_interval_minutes": int(row["sync_interval_minutes"]),
        "last_sync_at": row["last_sync_at"], "next_sync_at": row["next_sync_at"], "last_error": row["last_error"],
    }


def _capture_image(url: str, *, index: int, image_dir: Path, content_item_id: str) -> dict[str, object]:
    entry: dict[str, object] = {"index": index, "source_url": url, "cached_path": "", "ocr_text": "", "ocr_status": "not_configured"}
    try:
        payload, content_type = _download_image(url)
        preview = write_article_image_preview(payload, filename_stem=f"xhs-{index:02d}", image_cache_dir=image_dir)
        if not preview:
            suffix = Path(urlparse(url).path).suffix or ".jpg"
            fallback = image_dir / f"xhs-{index:02d}{suffix[:8]}"
            image_dir.mkdir(parents=True, exist_ok=True)
            fallback.write_bytes(payload)
            preview = str(fallback)
        entry["cached_path"] = preview
        if is_paddle_ocr_configured():
            result = recognize_local_image(Path(preview), content_item_id=content_item_id)
            entry["ocr_text"] = result.text.strip()
            entry["ocr_status"] = result.status
    except Exception as exc:
        entry["ocr_status"] = "failed"
        entry["error"] = str(exc)[:240]
    return entry


def _download_image(url: str) -> tuple[bytes, str]:
    with httpx.Client(timeout=30, follow_redirects=True, trust_env=False, headers={"Referer": "https://www.xiaohongshu.com/"}) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.content
        if not payload or len(payload) > 20 * 1024 * 1024:
            raise ValueError("图片为空或超过 20MB")
        content_type = str(response.headers.get("content-type") or "image/jpeg").split(";", 1)[0]
        if not content_type.startswith("image/"):
            raise ValueError("笔记图片地址未返回图片")
        return payload, content_type


def _source_text(description: str, gallery: list[dict[str, object]]) -> str:
    parts = [str(description or "").strip()]
    for entry in gallery:
        text = str(entry.get("ocr_text") or "").strip()
        if text:
            parts.append(f"[图片文字 {entry.get('index')}]\n{text}\n[/图片文字 {entry.get('index')}]")
    return "\n\n".join(part for part in parts if part).strip()


def render_xiaohongshu_description_html(description: str) -> str:
    """Render only a note description with safe, compact topic badges."""
    lines = [line.strip() for line in str(description or "").splitlines() if line.strip()]
    return "".join(f"<p>{_xhs_description_line_html(line)}</p>" for line in lines)


def _xhs_description_line_html(line: str) -> str:
    pieces: list[str] = []
    position = 0
    for match in _XHS_TAG_RE.finditer(line):
        pieces.append(html.escape(line[position:match.start()]))
        tag = html.escape(match.group("tag"))
        pieces.append(f'<span class="article-xhs-tag">#{tag}</span>')
        position = match.end()
    pieces.append(html.escape(line[position:]))
    return "".join(pieces)


def _text_from_html(value: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", value or "").strip()
