from __future__ import annotations

import re

from services.providers.base import ResolvedContent, ResolvedSeries, SubtitleResult
from services.xiaohongshu_client import normalize_note_url, note_id_from_url


# Search-result note URLs use the same durable note ID and xsec token as a
# normal explore URL. The parser and safe link normalizer already accept this
# official form, so provider dispatch must not reject it before normalization.
_NOTE_RE = re.compile(r"https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item|search_result)/[^/?#]+", re.IGNORECASE)


class XiaohongshuProvider:
    name = "xiaohongshu"

    def can_handle(self, url: str) -> bool:
        return bool(_NOTE_RE.search(url or ""))

    def normalize_url(self, url: str) -> str:
        return normalize_note_url(url)

    def resolve(self, url: str) -> ResolvedContent:
        normalized = self.normalize_url(url)
        note_id = note_id_from_url(normalized)
        return ResolvedContent(
            provider=self.name,
            content_type="article",
            source_url=normalized,
            canonical_source_id=note_id,
            title=f"小红书图文 · {note_id[:12]}",
        )

    def resolve_series(self, url: str) -> ResolvedSeries | None:
        return None

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None:
        return None
