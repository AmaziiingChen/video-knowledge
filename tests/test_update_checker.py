from unittest.mock import Mock, patch

from config import settings
from services.update_checker import check_for_update


def test_update_check_is_disabled_without_public_manifest_url():
    with patch.object(settings, "release_manifest_url", ""):
        assert check_for_update() == {"state": "disabled", "current_version": settings.app_version}


def test_update_check_returns_manual_download_page_for_newer_version():
    response = Mock()
    response.json.return_value = {
        "latest_version": "1.2.0",
        "download_page_url": "https://downloads.example.com/knowledgehub/",
        "release_notes": "修复稳定性问题",
    }
    with patch.object(settings, "app_version", "1.1.0"), patch.object(
        settings, "release_manifest_url", "https://downloads.example.com/manifest.json"
    ), patch("services.update_checker.httpx.get", return_value=response):
        assert check_for_update() == {
            "state": "available",
            "current_version": "1.1.0",
            "latest_version": "1.2.0",
            "download_page_url": "https://downloads.example.com/knowledgehub/",
            "release_notes": "修复稳定性问题",
        }


def test_update_check_rejects_non_https_download_page():
    response = Mock()
    response.json.return_value = {"latest_version": "1.2.0", "download_page_url": "http://example.com/download"}
    with patch.object(settings, "app_version", "1.1.0"), patch.object(
        settings, "release_manifest_url", "https://downloads.example.com/manifest.json"
    ), patch("services.update_checker.httpx.get", return_value=response):
        assert check_for_update() == {"state": "invalid", "current_version": "1.1.0"}
