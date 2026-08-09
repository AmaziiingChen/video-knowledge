from pydantic import BaseModel

from services.repository import ContentItemRecord


class InboxItemResponse(BaseModel):
    id: str
    content_type: str
    source_provider: str
    source_url: str | None = None
    canonical_source_id: str | None = None
    title: str
    cover_url: str | None = None
    duration_seconds: float | None = None
    status: str
    series_id: str | None = None
    created_at: str
    updated_at: str


def to_inbox_item_response(item: ContentItemRecord) -> InboxItemResponse:
    return InboxItemResponse(
        id=item.id,
        content_type=item.content_type,
        source_provider=item.source_provider,
        source_url=item.source_url,
        canonical_source_id=item.canonical_source_id,
        title=item.title,
        cover_url=item.cover_url,
        duration_seconds=item.duration_seconds,
        status=item.status,
        series_id=item.series_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
