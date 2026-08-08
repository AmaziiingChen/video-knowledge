from __future__ import annotations

from types import SimpleNamespace

from config import settings
from services import database, wechat_article_candidate, wechat_discovery
from services.content_index import ensure_manual_wechat_folder


ALBUM_URL = "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzAlbum&album_id=album-1"
KNOWN_URL = "https://mp.weixin.qq.com/s?__biz=MzAlbum&mid=10&idx=1"


def _configure_database(tmp_path, monkeypatch):
    db_path = tmp_path / "album-subscriptions.db"
    with database.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                source_provider TEXT,
                source_url TEXT,
                canonical_source_id TEXT,
                status TEXT,
                title TEXT,
                source_name TEXT,
                published_at TEXT,
                updated_at TEXT,
                UNIQUE(source_provider, canonical_source_id)
            )
            """
        )
        database._migration_087_wechat_public_discovery(connection)
        database._migration_088_wechat_seed_discovery_review(connection)
        database._migration_089_wechat_album_subscriptions(connection)
        connection.commit()
    monkeypatch.setattr(wechat_discovery, "ensure_database_initialized", lambda: None)
    monkeypatch.setattr(wechat_discovery, "connect", lambda: database.connect(db_path))
    return db_path


def test_album_import_can_enable_persisted_automatic_detection(tmp_path, monkeypatch):
    _configure_database(tmp_path, monkeypatch)

    run = wechat_discovery.create_discovery_run(
        ALBUM_URL,
        auto_analyze=True,
        subscribe_album=True,
        sync_interval_minutes=720,
    )
    sources = wechat_discovery.list_public_album_sources()

    assert len(sources) == 1
    assert sources[0]["id"] == run["source_id"]
    assert sources[0]["enabled"] is True
    assert sources[0]["auto_analyze"] is True
    assert sources[0]["sync_interval_minutes"] == 720
    assert sources[0]["next_sync_at"]

    updated = wechat_discovery.update_public_album_source(
        sources[0]["id"],
        enabled=False,
        auto_analyze=False,
        sync_interval_minutes=1440,
    )

    assert updated["enabled"] is False
    assert updated["auto_analyze"] is False
    assert updated["sync_interval_minutes"] == 1440
    assert updated["next_sync_at"] is None


def test_incremental_album_run_stops_after_a_fully_known_page(tmp_path, monkeypatch):
    db_path = _configure_database(tmp_path, monkeypatch)
    initial_run = wechat_discovery.create_discovery_run(
        ALBUM_URL,
        subscribe_album=True,
    )
    with database.connect(db_path) as connection:
        connection.execute(
            "UPDATE wechat_discovery_runs SET status='succeeded' WHERE id=?",
            (initial_run["id"],),
        )
        connection.execute(
            """
            INSERT INTO content_items (
                id, source_provider, source_url, canonical_source_id, status,
                title, source_name, published_at, updated_at
            ) VALUES ('known', 'wechat', ?, 'wechat:MzAlbum:10:1', 'to_read', '', '', '', '')
            """,
            (KNOWN_URL,),
        )
        connection.commit()

    requested = []
    def fetch_album_payload(url, *, referer):
        requested.append(url)
        return {
            "getalbum_resp": {
                "continue_flag": 1,
                "article_list": [
                    {
                        "title": "已有文章",
                        "url": KNOWN_URL,
                        "msgid": "10",
                        "itemidx": "1",
                    }
                ],
            }
        }

    monkeypatch.setattr(wechat_discovery, "_fetch_album_payload", fetch_album_payload)
    monkeypatch.setattr(wechat_discovery, "_prepare_album_folder", lambda run_id: "album-folder")
    run = wechat_discovery.create_album_sync_run(initial_run["source_id"])

    result = wechat_discovery.run_wechat_discovery(run["id"])

    assert result["status"] == "succeeded"
    assert result["candidate_count"] == 0
    assert result["imported_count"] == 0
    assert len(requested) == 1


def test_due_album_sources_enter_the_existing_background_queue(tmp_path, monkeypatch):
    db_path = _configure_database(tmp_path, monkeypatch)
    initial_run = wechat_discovery.create_discovery_run(ALBUM_URL, subscribe_album=True)
    with database.connect(db_path) as connection:
        connection.execute(
            "UPDATE wechat_discovery_runs SET status='succeeded' WHERE id=?",
            (initial_run["id"],),
        )
        connection.execute(
            "UPDATE wechat_public_sources SET next_sync_at='2000-01-01T00:00:00+00:00'",
        )
        connection.commit()

    queued = []

    def create_source_sync(request, **kwargs):
        queued.append((request, kwargs))
        return SimpleNamespace(task_id="task-1")

    from services.task_manager import task_manager

    monkeypatch.setattr(task_manager, "create_source_sync", create_source_sync)

    run_ids = wechat_discovery.enqueue_due_album_sources()

    assert len(run_ids) == 1
    assert queued[0][0]["kind"] == "wechat_public_discovery"
    assert queued[0][0]["source_id"] == initial_run["source_id"]
    assert queued[0][1]["execution_mode"] == "background"
    scheduled_run = wechat_discovery.get_discovery_run(run_ids[0])
    assert scheduled_run["task_id"] == "task-1"


def test_album_import_places_articles_under_the_named_album_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    database.initialize_database()
    article_url = "https://mp.weixin.qq.com/s?__biz=MzAlbum&mid=20&idx=1"
    monkeypatch.setattr(
        wechat_discovery,
        "_fetch_album_payload",
        lambda url, *, referer: {
            "getalbum_resp": {
                "base_info": {"title": "技大之星", "nickname": "深圳技术大学"},
                "continue_flag": 0,
                "article_list": [
                    {
                        "title": "合集文章",
                        "url": article_url,
                        "msgid": "20",
                        "itemidx": "1",
                    }
                ],
            }
        },
    )
    monkeypatch.setattr(
        wechat_discovery,
        "_verify_article",
        lambda url, *, expected_biz="": wechat_discovery.VerifiedArticle(
            url=url,
            canonical_source_id="wechat:MzAlbum:20:1",
            title="合集文章",
            source_name="深圳技术大学",
            biz="MzAlbum",
            published_at="2026-08-01",
        ),
    )
    monkeypatch.setattr(
        wechat_article_candidate,
        "enqueue_article_source_preparation",
        lambda item_id: None,
    )

    run = wechat_discovery.create_discovery_run(ALBUM_URL)
    result = wechat_discovery.run_wechat_discovery(run["id"])

    assert result["status"] == "succeeded"
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT content.library_folder_id,
                   album.name AS album_name,
                   collection.name AS collection_name,
                   provider.name AS provider_name,
                   source.title AS source_title
            FROM content_items AS content
            JOIN library_folders AS album ON album.id = content.library_folder_id
            JOIN library_folders AS collection ON collection.id = album.parent_folder_id
            JOIN library_folders AS provider ON provider.id = collection.parent_folder_id
            JOIN wechat_public_sources AS source ON source.id = ?
            WHERE content.canonical_source_id = 'wechat:MzAlbum:20:1'
            """,
            (run["source_id"],),
        ).fetchone()

    assert row is not None
    assert row["album_name"] == "技大之星"
    assert row["collection_name"] == "微信公众号合集"
    assert row["provider_name"] == "微信公众号"
    assert row["source_title"] == "技大之星"

    with database.connect() as connection:
        manual_folder_id = ensure_manual_wechat_folder(connection)
        connection.execute(
            "UPDATE content_items SET library_folder_id = ? WHERE canonical_source_id = ?",
            (manual_folder_id, "wechat:MzAlbum:20:1"),
        )
        connection.commit()

    incremental_run = wechat_discovery.create_album_sync_run(run["source_id"])
    incremental_result = wechat_discovery.run_wechat_discovery(incremental_run["id"])

    assert incremental_result["candidate_count"] == 0
    with database.connect() as connection:
        repaired = connection.execute(
            "SELECT library_folder_id FROM content_items WHERE canonical_source_id = ?",
            ("wechat:MzAlbum:20:1",),
        ).fetchone()
        album_folder_count = connection.execute(
            "SELECT COUNT(*) AS count FROM library_folders WHERE name = '技大之星' AND deleted_at IS NULL"
        ).fetchone()
    assert repaired["library_folder_id"] == row["library_folder_id"]
    assert album_folder_count["count"] == 1
