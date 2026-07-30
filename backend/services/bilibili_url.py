from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


_BVID_PATTERN = re.compile(r"\b(BV[0-9A-Za-z]+)\b", re.IGNORECASE)


def extract_bvid(url: str) -> str | None:
    match = _BVID_PATTERN.search(url or "")
    return match.group(1) if match else None


def bilibili_video_id_from_page_url(url: str) -> str | None:
    parsed = urlparse(url or "")
    if parsed.hostname not in {"www.bilibili.com", "bilibili.com"}:
        return None
    path_match = re.match(r"^/video/(BV[0-9A-Za-z]+)(?:/|$)", parsed.path, flags=re.IGNORECASE)
    return path_match.group(1) if path_match else None


def requested_page_number(url: str) -> int:
    try:
        raw_page = parse_qs(urlparse(url or "").query).get("p", ["1"])[0]
        page_number = int(raw_page)
        return page_number if page_number > 0 else 1
    except (TypeError, ValueError):
        return 1
