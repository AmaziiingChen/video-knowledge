from pathlib import Path
from unittest.mock import patch

from config import settings
from services.cache import cache_dir_for_url, read_cache_meta
from services.pipeline_runner import run_pipeline_sync


def test_pipeline_failure_is_persisted_in_the_active_source_cache(tmp_path: Path) -> None:
    original_data_dir = settings.data_dir
    settings.data_dir = tmp_path
    source_url = "https://mp.weixin.qq.com/s/cache-failure"
    try:
        with patch("services.pipeline_runner.fetch_article", side_effect=RuntimeError("正文抓取失败")):
            response = run_pipeline_sync(source_url, whisper_model="small", use_cache=True)

        assert response.success is False
        assert response.step == "info"
        assert response.error == "正文抓取失败"
        cache_dir = cache_dir_for_url(source_url)
        cache_meta = read_cache_meta(cache_dir)
        assert cache_meta["cache_key"] == cache_dir.name
        assert cache_meta["pipeline_error"] == "正文抓取失败"
        assert cache_meta["pipeline_status"] == "failed"
        assert cache_meta["platform"] == "wechat"
        assert cache_meta["source_url"] == source_url
    finally:
        settings.data_dir = original_data_dir
