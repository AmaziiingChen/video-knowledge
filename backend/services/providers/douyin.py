from __future__ import annotations

import re
from collections.abc import Callable

from services.downloader import get_video_info
from services.providers.base import ResolvedContent, ResolvedSeries, SubtitleResult


DOUYIN_SHORT_RE = re.compile(r"https?://v\.douyin\.com/[0-9A-Za-z_/-]+")
DOUYIN_VIDEO_ID_RE = re.compile(r"(?:/video/|/note/|modal_id=)(?P<id>\d+)")


class DouyinProvider:
    name = "douyin"

    def __init__(self, info_loader: Callable[[str, str], dict] | None = None) -> None:
        self._info_loader = info_loader or get_video_info

    def can_handle(self, url: str) -> bool:
        return bool(DOUYIN_SHORT_RE.search(url) or DOUYIN_VIDEO_ID_RE.search(url))

    def normalize_url(self, url: str) -> str:
        return url.strip()

    def resolve(self, url: str) -> ResolvedContent:
        normalized = self.normalize_url(url)
        info = self._info_loader(normalized, self.name) or {}
        canonical_id = _extract_douyin_id(normalized) or str(info.get("id") or normalized)
        duration = info.get("duration")
        return ResolvedContent(
            provider=self.name,
            content_type="video",
            source_url=normalized,
            canonical_source_id=canonical_id,
            title=str(info.get("title") or canonical_id),
            cover_url=str(info.get("thumbnail") or info.get("cover") or ""),
            duration_seconds=float(duration) if isinstance(duration, int | float) else None,
            metadata=info,
        )

    def resolve_series(self, url: str) -> ResolvedSeries | None:
        return None

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None:
        return None


def _extract_douyin_id(url: str) -> str | None:
    match = DOUYIN_VIDEO_ID_RE.search(url)
    return match.group("id") if match else None

