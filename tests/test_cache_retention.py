import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.article_preview import ARTICLE_NORMALIZER_VERSION
from services.cache import cache_dir_for_url, read_cache_meta, write_cache_meta, write_cached_transcript
from services.cache_retention import prune_stale_cache
from services.database import connect, initialize_database
from services.repository import ContentRepository


def _create_old_item(url: str, *, provider: str, content_type: str) -> None:
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider=provider,
            content_type=content_type,
            source_url=url,
            canonical_source_id=url,
            title="旧内容",
        )
        connection.execute(
            "UPDATE content_items SET created_at = '2026-01-01T00:00:00+00:00' WHERE id = ?",
            (item.id,),
        )
        connection.commit()


def test_retention_prunes_large_assets_but_keeps_article_text_and_video_transcript(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()

    article_url = "https://example.edu/article/old"
    _create_old_item(article_url, provider="campus", content_type="article")
    article_cache = cache_dir_for_url(article_url)
    (article_cache / "images").mkdir(parents=True)
    (article_cache / "images" / "large.jpg").write_bytes(b"x" * 100_000)
    write_cache_meta(article_cache, {
        "source_url": article_url,
        "platform": "campus",
        "article_info": {
            "title": "旧通知",
            "body_text": "需要长期保留的通知文字",
            "body_html": """
                <div style="width: 1200px">
                  <p><strong>一、名单</strong></p>
                  <table><tr><th>姓名</th><th>结果</th></tr>
                  <tr><td rowspan="2">张同学</td><td>通过</td></tr></table>
                  <img src="https://example.edu/large.jpg" data-local-media-path="/cache/images/large.jpg">
                </div>
            """,
            "images": ["https://example.edu/large.jpg"],
        },
    })

    video_url = "https://example.com/video/old"
    _create_old_item(video_url, provider="bilibili", content_type="video")
    video_cache = cache_dir_for_url(video_url)
    write_cache_meta(video_cache, {"source_url": video_url, "platform": "bilibili"})
    write_cached_transcript(video_cache, "small", "需要保留的转写")
    (video_cache / "video.mp4").write_bytes(b"v" * 100_000)

    result = prune_stale_cache(now=datetime(2026, 7, 16, tzinfo=timezone.utc))

    assert result.pruned == 2
    assert result.freed_bytes > 150_000
    article_meta = read_cache_meta(article_cache)
    assert article_meta["article_info"]["body_text"] == "需要长期保留的通知文字"
    assert article_meta["article_info"]["body_html"] == ""
    assert article_meta["article_info"]["normalized_html_version"] == ARTICLE_NORMALIZER_VERSION
    assert "<table>" in article_meta["article_info"]["normalized_html"]
    assert 'rowspan="2"' in article_meta["article_info"]["normalized_html"]
    assert 'src="https://example.edu/large.jpg"' in article_meta["article_info"]["normalized_html"]
    assert "data-local-media-path" not in article_meta["article_info"]["normalized_html"]
    assert not (article_cache / "images").exists()
    assert (video_cache / "transcript_small.txt").read_text(encoding="utf-8") == "需要保留的转写"
    assert not (video_cache / "video.mp4").exists()
    assert read_cache_meta(video_cache)["video_cache_status"] == "expired"


def test_retention_compacts_attachment_or_image_only_article_without_body_text(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    article_url = "https://example.edu/article/image-only"
    _create_old_item(article_url, provider="campus", content_type="article")
    cache_dir = cache_dir_for_url(article_url)
    (cache_dir / "images").mkdir(parents=True)
    (cache_dir / "images" / "notice.jpg").write_bytes(b"x" * 100_000)
    write_cache_meta(cache_dir, {
        "source_url": article_url,
        "platform": "campus",
        "article_info": {
            "title": "图片通知",
            "body_text": "",
            "body_html": '<p><img src="https://example.edu/notice.jpg" data-local-media-path="/cache/notice.jpg"></p>',
            "images": ["https://example.edu/notice.jpg"],
            "attachments": [{"name": "报名表", "url": "https://example.edu/form.docx"}],
        },
    })

    prune_stale_cache(now=datetime(2026, 7, 16, tzinfo=timezone.utc))

    article_info = read_cache_meta(cache_dir)["article_info"]
    assert article_info["body_html"] == ""
    assert 'src="https://example.edu/notice.jpg"' in article_info["normalized_html"]
    assert article_info["attachments"][0]["name"] == "报名表"
    assert not (cache_dir / "images").exists()
