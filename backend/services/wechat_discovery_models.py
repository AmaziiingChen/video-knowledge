from __future__ import annotations

from dataclasses import dataclass, field


class WeChatDiscoveryError(ValueError):
    pass


@dataclass(frozen=True)
class VerifiedArticle:
    url: str
    canonical_source_id: str
    title: str
    source_name: str
    biz: str
    published_at: str
    page_html: str = field(default="", repr=False, compare=False)
