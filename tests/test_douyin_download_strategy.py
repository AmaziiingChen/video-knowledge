import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.downloader import DownloadResult, _download_douyin


def test_douyin_download_falls_back_to_application_browser(tmp_path: Path):
    browser_failure = DownloadResult(success=False, error="浏览器未捕获媒体")

    with (
        patch(
            "services.downloader._download_douyin_via_public_metadata",
            return_value=DownloadResult(success=False, error="直连元数据未提供可用视频地址"),
        ) as direct,
        patch("services.downloader._download_douyin_via_browser", return_value=browser_failure) as browser,
    ):
        result = _download_douyin("https://www.douyin.com/video/123456", tmp_path)

    assert result is browser_failure
    direct.assert_called_once()
    browser.assert_called_once()
