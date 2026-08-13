"""Read a public release manifest for the manual-update prompt."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from config import settings

OFFICIAL_RELEASE_MANIFEST_URL = (
    "https://knowledgehub-release-manifest.knowledgehub4chen.workers.dev/v1/manifest.json"
)
OFFICIAL_RELEASE_PAGE_PREFIX = "https://github.com/AmaziiingChen/video-knowledge/releases/tag/v"


def _version_key(value: str) -> tuple[int, ...] | None:
    match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", str(value).strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _is_official_release_page(value: object, latest_version: str) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
        return (
            parsed.scheme == "https"
            and parsed.netloc == "github.com"
            and not parsed.username
            and parsed.port is None
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and parsed.path == f"/AmaziiingChen/video-knowledge/releases/tag/v{latest_version}"
        )
    except ValueError:
        return False


def _manifest_status(payload: dict[str, Any]) -> dict[str, object]:
    latest_version = str(payload.get("latest_version") or "").strip()
    current_key = _version_key(settings.app_version)
    latest_key = _version_key(latest_version)
    download_page_url = str(payload.get("download_page_url") or "").strip()
    if current_key is None or latest_key is None or not _is_official_release_page(download_page_url, latest_version):
        return {"state": "invalid", "current_version": settings.app_version}
    return {
        "state": "available" if latest_key > current_key else "up_to_date",
        "current_version": settings.app_version,
        "latest_version": latest_version,
        "download_page_url": download_page_url if latest_key > current_key else "",
        "release_notes": str(payload.get("release_notes") or "")[:500],
    }


def check_for_update() -> dict[str, object]:
    manifest_url = settings.release_manifest_url.strip()
    if not manifest_url:
        return {"state": "disabled", "current_version": settings.app_version}
    if manifest_url != OFFICIAL_RELEASE_MANIFEST_URL:
        return {"state": "invalid", "current_version": settings.app_version}
    try:
        response = httpx.get(manifest_url, timeout=5.0, follow_redirects=False)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return {"state": "unavailable", "current_version": settings.app_version}
    if not isinstance(payload, dict):
        return {"state": "invalid", "current_version": settings.app_version}
    return _manifest_status(payload)
