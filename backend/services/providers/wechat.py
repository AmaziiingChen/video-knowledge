from __future__ import annotations

from services.providers.base import ResolvedContent, ResolvedSeries, SubtitleResult
from services.wechat_urls import (
    canonical_wechat_article_id,
    is_wechat_article_url,
    normalize_wechat_url,
)


class WechatProvider:
    name = "wechat"

    def can_handle(self, url: str) -> bool:
        return is_wechat_article_url(url)

    def normalize_url(self, url: str) -> str:
        return normalize_wechat_url(url)

    def resolve(self, url: str) -> ResolvedContent:
        normalized = self.normalize_url(url)
        return ResolvedContent(
            provider=self.name,
            content_type="article",
            source_url=normalized,
            canonical_source_id=canonical_wechat_article_id(normalized),
            title=normalized,
        )

    def resolve_series(self, url: str) -> ResolvedSeries | None:
        return None

    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None:
        return None
