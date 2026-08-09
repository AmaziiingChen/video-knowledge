from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from services.creator_remote_payloads import parse_creator_page
from services.creator_sync_models import CreatorPreview, CreatorSyncError, CreatorVideo


MAX_CREATOR_CAPTURE_RESPONSE_PAGES = 60


def selected_preview_videos(videos: list[CreatorVideo], selected_video_ids: list[str] | None) -> list[CreatorVideo]:
    if selected_video_ids is None:
        return videos
    selected = {str(item).strip() for item in selected_video_ids if str(item).strip()}
    if not selected:
        raise CreatorSyncError("请至少选择一条预览作品")
    available = {video.canonical_id for video in videos}
    unknown = selected - available
    if unknown:
        raise CreatorSyncError("所选作品已不在本次预览中，请重新预览后提交")
    return [video for video in videos if video.canonical_id in selected]


def unseen_prefix_before_known_item(videos: list[CreatorVideo], known_item_ids: set[str]) -> list[CreatorVideo]:
    """Keep only remotely newer entries before this source's saved anchor.

    A creator source is ordered by the provider's own newest-first list
    order. Once any previously linked remote id appears, every later row is
    historical for this subscription and must stay out of a normal check.
    Failing closed when the anchor is absent is important: accepting a partial
    response would turn an upstream pagination change into a bulk reimport.
    """
    if not videos:
        return []
    for index, video in enumerate(videos):
        if video.canonical_id in known_item_ids:
            return videos[:index]
    raise CreatorSyncError("本次检查未找到上次订阅的作品边界，未导入任何内容；请稍后重试")


def latest_published_at(videos: list[CreatorVideo]) -> str | None:
    values = [str(video.published_at).strip() for video in videos if video.published_at]
    return max(values, default=None)


def should_continue_creator_capture(
    pages: list[dict[str, Any]],
    *,
    provider: str,
    limit: int,
    watermark: datetime | None,
    known_item_ids: set[str] | None = None,
) -> bool:
    if not pages:
        return True
    latest = pages[-1]
    latest_videos, _creator_name, _cursor, has_more = parse_creator_page(latest, provider=provider)
    if known_item_ids and any(video.canonical_id in known_item_ids for video in latest_videos):
        return False
    if len(pages) >= MAX_CREATOR_CAPTURE_RESPONSE_PAGES:
        if known_item_ids:
            raise CreatorSyncError("本次检查尚未找到上次订阅的作品边界，已停止以避免遗漏；请稍后重试")
        return False
    if not has_more:
        if known_item_ids:
            raise CreatorSyncError("本次检查未找到上次订阅的作品边界，未导入任何内容；请稍后重试")
        return False
    if page_reaches_watermark(latest, provider=provider, watermark=watermark):
        return False
    captured_ids = {
        video.canonical_id
        for payload in pages
        for video in parse_creator_page(payload, provider=provider)[0]
    }
    return len(captured_ids) < limit


def page_reaches_watermark(payload: dict[str, Any], *, provider: str, watermark: datetime | None) -> bool:
    if not watermark:
        return False
    videos, _creator_name, _cursor, _has_more = parse_creator_page(payload, provider=provider)
    dated = [parse_timestamp(video.published_at) for video in videos if video.published_at]
    return bool(dated) and min(dated) <= watermark


def append_new_videos(
    destination: list[CreatorVideo],
    candidates: list[CreatorVideo],
    *,
    limit: int,
    cutoff: datetime | None,
) -> None:
    known_ids = {video.canonical_id for video in destination}
    for video in candidates:
        if cutoff and video.published_at and parse_timestamp(video.published_at) < cutoff:
            continue
        if video.canonical_id not in known_ids:
            destination.append(video)
            known_ids.add(video.canonical_id)
        if len(destination) >= limit:
            return


def preview_within_date_range(
    preview: CreatorPreview,
    *,
    after: datetime | None,
    before: datetime | None,
) -> CreatorPreview:
    """Apply the selected date range consistently after provider pagination."""
    if not after and not before:
        return preview
    # Date-only values are inclusive from the UI perspective.
    inclusive_before = before + timedelta(days=1) if before else None
    videos = [
        video for video in preview.videos
        if video.published_at
        and (after is None or parse_timestamp(video.published_at) >= after)
        and (inclusive_before is None or parse_timestamp(video.published_at) < inclusive_before)
    ]
    return CreatorPreview(
        provider=preview.provider,
        source_kind=preview.source_kind,
        source_url=preview.source_url,
        creator_key=preview.creator_key,
        creator_name=preview.creator_name,
        videos=videos,
        creator_avatar_url=preview.creator_avatar_url,
        creator_description=preview.creator_description,
        collection_id=preview.collection_id,
        collection_name=preview.collection_name,
    )


def parse_cutoff(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CreatorSyncError("起始日期格式无效") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
