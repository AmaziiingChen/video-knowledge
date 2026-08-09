from __future__ import annotations

from dataclasses import dataclass, field


class CreatorSyncError(ValueError):
    """An input or upstream-response error safe to show in the UI."""


@dataclass(frozen=True)
class CreatorVideo:
    provider: str
    canonical_id: str
    source_url: str
    title: str
    cover_url: str = ""
    duration_seconds: float | None = None
    published_at: str | None = None
    description: str = ""
    author_name: str = ""
    tags: tuple[str, ...] = ()
    stats: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CreatorPreview:
    provider: str
    source_kind: str
    source_url: str
    creator_key: str
    creator_name: str
    videos: list[CreatorVideo]
    creator_avatar_url: str = ""
    creator_description: str = ""
    collection_id: str = ""
    collection_name: str = ""


@dataclass(frozen=True)
class CreatorSyncResult:
    source_id: str
    provider: str
    creator_name: str
    folder_id: str
    discovered_count: int
    created_count: int
    duplicate_count: int
    queued_count: int
    inbox_count: int
    task_ids: list[str]
    content_item_ids: list[str]
