from __future__ import annotations

import re

from services.providers.base import ResolvedContent, ResolvedSeries, SubtitleResult


WECHAT_ARTICLE_RE = re.compile(r"https?://mp\.weixin\.qq\.com/[^\s]+")


class WechatProvider:
    name = "wechat"

    def can_handle(self, url: str) -> bool:
        return bool(WECHAT_ARTICLE_RE.search(url))

    def normalize_url(self, url: str) -> str:
        return url.strip().rstrip("，。；、,.!?)）]")

    def resolve(self, url: str) -> ResolvedContent:
        normalized = self.normalize_url(url)
        return ResolvedContent(
            provider=self.name,
            content_type="article",
            source_url=normalized,
            canonical_source_id=normalized,
            title=normalized,
        )

    def resolve_series(self, url: str) -> ResolvedSeries | None:
        return None

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None:
        return None
