from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from main import app
from routers import wechat_feed
from services.content_source_text import ContentSourceText
from services.database import connect, initialize_database, utc_now_iso
from services.repository import ContentRepository, new_id


def _seed_subscription_articles():
    initialize_database()
    with connect() as connection:
        now = utc_now_iso()
        account_id = new_id()
        subscription_id = new_id()
        connection.execute(
            "INSERT INTO wechat_accounts (id, display_name, keychain_ref, status, created_at, updated_at) VALUES (?, '测试账号', ?, 'active', ?, ?)",
            (account_id, f"test:{account_id}", now, now),
        )
        connection.execute(
            """INSERT INTO wechat_subscriptions (id, account_id, fakeid, mp_name, enabled, auto_process, sync_interval_minutes, next_sync_at, created_at, updated_at)
            VALUES (?, ?, 'fakeid-test', '测试公众号', 1, 0, 60, ?, ?, ?)""",
            (subscription_id, account_id, now, now, now),
        )
        repository = ContentRepository(connection)
        article_ids = []
        first_item = None
        for number, discovered_at in ((1, "2026-07-14T01:00:00+00:00"), (2, "2026-07-14T01:00:01+00:00")):
            item = repository.create_content_item(
                source_provider="wechat", content_type="article", title=f"第{number}篇",
                source_url=f"https://mp.weixin.qq.com/s?article={number}", canonical_source_id=f"wechat:{number}", status="to_read",
            )
            first_item = first_item or item
            article_id = new_id()
            article_ids.append(article_id)
            connection.execute(
                """INSERT INTO wechat_subscription_items (id, subscription_id, remote_article_id, source_url, content_item_id, title, published_at, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, '2026-07-13T00:00:00+00:00', ?)""",
                (article_id, subscription_id, f"remote:{article_id}", item.source_url, item.id, item.title, discovered_at),
            )
        connection.commit()
    return subscription_id, article_ids, first_item


def test_feed_paginates_by_stable_discovery_cursor(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    subscription_id, article_ids, _ = _seed_subscription_articles()
    with TestClient(app) as client:
        first = client.get("/api/wechat-feed/articles.json", params={"subscription_id": subscription_id, "limit": 1})
        assert first.status_code == 200
        payload = first.json()
        assert [article["id"] for article in payload["articles"]] == [article_ids[0]]
        assert payload["next_cursor"]
        second = client.get("/api/wechat-feed/articles.json", params={"cursor": payload["next_cursor"]})
        assert [article["id"] for article in second.json()["articles"]] == [article_ids[1]]
        assert client.get("/api/wechat-feed/articles.json", params={"cursor": "not-a-cursor"}).status_code == 400


def test_feed_filters_by_exact_publication_date_and_sorts_newest_first(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    subscription_id, article_ids, _ = _seed_subscription_articles()
    with connect() as connection:
        connection.execute(
            "UPDATE wechat_subscription_items SET published_at = ? WHERE id = ?",
            ("2026-07-23 09:00", article_ids[0]),
        )
        connection.execute(
            "UPDATE wechat_subscription_items SET published_at = ? WHERE id = ?",
            ("2026-07-23 18:00", article_ids[1]),
        )
        connection.commit()
    with TestClient(app) as client:
        response = client.get(
            "/api/wechat-feed/articles.json",
            params={"subscription_id": subscription_id, "published_on": "2026-07-23", "order": "published_desc"},
        )

    assert response.status_code == 200
    assert [article["id"] for article in response.json()["articles"]] == [article_ids[1], article_ids[0]]
    assert response.json()["next_cursor"] is None


def test_feed_exports_markdown_without_needing_an_ai_draft(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    _, article_ids, first_item = _seed_subscription_articles()
    monkeypatch.setattr(
        wechat_feed, "load_content_source_text",
        lambda content_item_id: ContentSourceText(content_item_id, "抓取后的标题", first_item.source_url or "", "文章正文。", "article"),
    )
    with TestClient(app) as client:
        response = client.get(f"/api/wechat-feed/article/{article_ids[0]}.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'publisher: "测试公众号"' in response.text
    assert "# 抓取后的标题" in response.text
    assert "文章正文。" in response.text


def test_feed_exposes_aggregate_and_single_subscription_rss(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    subscription_id, article_ids, _ = _seed_subscription_articles()
    with TestClient(app) as client:
        aggregate = client.get("/api/wechat-feed/rss.xml")
        single = client.get(f"/api/wechat-feed/rss/{subscription_id}.xml")
    assert aggregate.status_code == 200
    assert aggregate.headers["content-type"].startswith("application/rss+xml")
    assert f"<guid isPermaLink=\"false\">{article_ids[0]}</guid>" in aggregate.text
    assert "<pubDate>Mon, 13 Jul 2026 00:00:00 GMT</pubDate>" in aggregate.text
    assert "<title>KnowledgeHub · 测试公众号</title>" in single.text
