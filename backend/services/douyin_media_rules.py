"""Pure URL, payload, header, and quality rules for Douyin media capture."""
from __future__ import annotations

from urllib.parse import urlparse

from services.source_context import find_douyin_aweme


def looks_like_video_url(url: str) -> bool:
    lowered = url.lower()
    video_markers = (
        "mime_type=video",
        "mime_type%3dvideo",
        "video/tos",
        "/obj/tos-",
        "/tos-cn-",
        "playwm",
        "play_addr",
        "video_id=",
    )
    if is_media_host(url):
        return any(marker in lowered for marker in video_markers)

    # Douyin regularly serves signed video files from rotating CDN domains
    # (for example sjxydc.com). Keep this strict enough to avoid treating an
    # arbitrary page video as content, while accepting those real CDN streams.
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return bool(
        parsed.netloc
        and "/video/tos/" in parsed.path.lower()
        and "mime_type=video" in parsed.query.lower()
        and ("dy_q=" in parsed.query.lower() or "x_r_id=" in parsed.query.lower())
    )


def looks_like_audio_url(url: str) -> bool:
    lowered = url.lower()
    if "media-audio" in lowered:
        return True
    if not is_media_host(url):
        return False
    return "mime_type=audio" in lowered or "mime_type%3daudio" in lowered or "/audio/" in lowered


def is_media_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(
        host == marker or host.endswith(f".{marker}")
        for marker in (
            "douyinvod.com",
            "douyin.com",
            "bytecdn.cn",
            "bytedance.com",
            "snssdk.com",
        )
    )


def browser_media_headers(captured: dict[str, str]) -> dict[str, str]:
    """Forward signed-media headers without cookies or transport metadata."""
    allowed = {"accept", "accept-language", "referer", "user-agent", "origin", "range"}
    headers = {key: value for key, value in captured.items() if key.lower() in allowed}
    headers.setdefault("referer", "https://www.douyin.com/")
    headers.setdefault("accept", "*/*")
    headers["accept-encoding"] = "identity"
    return headers


def needs_media_refresh(status_code: int | None) -> bool:
    """Return whether a captured signed media URL must be collected again."""
    return status_code in {401, 403}


def video_variants(payload: object, video_id: str) -> list[tuple[str, int, str]]:
    """Extract all signed video alternatives advertised for one work."""
    aweme = find_aweme(payload, video_id)
    if not aweme:
        return []
    video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
    variants = video.get("bit_rate") if isinstance(video.get("bit_rate"), list) else []
    candidates: list[tuple[str, int, str]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        try:
            bitrate = int(variant.get("bit_rate") or 0)
        except (TypeError, ValueError):
            continue
        address = variant.get("play_addr") if isinstance(variant.get("play_addr"), dict) else {}
        urls = address.get("url_list") if isinstance(address.get("url_list"), list) else []
        media_url = next(
            (
                url
                for url in urls
                if isinstance(url, str) and url.startswith(("https://", "http://"))
            ),
            "",
        )
        if media_url and bitrate > 0:
            candidates.append((media_url, bitrate, str(variant.get("gear_name") or "")))
    # Older response shapes expose a single progressive stream at play_addr.
    if not candidates:
        address = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
        urls = address.get("url_list") if isinstance(address.get("url_list"), list) else []
        media_url = next(
            (
                url
                for url in urls
                if isinstance(url, str) and url.startswith(("https://", "http://"))
            ),
            "",
        )
        if media_url:
            candidates.append((media_url, 0, "默认"))
    return candidates


def select_video_variant(
    payload: object,
    video_id: str,
    quality: str,
) -> tuple[str, int, str] | None:
    candidates = video_variants(payload, video_id)
    if not candidates:
        return None
    quality = quality if quality in {"low", "standard", "high"} else "standard"
    with_bitrate = [candidate for candidate in candidates if candidate[1] > 0]
    if not with_bitrate:
        return candidates[0]
    if quality == "low":
        return min(with_bitrate, key=lambda item: item[1])
    if quality == "high":
        return max(with_bitrate, key=lambda item: item[1])
    ordered = sorted(with_bitrate, key=lambda item: item[1])
    return ordered[(len(ordered) - 1) // 2]


def lowest_video_variant(payload: object, video_id: str) -> tuple[str, int, str] | None:
    """Compatibility wrapper for callers that explicitly request low quality."""
    return select_video_variant(payload, video_id, "low")


def quality_label(quality: str) -> str:
    return {"low": "省流量", "standard": "标准", "high": "高质量"}.get(quality, "标准")


def is_preferred_bitrate(candidate: int, current: int | None, quality: str) -> bool:
    if current is None:
        return True
    if quality == "low":
        return candidate < current
    if quality == "high":
        return candidate > current
    return abs(candidate - 2_000_000) < abs(current - 2_000_000)


def find_aweme(payload: object, video_id: str) -> dict | None:
    return find_douyin_aweme(payload, video_id)


def is_work_payload_url(url: str) -> bool:
    return "/aweme/v1/web/" in url and any(
        part in url
        for part in ("aweme/detail", "feed", "mix/aweme")
    )


def is_comment_payload_url(url: str) -> bool:
    return "/aweme/v1/web/comment/list" in url or "/web/api/v2/comment/list" in url


__all__ = [
    "browser_media_headers",
    "find_aweme",
    "is_comment_payload_url",
    "is_media_host",
    "is_preferred_bitrate",
    "is_work_payload_url",
    "looks_like_audio_url",
    "looks_like_video_url",
    "lowest_video_variant",
    "needs_media_refresh",
    "quality_label",
    "select_video_variant",
    "video_variants",
]
