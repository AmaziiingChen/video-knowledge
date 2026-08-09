from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.creator_sync_models import CreatorVideo


DEFAULT_PAGE_SIZE = 20


def parse_creator_page(payload: dict[str, Any], *, provider: str) -> tuple[list[CreatorVideo], str, int | None, bool]:
    if provider == "douyin":
        payload = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        rows = payload.get("aweme_list") or payload.get("aweme_list_data") or []
        if not isinstance(rows, list):
            rows = []
        videos = [douyin_video(row) for row in rows if isinstance(row, dict)]
        videos = [video for video in videos if video is not None]
        author = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        creator_name = str(author.get("nickname") or "")
        if not creator_name and rows and isinstance(rows[0], dict):
            creator_name = str(((rows[0].get("author") or {}).get("nickname")) or "")
        next_cursor = as_int(payload.get("max_cursor") or payload.get("cursor"))
        return videos, creator_name, next_cursor, bool(payload.get("has_more"))

    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    data = root.get("list") if isinstance(root.get("list"), dict) else root
    rows = data.get("vlist") or data.get("list") or data.get("archives") or data.get("medias") or root.get("archives") or root.get("medias") or []
    if not isinstance(rows, list):
        rows = []
    videos = [bilibili_video(row) for row in rows if isinstance(row, dict)]
    videos = [video for video in videos if video is not None]
    meta = root.get("meta") if isinstance(root.get("meta"), dict) else {}
    creator_name = str(data.get("owner_name") or data.get("name") or meta.get("owner_name") or meta.get("author") or "")
    if not creator_name and rows and isinstance(rows[0], dict):
        creator_name = bilibili_author_name(rows[0])
    page_info = data.get("page") if isinstance(data.get("page"), dict) else {}
    page_number = int(page_info.get("pn") or 1)
    page_size = int(page_info.get("ps") or len(rows) or DEFAULT_PAGE_SIZE)
    total_items = int(page_info.get("count") or 0)
    explicit_has_more = data.get("has_more")
    has_more = bool(explicit_has_more) if isinstance(explicit_has_more, (bool, int)) else bool(rows) and (not total_items or page_number * page_size < total_items)
    return videos, creator_name, None, has_more


def douyin_video(row: dict[str, Any]) -> CreatorVideo | None:
    video_id = str(row.get("aweme_id") or row.get("id") or "").strip()
    if not video_id:
        return None
    video = row.get("video") if isinstance(row.get("video"), dict) else {}
    cover = video.get("cover") if isinstance(video.get("cover"), dict) else {}
    cover_list = cover.get("url_list") if isinstance(cover.get("url_list"), list) else []
    published = timestamp_iso(row.get("create_time"))
    author = row.get("author") if isinstance(row.get("author"), dict) else {}
    statistics = row.get("statistics") if isinstance(row.get("statistics"), dict) else {}
    return CreatorVideo(
        provider="douyin",
        canonical_id=video_id,
        source_url=f"https://www.douyin.com/video/{video_id}",
        title=str(row.get("desc") or video_id),
        cover_url=str(cover_list[0]) if cover_list else "",
        duration_seconds=as_float(video.get("duration"), scale=1000),
        published_at=published,
        description=str(row.get("desc") or ""),
        author_name=str(author.get("nickname") or ""),
        tags=tuple(douyin_tags(row)),
        stats=normalized_stats(statistics, {
            "play": "play_count", "like": "digg_count", "comment": "comment_count",
            "favorite": "collect_count", "share": "share_count",
        }),
    )


def bilibili_video(row: dict[str, Any]) -> CreatorVideo | None:
    video_id = str(row.get("bvid") or row.get("bv_id") or "").strip()
    if not video_id:
        return None
    cover = row.get("pic") or row.get("cover")
    if isinstance(cover, str) and cover.startswith("//"):
        cover = f"https:{cover}"
    stats_source = dict(row)
    if isinstance(row.get("stat"), dict):
        stats_source.update(row["stat"])
    return CreatorVideo(
        provider="bilibili",
        canonical_id=video_id,
        source_url=f"https://www.bilibili.com/video/{video_id}",
        title=str(row.get("title") or video_id),
        cover_url=str(cover or ""),
        duration_seconds=duration_from_bilibili(row),
        published_at=timestamp_iso(row.get("created") or row.get("pubdate")),
        description=str(row.get("description") or row.get("desc") or ""),
        author_name=bilibili_author_name(row),
        tags=tuple(string_list(row.get("tags"))),
        stats=normalized_stats(
            stats_source,
            {
                "play": ("view", "play"), "like": "like", "coin": "coin", "favorite": "favorite",
                "share": "share", "comment": ("reply", "video_review", "comment"), "danmaku": "danmaku",
            },
        ),
    )


def bilibili_author_name(row: dict[str, Any]) -> str:
    owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
    author = row.get("author")
    return str(owner.get("name") or author or row.get("owner_name") or "")


def douyin_tags(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    challenge = row.get("cha_list") or row.get("challenge")
    if isinstance(challenge, list):
        values.extend(str(item.get("cha_name") or item.get("title") or "") for item in challenge if isinstance(item, dict))
    if isinstance(challenge, dict):
        values.append(str(challenge.get("cha_name") or challenge.get("title") or ""))
    return string_list(values)


def string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = str(item.get("name") or item.get("tag_name") or "") if isinstance(item, dict) else str(item or "")
        if text.strip() and text.strip() not in result:
            result.append(text.strip())
    return result[:40]


def normalized_stats(raw: Any, aliases: dict[str, str | tuple[str, ...]]) -> dict[str, int]:
    source = raw if isinstance(raw, dict) else {}
    values: dict[str, int] = {}
    for name, aliases_for_value in aliases.items():
        keys = (aliases_for_value,) if isinstance(aliases_for_value, str) else aliases_for_value
        value = next((parsed for key in keys if (parsed := as_int(source.get(key))) is not None and parsed >= 0), None)
        if value is not None:
            values[name] = value
    return values


def collection_name_from_payload(payload: dict[str, Any]) -> str:
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    meta = root.get("meta") if isinstance(root.get("meta"), dict) else {}
    for value in (meta.get("name"), meta.get("title"), root.get("season_name"), root.get("title")):
        if str(value or "").strip():
            return str(value).strip()
    return ""


def duration_from_bilibili(row: dict[str, Any]) -> float | None:
    raw = row.get("length") or row.get("duration")
    if isinstance(raw, str) and ":" in raw:
        try:
            seconds = 0
            for part in raw.split(":"):
                seconds = seconds * 60 + int(part)
            return float(seconds)
        except ValueError:
            return None
    return as_float(raw)


def as_float(value: Any, *, scale: float = 1) -> float | None:
    try:
        return float(value) / scale if value is not None else None
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def timestamp_iso(value: Any) -> str | None:
    timestamp = as_int(value)
    if timestamp is None or timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
