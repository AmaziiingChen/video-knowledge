from __future__ import annotations

from services.providers.bilibili import BilibiliProvider
from services.providers.douyin import DouyinProvider
from services.providers.wechat import WechatProvider
from services.providers.xiaohongshu import XiaohongshuProvider
from services.providers.base import SourceProvider


_PROVIDERS: list[SourceProvider] = [
    DouyinProvider(),
    BilibiliProvider(),
    WechatProvider(),
    XiaohongshuProvider(),
]


def list_providers() -> list[SourceProvider]:
    return list(_PROVIDERS)


def get_provider_for_url(url: str) -> SourceProvider | None:
    for provider in _PROVIDERS:
        if provider.can_handle(url):
            return provider
    return None
