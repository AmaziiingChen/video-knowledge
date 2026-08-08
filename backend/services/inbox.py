from __future__ import annotations

from dataclasses import dataclass

from services.database import connect, initialize_database
from services.content_index import ensure_manual_collection_target_folder
from services.manual_collection_settings import manual_collection_settings
from services.pipeline_runner import PipelineRequest
from services.providers.registry import get_provider_for_url
from services.repository import ContentItemRecord, ContentRepository
from services.task_manager import TaskRecord, task_manager
from services.url_parser import parse_share_text
from services.xiaohongshu_links import XiaohongshuShareLinkError, resolve_xiaohongshu_share_url


@dataclass(frozen=True)
class InboxCaptureResult:
    item: ContentItemRecord | None
    created: bool
    duplicate: bool
    error: str | None = None


def capture_link_to_inbox(
    url: str,
    *,
    manual_collection: bool = True,
    library_folder_id: str | None = None,
) -> InboxCaptureResult:
    parsed = parse_share_text(url)
    if parsed and parsed.platform == "xiaohongshu":
        try:
            url = resolve_xiaohongshu_share_url(parsed.url)
        except XiaohongshuShareLinkError as exc:
            return InboxCaptureResult(item=None, created=False, duplicate=False, error=str(exc))

    provider = get_provider_for_url(url)
    if provider is None:
        return InboxCaptureResult(item=None, created=False, duplicate=False, error="不支持的链接来源")

    try:
        resolved = provider.resolve(url)
    except Exception:
        normalized = provider.normalize_url(url)
        resolved = None

    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        folder_id = library_folder_id
        if folder_id is None and manual_collection:
            folder_id = ensure_manual_collection_target_folder(connection, provider.name)
        if resolved is None:
            canonical_id = normalized
            existing = repository.find_by_canonical_id(
                source_provider=provider.name,
                canonical_source_id=canonical_id,
            )
            if existing:
                return InboxCaptureResult(item=existing, created=False, duplicate=True)
            item = repository.create_content_item(
                source_provider=provider.name,
                source_url=normalized,
                canonical_source_id=canonical_id,
                title=canonical_id,
                status="inbox",
                library_folder_id=folder_id,
            )
        else:
            existing = repository.find_by_canonical_id(
                source_provider=resolved.provider,
                canonical_source_id=resolved.canonical_source_id,
            )
            if existing is None and resolved.provider == "bilibili":
                existing = repository.find_by_source_url(
                    source_provider=resolved.provider,
                    source_url=resolved.source_url,
                )
                if existing and existing.canonical_source_id != resolved.canonical_source_id:
                    existing = repository.update_canonical_source_id(existing.id, resolved.canonical_source_id)
                    connection.commit()
            if existing:
                # Early XHS attempts could be persisted as generic videos
                # before the image-note provider was introduced. Retain the
                # user's item, but repair its type so retries use the article
                # capture path rather than the media downloader. XHS access
                # tokens can also expire, so a newly captured share link should
                # refresh the URL while the stable note id remains unchanged.
                changed = False
                if resolved.provider == "xiaohongshu" and existing.source_url != resolved.source_url:
                    from services.xiaohongshu_cache import promote_xiaohongshu_cache

                    promote_xiaohongshu_cache(existing.source_url)
                    existing = repository.update_source_url(existing.id, resolved.source_url)
                    changed = True
                if resolved.provider == "xiaohongshu" and existing.content_type != "article":
                    existing = repository.update_content_type(existing.id, "article")
                    changed = True
                if changed:
                    connection.commit()
                return InboxCaptureResult(item=existing, created=False, duplicate=True)
            item = repository.create_content_item(
                source_provider=resolved.provider,
                source_url=resolved.source_url,
                canonical_source_id=resolved.canonical_source_id,
                title=resolved.title,
                content_type=resolved.content_type,
                cover_url=resolved.cover_url or None,
                duration_seconds=resolved.duration_seconds,
                status="inbox",
                library_folder_id=folder_id,
            )
        connection.commit()
        return InboxCaptureResult(item=item, created=True, duplicate=False)


def list_inbox_items(limit: int = 100) -> list[ContentItemRecord]:
    initialize_database()
    with connect() as connection:
        return ContentRepository(connection).list_content_items(status="inbox", limit=limit)


def process_inbox_item(
    item_id: str,
    *,
    whisper_model: str | None = None,
    asr_backend: str | None = None,
    asr_model_strategy: str | None = None,
    asr_short_video_model: str | None = None,
    asr_long_video_model: str | None = None,
    asr_beam_size: int | None = None,
    asr_vad_filter: bool | None = None,
    asr_fallback_enabled: bool | None = None,
    ai_model: str | None = None,
    use_cache: bool = True,
    processing_mode: str | None = None,
) -> tuple[ContentItemRecord, TaskRecord]:
    initialize_database()
    with connect() as connection:
        repository = ContentRepository(connection)
        item = repository.get_content_item(item_id)
        if item.status not in {"inbox", "failed", "archived"}:
            raise ValueError(f"当前状态不能创建处理任务: {item.status}")
        if not item.source_url:
            raise ValueError("收件箱条目缺少来源链接")
        item = repository.update_status(item.id, "processing")
        connection.commit()

    # Explicitly saved links default to a full AI summary.  When the user
    # disables that preference we still fetch and persist readable text, but
    # use the transcript-only path so no model summary is invoked.
    mode = processing_mode or ("full" if manual_collection_settings()["auto_summarize"] else "transcript")
    task = task_manager.create(
        PipelineRequest(
            content_item_id=item.id,
            share_text=item.source_url,
            source_title=item.title,
            source_url=item.source_url,
            whisper_model=whisper_model,
            asr_backend=asr_backend,
            asr_model_strategy=asr_model_strategy,
            asr_short_video_model=asr_short_video_model,
            asr_long_video_model=asr_long_video_model,
            asr_beam_size=asr_beam_size,
            asr_vad_filter=asr_vad_filter,
            asr_fallback_enabled=asr_fallback_enabled,
            ai_model=ai_model,
            use_cache=use_cache,
            processing_mode=mode,
        )
    )
    return item, task
