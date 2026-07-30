from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ResolvedContent:
    provider: str
    content_type: str
    source_url: str
    canonical_source_id: str
    title: str = ""
    cover_url: str = ""
    duration_seconds: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedSeries:
    provider: str
    source_url: str
    canonical_source_id: str
    title: str
    cover_url: str = ""
    items: list[ResolvedContent] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SubtitleResult:
    source: str
    path: Path | None = None
    segments: list[dict] = field(default_factory=list)
    text: str = ""


class SourceProvider(Protocol):
    name: str

    def can_handle(self, url: str) -> bool: ...

    def normalize_url(self, url: str) -> str: ...

    def resolve(self, url: str) -> ResolvedContent: ...

    def resolve_series(self, url: str) -> ResolvedSeries | None: ...

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None: ...

