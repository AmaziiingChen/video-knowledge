from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from services.creator_sync_models import CreatorSyncError


PERSONAL_SOURCE_KINDS = {"favorites", "likes"}

_BILIBILI_SPACE_PATH_RE = re.compile(r"^/(?P<id>\d+)(?:/upload/video)?/?$")
_BILIBILI_LIST_PATH_RE = re.compile(r"^/(?P<mid>\d+)/lists/(?P<id>\d+)/?$")
_BILIBILI_CHANNEL_PATH_RE = re.compile(r"^/(?P<mid>\d+)/channel/(?P<kind>seriesdetail|collectiondetail)/?$")
_BILIBILI_FAVORITES_PATH_RE = re.compile(r"^/(?P<mid>\d+)/favlist/?$")
_BILIBILI_LIKES_PATH_RE = re.compile(r"^/(?P<mid>\d+)/like/?$")
_DOUYIN_USER_PATH_RE = re.compile(r"^/user/(?P<id>[^/?#]+)/?$")
_DOUYIN_COLLECTION_PATH_RE = re.compile(r"^/collection/(?P<id>\d+)(?:/(?P<position>\d+))?/?$")
_XIAOHONGSHU_PROFILE_PATH_RE = re.compile(r"^/user/profile/(?P<id>[^/?#]+)/?$")


def canonical_creator_url(provider: str, source_kind: str, creator_key: str) -> str:
    if provider == "bilibili":
        if source_kind == "profile":
            # The space root is a personal overview page.  Bilibili can serve
            # it without ever requesting the upload list, which leaves the
            # browser reader with nothing to capture and unnecessarily sends
            # us to the lower-fidelity WBI fallback.  Open the explicit upload
            # tab instead; both URLs retain the same stable creator identity.
            return f"https://space.bilibili.com/{creator_key}/upload/video"
        mid, source_id = creator_key.split(":", 1)
        if source_kind in {"series", "collection"}:
            return f"https://space.bilibili.com/{mid}/lists/{source_id}?type={'series' if source_kind == 'series' else 'season'}"
        if source_kind in {"channel_series", "channel_collection"}:
            kind = "seriesdetail" if source_kind == "channel_series" else "collectiondetail"
            return f"https://space.bilibili.com/{mid}/channel/{kind}?sid={source_id}"
        if source_kind == "favorites":
            # Favorites are ordered by the time they were added.  Explicitly
            # retaining this view makes the personal-favorites sync inspect
            # the newest entries first instead of inheriting a browser's last
            # selected sort order.
            return f"https://space.bilibili.com/{mid}/favlist?fid={source_id}&ftype=create"
        if source_kind == "likes":
            return f"https://space.bilibili.com/{mid}/like"
    if provider == "xiaohongshu" and source_kind == "favorites":
        return f"https://www.xiaohongshu.com/user/profile/{creator_key}?tab=collect"
    if source_kind == "favorites":
        return f"https://www.douyin.com/user/{creator_key}?showSubTab=favorite_folder&showTab=favorite_collection"
    if source_kind == "likes":
        return f"https://www.douyin.com/user/{creator_key}?showTab=like"
    if source_kind == "collection":
        return f"https://www.douyin.com/collection/{creator_key}"
    if source_kind == "profile_compilations":
        return f"https://www.douyin.com/user/{creator_key}?showSubTab=compilation"
    return f"https://www.douyin.com/user/{creator_key}"


def creator_capture_url(source_url: str, *, provider: str, source_kind: str, creator_key: str) -> str:
    """Keep a validated Douyin collection entry page for browser collection context.

    Douyin redirects ``/collection/<id>/<position>`` to a video URL after it
    has established the collection context. The position is not part of the
    subscription identity, but retaining it during navigation makes the
    browser issue the collection request in the first place.
    """
    if provider != "douyin" or source_kind != "collection":
        return canonical_creator_url(provider, source_kind, creator_key)
    parsed = urlparse(source_url)
    match = _DOUYIN_COLLECTION_PATH_RE.fullmatch(parsed.path)
    if match and match.group("id") == creator_key and match.group("position"):
        return f"https://www.douyin.com/collection/{creator_key}/{match.group('position')}"
    return canonical_creator_url(provider, source_kind, creator_key)


def parse_creator_url(source_url: str) -> tuple[str, str, str]:
    parsed = urlparse(source_url)
    if parsed.scheme != "https":
        raise CreatorSyncError("链接必须使用 HTTPS")
    host = (parsed.hostname or "").lower()
    if host == "space.bilibili.com":
        if match := _BILIBILI_SPACE_PATH_RE.fullmatch(parsed.path):
            return "bilibili", "profile", match.group("id")
        query = parse_qs(parsed.query)
        if match := _BILIBILI_LIST_PATH_RE.fullmatch(parsed.path):
            source_kind = "series" if query.get("type", [""])[0] == "series" else "collection"
            return "bilibili", source_kind, f"{match.group('mid')}:{match.group('id')}"
        if match := _BILIBILI_CHANNEL_PATH_RE.fullmatch(parsed.path):
            sid = query.get("sid", [""])[0]
            if sid.isdigit():
                source_kind = "channel_series" if match.group("kind") == "seriesdetail" else "channel_collection"
                return "bilibili", source_kind, f"{match.group('mid')}:{sid}"
        if match := _BILIBILI_FAVORITES_PATH_RE.fullmatch(parsed.path):
            fid = query.get("fid", [""])[0]
            if fid.isdigit():
                return "bilibili", "favorites", f"{match.group('mid')}:{fid}"
        if match := _BILIBILI_LIKES_PATH_RE.fullmatch(parsed.path):
            return "bilibili", "likes", f"{match.group('mid')}:liked"
    if host in {"douyin.com", "www.douyin.com"}:
        if match := _DOUYIN_COLLECTION_PATH_RE.fullmatch(parsed.path):
            return "douyin", "collection", match.group("id")
        if match := _DOUYIN_USER_PATH_RE.fullmatch(parsed.path):
            query = parse_qs(parsed.query)
            active_tab = str(query.get("showTab", [""])[0]).lower()
            active_sub_tab = str(query.get("showSubTab", [""])[0]).lower()
            if active_tab in {"like", "liked"}:
                return "douyin", "likes", match.group("id")
            if active_tab in {"favorite", "favorite_collection"} or active_sub_tab == "favorite_folder":
                return "douyin", "favorites", match.group("id")
            if query.get("showSubTab", [""])[0] == "compilation":
                return "douyin", "profile_compilations", match.group("id")
            return "douyin", "profile", match.group("id")
    if host in {"xiaohongshu.com", "www.xiaohongshu.com"}:
        if match := _XIAOHONGSHU_PROFILE_PATH_RE.fullmatch(parsed.path):
            query = parse_qs(parsed.query)
            active_tab = str(
                query.get("tab", query.get("showTab", query.get("section", [""])))[0]
            ).lower()
            # The web profile currently labels the favorites tab `fav`; older
            # shared links have used the other spellings below. They all map
            # to the same current-account favorites pipeline.
            if active_tab in {"fav", "collect", "collection", "favorite", "favorites"}:
                return "xiaohongshu", "favorites", match.group("id")
            raise CreatorSyncError("小红书目前仅支持“我的收藏”链接；请从个人主页的收藏页复制链接")
    raise CreatorSyncError("仅支持抖音/B站的主页、合集、收藏夹或喜欢列表，以及小红书“我的收藏”链接")
