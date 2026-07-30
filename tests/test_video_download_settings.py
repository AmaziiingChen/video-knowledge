import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.video_download_settings import load_video_download_settings, save_video_download_settings


def test_bilibili_video_preference_is_local_and_persistent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")

    assert load_video_download_settings()["auto_download_bilibili_video"] is False
    saved = save_video_download_settings(auto_download_bilibili_video=True)

    assert saved["auto_download_bilibili_video"] is True
    assert load_video_download_settings()["auto_download_bilibili_video"] is True
