from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from urllib.parse import urlparse

from services.campus_sources import CampusArticle, discover_campus_articles, get_campus_source
from services.campus_source_settings import load_campus_source_settings, record_campus_source_sync
from services.article_ingest_preparation import enqueue_article_source_preparation
from services.content_index import campus_section_binding_key, ensure_campus_section_folder
from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.pipeline_runner import PipelineRequest
from services.task_manager import task_manager


_SYNC_WRITE_LOCK = Lock()


@dataclass(frozen=True)
class CampusSyncRecord:
    content_item_id: str
    title: str
    url: str
    published_at: str
    section: str
    created: bool


def persist_campus_articles(
    source_name: str,
    discovered: list[CampusArticle],
) -> tuple[list[CampusSyncRecord], int]:
    rows: list[CampusSyncRecord] = []
    created_count = 0
    with _SYNC_WRITE_LOCK:
        initialize_database()
        with connect() as connection:
            repository = ContentRepository(connection)
            for article in discovered:
                if source_name.strip() == "公文通":
                    folder_source_name = "公文通"
                    folder_section_name = article.department or article.source_name or "未分类"
                else:
                    folder_source_name = article.department or article.source_name or source_name
                    folder_section_name = article.section or "未分类"
                folder_id = ensure_campus_section_folder(
                    connection,
                    folder_source_name,
                    folder_section_name,
                    source_key=campus_section_binding_key(folder_source_name, folder_section_name),
                )
                provider = "wechat" if urlparse(article.url).hostname == "mp.weixin.qq.com" else "campus"
                existing = repository.find_by_canonical_id(
                    source_provider=provider,
                    canonical_source_id=article.url,
                )
                if existing:
                    item = repository.update_source_metadata(
                        existing.id,
                        title=article.title,
                        published_at=article.published_at,
                        source_name=article.department or article.source_name or source_name,
                        source_section=article.section,
                    )
                    if item.library_folder_id != folder_id:
                        item = repository.update_content_item(
                            item.id,
                            library_folder_id=folder_id,
                        )
                    created = False
                else:
                    item = repository.create_content_item(
                        source_provider=provider,
                        content_type="article",
                        source_url=article.url,
                        canonical_source_id=article.url,
                        title=article.title,
                        status="to_read",
                        library_folder_id=folder_id,
                        published_at=article.published_at or None,
                        source_name=article.department or article.source_name or source_name,
                        source_section=article.section or None,
                    )
                    created = True
                    created_count += 1
                rows.append(
                    CampusSyncRecord(
                        content_item_id=item.id,
                        title=article.title,
                        url=article.url,
                        published_at=article.published_at,
                        section=article.section,
                        created=created,
                    )
                )
            connection.commit()
    for row in rows:
        if row.created:
            enqueue_article_source_preparation(row.content_item_id)
    return rows, created_count


def enqueue_campus_article_analyses(records: list[CampusSyncRecord]) -> int:
    """Queue summaries only for newly discovered campus articles.

    The pipeline recognizes the persisted campus article form and reads its
    local source snapshot, so this does not re-run discovery or move it out of
    the campus source folder.
    """
    queued = 0
    for record in records:
        if not record.created:
            continue
        task_manager.create(
            PipelineRequest(
                content_item_id=record.content_item_id,
                share_text=record.url,
                source_title=record.title,
                source_url=record.url,
                processing_mode="full",
                execution_mode="background",
            )
        )
        queued += 1
    return queued


def known_campus_source_urls(source_name: str, *, source_slug: str = "") -> set[str]:
    """Return the local boundary for newest-first website listing pages."""
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            """SELECT source_url FROM content_items
               WHERE deleted_at IS NULL AND source_url IS NOT NULL
                 AND (source_name=? OR (?='gwt' AND source_section='公文通'))""",
            (source_name, source_slug),
        ).fetchall()
    return {str(row["source_url"]) for row in rows if str(row["source_url"] or "").strip()}


def sync_campus_source_once(source_slug: str, *, limit: int = 100) -> dict[str, object]:
    source = get_campus_source(source_slug)
    known_urls = known_campus_source_urls(source.name, source_slug=source.slug)
    if source.slug == "gwt":
        discovered = discover_campus_articles(
            source_slug,
            limit=limit,
            known_urls=known_urls,
        )
    else:
        # College sites often expose notices and news in separate lists. Keep
        # ten newest unseen items per section, stopping as soon as that section
        # reaches a locally known article.
        discovered = []
        for section in source.sections:
            discovered.extend(discover_campus_articles(
                source_slug,
                section=section,
                limit=max(1, min(int(limit), 200)),
                known_urls=known_urls,
            ))
        discovered = list({article.url: article for article in discovered}.values())
    rows, created = persist_campus_articles(source.name, discovered)
    settings_by_slug = {str(item["slug"]): item for item in load_campus_source_settings()}
    if bool(settings_by_slug.get(source.slug, {}).get("auto_analyze")):
        enqueue_campus_article_analyses(rows)
    record_campus_source_sync(
        source.slug,
        status="success",
        message="后台检查完成",
        discovered=len(rows),
        created=created,
    )
    return {
        "source_slug": source.slug,
        "source_name": source.name,
        "discovered": len(rows),
        "created": created,
        "duplicates": len(rows) - created,
    }


__all__ = ["CampusSyncRecord", "enqueue_campus_article_analyses", "known_campus_source_urls", "persist_campus_articles", "sync_campus_source_once"]
