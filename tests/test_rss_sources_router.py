import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from routers import rss_sources


def test_create_rss_source_maps_auto_analyze_to_service(monkeypatch):
    received = {}

    def create_source(*, feed_url, sync_interval_minutes, auto_analyze):
        received.update(
            feed_url=feed_url,
            sync_interval_minutes=sync_interval_minutes,
            auto_analyze=auto_analyze,
        )
        return {"source": {"id": "rss-source"}, "created_count": 0}

    monkeypatch.setattr(rss_sources, "create_rss_source", create_source)

    result = asyncio.run(
        rss_sources.create_rss_source_endpoint(
            rss_sources.RssSourceRequest(
                feed_url="https://example.com/feed.xml",
                sync_interval_minutes=180,
                auto_analyze=True,
            )
        )
    )

    assert result["source"]["id"] == "rss-source"
    assert received == {
        "feed_url": "https://example.com/feed.xml",
        "sync_interval_minutes": 180,
        "auto_analyze": True,
    }
