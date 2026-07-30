"""Low-frequency RSS/Atom source discovery and local article ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from time import strftime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.cache import cache_dir_for_url, read_cache_meta, write_cache_meta
from services.content_index import ensure_rss_source_folder
from services.database import connect, initialize_database, utc_now_iso
from services.repository import ContentRepository, new_id
from services.pipeline_runner import PipelineRequest
from services.task_manager import task_manager


DEFAULT_SYNC_INTERVAL_MINUTES = 180
DEFAULT_SYNC_LIMIT = 100
MAX_SYNC_LIMIT = 100
ALLOWED_SYNC_INTERVAL_MINUTES = {30, 60, 180, 360, 720, 1440}


class RssSyncError(ValueError):
    """A source or feed error safe to show directly in the interface."""


@dataclass(frozen=True)
class RssEntry:
    identity: str
    title: str
    url: str
    published_at: str | None
    author: str
    body_html: str
    body_text: str
    source_summary: str
    needs_full_text: bool = False


@dataclass(frozen=True)
class RssPreview:
    feed_url: str
    title: str
    description: str
    site_url: str
    entries: list[RssEntry]


def preview_rss_source(*, feed_url: str, limit: int = DEFAULT_SYNC_LIMIT) -> RssPreview:
    normalized_url = _normalize_feed_url(feed_url)
    parsed = _fetch_feed(normalized_url)
    feed = parsed.feed
    title = _entry_value(feed, "title") or _hostname_label(normalized_url)
    description = _html_text(_entry_value(feed, "subtitle") or _entry_value(feed, "description"))
    site_url = _entry_value(feed, "link")
    entries = [_parse_entry(entry) for entry in list(parsed.entries)[:_valid_limit(limit)]]
    return RssPreview(
        feed_url=normalized_url,
        title=title[:300],
        description=description[:1000],
        site_url=site_url[:2000],
        entries=[entry for entry in entries if entry is not None],
    )


def create_rss_source(*, feed_url: str, sync_interval_minutes: int = DEFAULT_SYNC_INTERVAL_MINUTES, auto_analyze: bool = False, notify_on_new: bool = False) -> dict[str, Any]:
    preview = preview_rss_source(feed_url=feed_url)
    return _save_and_sync(preview, source_id=None, sync_interval_minutes=sync_interval_minutes, auto_analyze=auto_analyze, notify_on_new=notify_on_new)


def sync_saved_rss_source(source_id: str) -> dict[str, Any]:
    source = get_rss_source(source_id)
    if not source["enabled"]:
        raise RssSyncError("该 RSS 订阅已暂停；恢复后再检查")
    try:
        preview = preview_rss_source(feed_url=source["feed_url"])
        return _save_and_sync(
            preview,
            source_id=source_id,
            sync_interval_minutes=source["sync_interval_minutes"],
            auto_analyze=bool(source.get("auto_analyze", False)),
            notify_on_new=bool(source.get("notify_on_new", False)),
        )
    except Exception as exc:
        _record_sync_error(source_id, str(exc))
        if isinstance(exc, RssSyncError):
            raise
        raise RssSyncError(f"RSS 检查失败：{exc}") from exc


def sync_due_rss_sources() -> list[str]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT id FROM rss_sources
               WHERE enabled=1 AND (next_sync_at IS NULL OR next_sync_at='' OR next_sync_at<=?)
               ORDER BY COALESCE(next_sync_at, created_at), created_at""",
            (utc_now_iso(),),
        ).fetchall()
    from services.task_manager import task_manager

    completed: list[str] = []
    for row in rows:
        try:
            source_id = str(row["id"])
            task_manager.create_source_sync(
                {"kind": "rss_saved", "source_id": source_id},
                source_title="自动检查 RSS",
                execution_mode="background",
            )
            completed.append(source_id)
        except Exception:
            continue
    return completed


def list_rss_sources() -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        # The management view is a stable subscription list, not an activity
        # feed. ``updated_at`` changes for every automatic sync and setting
        # toggle, so ordering by it made rows jump unexpectedly.
        rows = connection.execute("SELECT * FROM rss_sources ORDER BY created_at ASC, id ASC").fetchall()
        groups = _source_group_ids(connection, [str(row["id"]) for row in rows])
    return [_serialize_source(row, group_ids=groups.get(str(row["id"]), [])) for row in rows]


def get_rss_source(source_id: str) -> dict[str, Any]:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT * FROM rss_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise LookupError(source_id)
        groups = _source_group_ids(connection, [source_id])
    return _serialize_source(row, group_ids=groups.get(source_id, []))


def update_rss_source(
    source_id: str,
    *,
    enabled: bool | None = None,
    sync_interval_minutes: int | None = None,
    group_ids: list[str] | None = None,
    auto_analyze: bool | None = None,
    notify_on_new: bool | None = None,
) -> dict[str, Any]:
    if enabled is None and sync_interval_minutes is None and group_ids is None and auto_analyze is None and notify_on_new is None:
        raise RssSyncError("至少提供一个需要更新的订阅设置")
    initialize_database()
    with connect() as connection:
        current = connection.execute("SELECT * FROM rss_sources WHERE id=?", (source_id,)).fetchone()
        if not current:
            raise LookupError(source_id)
        interval = _valid_interval(sync_interval_minutes if sync_interval_minutes is not None else current["sync_interval_minutes"])
        next_enabled = bool(current["enabled"]) if enabled is None else bool(enabled)
        next_auto_analyze = bool(current["auto_analyze"]) if auto_analyze is None else bool(auto_analyze)
        next_notify_on_new = bool(current["notify_on_new"]) if notify_on_new is None else bool(notify_on_new)
        normalized_group_ids = None if group_ids is None else list(dict.fromkeys(str(value).strip() for value in group_ids if str(value).strip()))
        if normalized_group_ids is not None:
            if len(normalized_group_ids) > 3:
                raise RssSyncError("一个 RSS 订阅最多加入 3 个分组")
            if normalized_group_ids:
                placeholders = ",".join("?" for _ in normalized_group_ids)
                count = connection.execute(f"SELECT COUNT(*) FROM wechat_subscription_groups WHERE id IN ({placeholders})", tuple(normalized_group_ids)).fetchone()[0]
                if count != len(normalized_group_ids):
                    raise RssSyncError("报告分组不存在")
        next_sync_at = utc_now_iso() if enabled is True else current["next_sync_at"]
        connection.execute(
            """UPDATE rss_sources
               SET enabled=?, sync_interval_minutes=?, auto_analyze=?, notify_on_new=?, next_sync_at=?, updated_at=?
               WHERE id=?""",
            (int(next_enabled), interval, int(next_auto_analyze), int(next_notify_on_new), next_sync_at, utc_now_iso(), source_id),
        )
        if normalized_group_ids is not None:
            connection.execute("DELETE FROM rss_source_group_memberships WHERE source_id=?", (source_id,))
            connection.executemany(
                "INSERT INTO rss_source_group_memberships (source_id, group_id, created_at) VALUES (?, ?, ?)",
                [(source_id, group_id, utc_now_iso()) for group_id in normalized_group_ids],
            )
        connection.commit()
        row = connection.execute("SELECT * FROM rss_sources WHERE id=?", (source_id,)).fetchone()
        groups = _source_group_ids(connection, [source_id])
    return _serialize_source(row, group_ids=groups.get(source_id, []))


def delete_rss_source(source_id: str) -> None:
    initialize_database()
    with connect() as connection:
        row = connection.execute("SELECT id FROM rss_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            raise LookupError(source_id)
        # Removing a subscription stops future checks but preserves imported
        # articles in the library, matching the existing subscription contract.
        connection.execute("DELETE FROM rss_sources WHERE id=?", (source_id,))
        connection.commit()


def list_rss_sync_runs(source_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT status, message, discovered_count, created_count, created_at
               FROM rss_sync_runs WHERE source_id=? ORDER BY created_at DESC LIMIT ?""",
            (source_id, max(1, min(int(limit), 30))),
        ).fetchall()
    return [dict(row) for row in rows]


def _save_and_sync(preview: RssPreview, *, source_id: str | None, sync_interval_minutes: int, auto_analyze: bool | None = None, notify_on_new: bool | None = None) -> dict[str, Any]:
    initialize_database()
    interval = _valid_interval(sync_interval_minutes)
    created_count = 0
    created_items: list[tuple[str, str, str, bool]] = []
    existing_summary_items: list[str] = []
    with connect() as connection:
        source_row = (
            connection.execute("SELECT * FROM rss_sources WHERE id=?", (source_id,)).fetchone()
            if source_id else connection.execute("SELECT * FROM rss_sources WHERE feed_url=?", (preview.feed_url,)).fetchone()
        )
        if source_id and not source_row:
            raise LookupError(source_id)
        source_id = str(source_row["id"]) if source_row else new_id()
        folder_id = str(source_row["library_folder_id"] or "") if source_row else ""
        if not folder_id:
            folder_id = ensure_rss_source_folder(connection, source_id, preview.title)
        now = utc_now_iso()
        if source_row:
            connection.execute(
                """UPDATE rss_sources SET feed_url=?, title=?, description=?, site_url=?, library_folder_id=?,
                   sync_interval_minutes=?, updated_at=? WHERE id=?""",
                (preview.feed_url, preview.title, preview.description, preview.site_url, folder_id, interval, now, source_id),
            )
            source_auto_analyze = bool(source_row["auto_analyze"])
            source_notify_on_new = bool(source_row["notify_on_new"])
        else:
            source_auto_analyze = bool(auto_analyze)
            source_notify_on_new = bool(notify_on_new)
            connection.execute(
                """INSERT INTO rss_sources (
                    id, feed_url, title, description, site_url, library_folder_id, enabled,
                    sync_interval_minutes, sync_limit, auto_analyze, notify_on_new, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)""",
                (source_id, preview.feed_url, preview.title, preview.description, preview.site_url, folder_id, interval, DEFAULT_SYNC_LIMIT, int(source_auto_analyze), int(source_notify_on_new), now, now),
            )
        repository = ContentRepository(connection)
        for position, entry in enumerate(preview.entries):
            existing = connection.execute(
                "SELECT content_item_id FROM rss_source_items WHERE source_id=? AND entry_identity=?",
                (source_id, entry.identity),
            ).fetchone()
            if existing:
                if entry.needs_full_text and _mark_existing_summary_for_full_text(
                    str(existing["content_item_id"]), entry,
                ):
                    existing_summary_items.append(str(existing["content_item_id"]))
                continue
            item = repository.create_content_item(
                source_provider="rss",
                content_type="article",
                source_url=entry.url,
                canonical_source_id=f"{source_id}:{entry.identity}",
                title=entry.title,
                status="to_read",
                library_folder_id=folder_id,
                sort_order=float(position),
                published_at=entry.published_at,
                source_name=preview.title,
                source_section="RSS 订阅",
            )
            connection.execute(
                """INSERT INTO rss_source_items (source_id, content_item_id, entry_identity, source_summary, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (source_id, item.id, entry.identity, entry.source_summary, now),
            )
            _write_entry_cache(item.id, entry)
            created_items.append((item.id, entry.title, entry.url, entry.needs_full_text))
            created_count += 1
        _record_sync_success(connection, source_id, interval, len(preview.entries), created_count)
        connection.commit()
        source = connection.execute("SELECT * FROM rss_sources WHERE id=?", (source_id,)).fetchone()
    if source_auto_analyze:
        for item_id, title, url, _needs_full_text in created_items:
            task_manager.create(PipelineRequest(content_item_id=item_id, share_text=url, source_title=title, source_url=url, processing_mode="full", execution_mode="background"))
    if existing_summary_items or not source_auto_analyze:
        # Summary-only feeds remain quick to import. Their linked pages are
        # fetched by the existing low-priority article preparation workers.
        from services.article_ingest_preparation import enqueue_article_source_preparation

        for item_id in existing_summary_items:
            enqueue_article_source_preparation(item_id)
        for item_id, _title, _url, needs_full_text in created_items:
            if needs_full_text and not source_auto_analyze:
                enqueue_article_source_preparation(item_id)
    return {
        "source": _serialize_source(source),
        "discovered_count": len(preview.entries),
        "created_count": created_count,
        "duplicate_count": len(preview.entries) - created_count,
    }


def _write_entry_cache(content_item_id: str, entry: RssEntry) -> None:
    cache_dir = cache_dir_for_url(entry.url)
    article_info = {
        "title": entry.title,
        "platform": "rss",
        "author": entry.author,
        "published_at": entry.published_at or "",
        "body_text": entry.body_text,
        "body_html": entry.body_html,
        "normalized_html": normalize_article_html(entry.body_html),
        "normalized_html_version": ARTICLE_NORMALIZER_VERSION,
        "images": [],
        "image_ocr": {},
        "document_ocr": {},
        "document_markdown": "",
        "attachments": [],
        "rss_content_item_id": content_item_id,
        "rss_body_source": "feed_summary" if entry.needs_full_text else "feed_full",
        "rss_full_text_status": "pending" if entry.needs_full_text else "not_needed",
        "rss_feed_summary": entry.source_summary,
    }
    write_cache_meta(cache_dir, {
        "source_url": entry.url,
        "platform": "rss",
        "cache_key": cache_dir.name,
        "article_info": article_info,
        "article_capture": {"last_attempt_at": utc_now_iso(), "last_error": ""},
    })


def _mark_existing_summary_for_full_text(content_item_id: str, entry: RssEntry) -> bool:
    """Upgrade a pre-feature RSS cache so its next worker fetches the page once."""
    cache_dir = cache_dir_for_url(entry.url)
    metadata = read_cache_meta(cache_dir)
    article_info = metadata.get("article_info")
    article_info = article_info if isinstance(article_info, dict) else {}
    if article_info.get("rss_body_source") in {"web_full", "feed_full"}:
        return False
    if article_info.get("rss_full_text_status") == "failed":
        return False
    if article_info.get("rss_body_source") == "feed_summary" and article_info.get("rss_full_text_status") == "pending":
        return True
    write_cache_meta(
        cache_dir,
        {
            "article_info": {
                **article_info,
                "rss_content_item_id": content_item_id,
                "rss_body_source": "feed_summary",
                "rss_full_text_status": "pending",
                "rss_feed_summary": entry.source_summary,
            }
        },
    )
    return True


def _fetch_feed(feed_url: str):
    try:
        response = httpx.get(
            feed_url,
            follow_redirects=True,
            timeout=20.0,
            headers={"User-Agent": "KnowledgeHub RSS Reader/1.0 (+local)"},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RssSyncError(f"无法读取订阅地址：{exc}") from exc
    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        detail = str(getattr(parsed, "bozo_exception", "订阅格式无效"))
        raise RssSyncError(f"无法解析 RSS/Atom：{detail}")
    if not parsed.entries:
        raise RssSyncError("订阅源中没有可读取的文章")
    return parsed


def _parse_entry(entry: Any) -> RssEntry | None:
    title = _entry_value(entry, "title").strip() or "未命名文章"
    url = _entry_value(entry, "link").strip()
    if not url.startswith(("https://", "http://")):
        return None
    raw_content, needs_full_text = _entry_content(entry)
    body_html = raw_content.strip() or f"<p>{title}</p>"
    body_text = _html_text(body_html) or title
    identity = _entry_value(entry, "id") or _entry_value(entry, "guid") or url
    identity = sha256(identity.encode("utf-8")).hexdigest()
    return RssEntry(
        identity=identity,
        title=title[:500],
        url=url[:2000],
        published_at=_entry_published_at(entry),
        author=_entry_value(entry, "author")[:300],
        body_html=body_html,
        body_text=body_text,
        source_summary=_entry_value(entry, "summary")[:4000],
        needs_full_text=needs_full_text,
    )


def _entry_content(entry: Any) -> tuple[str, bool]:
    contents = getattr(entry, "content", None) or []
    for content in contents:
        value = _entry_value(content, "value")
        if value:
            return value, False
    encoded = _entry_value(entry, "content_encoded")
    if encoded:
        return encoded, False
    return _entry_value(entry, "summary") or _entry_value(entry, "description"), True


def _entry_value(value: Any, key: str) -> str:
    if isinstance(value, dict):
        raw = value.get(key, "")
    else:
        raw = getattr(value, key, "")
    return str(raw or "").strip()


def _entry_published_at(entry: Any) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            try:
                return strftime("%Y-%m-%dT%H:%M:%SZ", parsed)
            except (TypeError, ValueError):
                pass
    return None


def _html_text(value: str) -> str:
    soup = BeautifulSoup(value or "", "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())[:200_000]


def _normalize_feed_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RssSyncError("请输入有效的 HTTP(S) RSS 或 Atom 地址")
    return url


def _hostname_label(url: str) -> str:
    return str(urlparse(url).hostname or "RSS 订阅")


def _valid_interval(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError) as exc:
        raise RssSyncError("检查频率无效") from exc
    if minutes not in ALLOWED_SYNC_INTERVAL_MINUTES:
        raise RssSyncError("检查频率必须使用预设值")
    return minutes


def _valid_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise RssSyncError("单次检查数量无效") from exc
    if not 1 <= limit <= MAX_SYNC_LIMIT:
        raise RssSyncError(f"单次检查数量必须在 1 到 {MAX_SYNC_LIMIT} 之间")
    return limit


def _record_sync_success(connection, source_id: str, interval: int, discovered_count: int, created_count: int) -> None:
    now = datetime.now(timezone.utc)
    connection.execute(
        """UPDATE rss_sources SET last_sync_at=?, next_sync_at=?, last_error='', consecutive_failure_count=0,
           last_discovered_count=?, last_created_count=?, updated_at=? WHERE id=?""",
        ((now.isoformat()), (now + timedelta(minutes=interval)).isoformat(), discovered_count, created_count, now.isoformat(), source_id),
    )
    connection.execute(
        """INSERT INTO rss_sync_runs (id, source_id, status, discovered_count, created_count, created_at)
           VALUES (?, ?, 'succeeded', ?, ?, ?)""",
        (new_id(), source_id, discovered_count, created_count, now.isoformat()),
    )


def _record_sync_error(source_id: str, message: str) -> None:
    initialize_database()
    now = datetime.now(timezone.utc)
    with connect() as connection:
        row = connection.execute("SELECT sync_interval_minutes, consecutive_failure_count FROM rss_sources WHERE id=?", (source_id,)).fetchone()
        if not row:
            return
        failures = int(row["consecutive_failure_count"] or 0) + 1
        interval = _valid_interval(row["sync_interval_minutes"])
        retry_minutes = min(720, max(interval, 30 * (2 ** min(failures - 1, 4))))
        safe_message = str(message or "RSS 检查失败")[:500]
        connection.execute(
            """UPDATE rss_sources SET last_error=?, consecutive_failure_count=?, next_sync_at=?, updated_at=? WHERE id=?""",
            (safe_message, failures, (now + timedelta(minutes=retry_minutes)).isoformat(), now.isoformat(), source_id),
        )
        connection.execute(
            """INSERT INTO rss_sync_runs (id, source_id, status, message, created_at)
               VALUES (?, ?, 'failed', ?, ?)""",
            (new_id(), source_id, safe_message, now.isoformat()),
        )
        connection.commit()


def _source_group_ids(connection, source_ids: list[str]) -> dict[str, list[str]]:
    if not source_ids:
        return {}
    placeholders = ",".join("?" for _ in source_ids)
    rows = connection.execute(f"SELECT source_id, group_id FROM rss_source_group_memberships WHERE source_id IN ({placeholders}) ORDER BY created_at", tuple(source_ids)).fetchall()
    groups: dict[str, list[str]] = {source_id: [] for source_id in source_ids}
    for row in rows:
        groups.setdefault(str(row["source_id"]), []).append(str(row["group_id"]))
    return groups


def _serialize_source(row: Any, *, group_ids: list[str] | None = None) -> dict[str, Any]:
    source = dict(row)
    source["enabled"] = bool(source.get("enabled", True))
    source["auto_analyze"] = bool(source.get("auto_analyze", False))
    source["notify_on_new"] = bool(source.get("notify_on_new", False))
    source["sync_interval_minutes"] = _valid_interval(source.get("sync_interval_minutes", DEFAULT_SYNC_INTERVAL_MINUTES))
    source.pop("sync_limit", None)
    source["consecutive_failure_count"] = max(0, int(source.get("consecutive_failure_count") or 0))
    source["last_discovered_count"] = max(0, int(source.get("last_discovered_count") or 0))
    source["last_created_count"] = max(0, int(source.get("last_created_count") or 0))
    source["group_ids"] = list(group_ids or [])
    return source
