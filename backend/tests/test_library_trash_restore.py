import asyncio
import sqlite3

from routers import content as content_router


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE library_folders (
            id TEXT PRIMARY KEY,
            deleted_at TEXT,
            trash_batch_id TEXT,
            updated_at TEXT
        );
        CREATE TABLE content_items (
            id TEXT PRIMARY KEY,
            deleted_at TEXT,
            trash_batch_id TEXT,
            updated_at TEXT
        );
        """
    )
    return connection


def test_restoring_a_file_returns_the_content_id_for_progressive_tree_hydration(monkeypatch):
    connection = _connection()
    connection.execute(
        "INSERT INTO content_items (id, deleted_at, trash_batch_id, updated_at) VALUES (?, ?, ?, ?)",
        ("video-1", "2026-08-01T00:00:00+00:00", "batch-1", ""),
    )
    monkeypatch.setattr(content_router, "initialize_database", lambda: None)
    monkeypatch.setattr(content_router, "connect", lambda: connection)

    restored = asyncio.run(content_router.restore_library_trash_entry("content", "video-1"))

    assert restored["success"] is True
    assert restored["restored_content_ids"] == ["video-1"]
    assert restored["restored_folder_ids"] == []
    row = connection.execute("SELECT deleted_at, trash_batch_id FROM content_items WHERE id = 'video-1'").fetchone()
    assert row["deleted_at"] is None
    assert row["trash_batch_id"] is None


def test_restoring_a_folder_returns_every_file_in_its_trash_batch(monkeypatch):
    connection = _connection()
    connection.execute(
        "INSERT INTO library_folders (id, deleted_at, trash_batch_id, updated_at) VALUES (?, ?, ?, ?)",
        ("folder-1", "2026-08-01T00:00:00+00:00", "batch-1", ""),
    )
    connection.executemany(
        "INSERT INTO content_items (id, deleted_at, trash_batch_id, updated_at) VALUES (?, ?, ?, ?)",
        [
            ("article-1", "2026-08-01T00:00:00+00:00", "batch-1", ""),
            ("video-1", "2026-08-01T00:00:00+00:00", "batch-1", ""),
        ],
    )
    monkeypatch.setattr(content_router, "initialize_database", lambda: None)
    monkeypatch.setattr(content_router, "connect", lambda: connection)

    restored = asyncio.run(content_router.restore_library_trash_entry("folder", "folder-1"))

    assert restored["restored_folder_ids"] == ["folder-1"]
    assert set(restored["restored_content_ids"]) == {"article-1", "video-1"}
    assert connection.execute("SELECT COUNT(*) FROM content_items WHERE deleted_at IS NULL").fetchone()[0] == 2
