from unittest.mock import Mock, patch

import httpx

from config import settings
from services.update_checker import (
    OFFICIAL_GITHUB_RELEASE_API_URL,
    OFFICIAL_RELEASE_MANIFEST_URL,
    check_for_update,
)


def test_update_check_is_disabled_without_public_manifest_url():
    with patch.object(settings, "release_manifest_url", ""):
        assert check_for_update() == {"state": "disabled", "current_version": settings.app_version}


def test_update_check_returns_the_official_release_page_for_newer_version():
    response = Mock()
    response.json.return_value = {
        "latest_version": "1.2.0",
        "download_page_url": "https://github.com/AmaziiingChen/video-knowledge/releases/tag/v1.2.0",
        "release_notes": "修复稳定性问题",
    }
    with patch.object(settings, "app_version", "1.1.0"), patch.object(
        settings, "release_manifest_url", OFFICIAL_RELEASE_MANIFEST_URL
    ), patch("services.update_checker.httpx.get", return_value=response):
        assert check_for_update() == {
            "state": "available",
            "current_version": "1.1.0",
            "latest_version": "1.2.0",
            "download_page_url": "https://github.com/AmaziiingChen/video-knowledge/releases/tag/v1.2.0",
            "release_notes": "修复稳定性问题",
        }


def test_update_check_rejects_a_non_official_release_page():
    response = Mock()
    response.json.return_value = {"latest_version": "1.2.0", "download_page_url": "http://example.com/download"}
    with patch.object(settings, "app_version", "1.1.0"), patch.object(
        settings, "release_manifest_url", OFFICIAL_RELEASE_MANIFEST_URL
    ), patch("services.update_checker.httpx.get", return_value=response):
        assert check_for_update() == {"state": "invalid", "current_version": "1.1.0"}


def test_update_check_rejects_a_manifest_url_outside_the_compiled_allowlist():
    with patch.object(settings, "release_manifest_url", "https://workers.dev/v1/manifest.json"):
        assert check_for_update() == {"state": "invalid", "current_version": settings.app_version}


def test_update_check_rejects_a_release_page_with_a_port_or_query():
    response = Mock()
    response.json.return_value = {
        "latest_version": "1.2.0",
        "download_page_url": "https://github.com:443/AmaziiingChen/video-knowledge/releases/tag/v1.2.0?x=1",
    }
    with patch.object(settings, "app_version", "1.1.0"), patch.object(
        settings, "release_manifest_url", OFFICIAL_RELEASE_MANIFEST_URL
    ), patch("services.update_checker.httpx.get", return_value=response):
        assert check_for_update() == {"state": "invalid", "current_version": "1.1.0"}


def test_update_check_falls_back_to_the_official_github_release_api():
    github_response = Mock()
    github_response.json.return_value = {
        "tag_name": "v1.2.0",
        "html_url": "https://github.com/AmaziiingChen/video-knowledge/releases/tag/v1.2.0",
        "body": "修复更新通道。",
    }
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url == OFFICIAL_RELEASE_MANIFEST_URL:
            raise httpx.ConnectError("workers.dev unavailable")
        return github_response

    with patch.object(settings, "app_version", "1.1.0"), patch.object(
        settings, "release_manifest_url", OFFICIAL_RELEASE_MANIFEST_URL
    ), patch("services.update_checker.httpx.get", side_effect=get):
        assert check_for_update() == {
            "state": "available",
            "current_version": "1.1.0",
            "latest_version": "1.2.0",
            "download_page_url": "https://github.com/AmaziiingChen/video-knowledge/releases/tag/v1.2.0",
            "release_notes": "修复更新通道。",
        }

    assert calls[0][0] == OFFICIAL_RELEASE_MANIFEST_URL
    assert calls[1][0] == OFFICIAL_GITHUB_RELEASE_API_URL
