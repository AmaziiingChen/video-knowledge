import sqlite3

from services import rss_sync


def test_rss_management_order_stays_stable_after_source_activity_changes(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE rss_sources (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE rss_source_group_memberships (source_id TEXT NOT NULL, group_id TEXT NOT NULL, created_at TEXT NOT NULL);
        """
    )
    connection.executemany(
        "INSERT INTO rss_sources (id, created_at, updated_at) VALUES (?, ?, ?)",
        [
            ("first", "2026-01-01T00:00:00+00:00", "2026-07-25T20:00:00+00:00"),
            ("second", "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:00+00:00"),
        ],
    )
    monkeypatch.setattr(rss_sync, "initialize_database", lambda: None)
    monkeypatch.setattr(rss_sync, "connect", lambda: connection)
    monkeypatch.setattr(rss_sync, "_serialize_source", lambda row, *, group_ids: {"id": row["id"]})

    assert [source["id"] for source in rss_sync.list_rss_sources()] == ["first", "second"]
