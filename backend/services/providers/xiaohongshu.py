from __future__ import annotations

import re

from services.providers.base import ResolvedContent, ResolvedSeries, SubtitleResult
from services.xiaohongshu_client import normalize_note_url, note_id_from_url


_NOTE_RE = re.compile(r"https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/[^/?#]+", re.IGNORECASE)


class XiaohongshuProvider:
    name = "xiaohongshu"

    def can_handle(self, url: str) -> bool:
        return bool(_NOTE_RE.search(url or ""))

    def normalize_url(self, url: str) -> str:
        return normalize_note_url(url)

    def resolve(self, url: str) -> ResolvedContent:
        normalized = self.normalize_url(url)
        return ResolvedContent(
            provider=self.name,
            content_type="article",
            source_url=normalized,
            canonical_source_id=note_id_from_url(normalized),
            title="小红书图文",
        )

    def resolve_series(self, url: str) -> ResolvedSeries | None:
        return None

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None:
        return None
