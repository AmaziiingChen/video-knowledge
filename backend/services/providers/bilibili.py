from __future__ import annotations

import re
from collections.abc import Callable

from services.bilibili_url import extract_bvid, requested_page_number
from services.downloader import get_video_info
from services.providers.base import ResolvedContent, ResolvedSeries, SubtitleResult


BILIBILI_VIDEO_RE = re.compile(r"https?://(?:www\.)?bilibili\.com/video/(?P<bvid>BV[0-9A-Za-z]+)")
BILIBILI_SHORT_RE = re.compile(r"https?://b23\.tv/[0-9A-Za-z_/-]+")


class BilibiliProvider:
    name = "bilibili"

    def __init__(self, info_loader: Callable[[str, str], dict] | None = None) -> None:
        self._info_loader = info_loader or get_video_info

    def can_handle(self, url: str) -> bool:
        return bool(BILIBILI_VIDEO_RE.search(url) or BILIBILI_SHORT_RE.search(url))

    def normalize_url(self, url: str) -> str:
        url = url.strip()
        match = BILIBILI_VIDEO_RE.search(url)
        if match:
            normalized = f"https://www.bilibili.com/video/{match.group('bvid')}"
            page_number = requested_page_number(url)
            return f"{normalized}?p={page_number}" if page_number > 1 else normalized
        return url

    def resolve(self, url: str) -> ResolvedContent:
        normalized = self.normalize_url(url)
        info = self._info_loader(normalized, self.name) or {}
        bvid = extract_bvid(normalized) or str(info.get("id") or normalized)
        page_number = requested_page_number(normalized)
        canonical_source_id = f"{bvid}:p{page_number}" if page_number > 1 else bvid
        duration = info.get("duration")
        return ResolvedContent(
            provider=self.name,
            content_type="video",
            source_url=normalized,
            canonical_source_id=canonical_source_id,
            title=str(info.get("title") or bvid),
            cover_url=str(info.get("thumbnail") or ""),
            duration_seconds=float(duration) if isinstance(duration, int | float) else None,
            metadata={**info, "page_number": page_number},
        )

    def resolve_series(self, url: str) -> ResolvedSeries | None:
        return None

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None:
        return None
