import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from services.database import connect, initialize_database, utc_now_iso
from services.repository import ContentRepository


def test_renamed_provider_root_keeps_its_presentation_group(monkeypatch, tmp_path):
    """The sidebar must not rely on a mutable folder name for its group."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO library_folders
                (id, name, parent_folder_id, sort_order, created_at, updated_at)
            VALUES (?, ?, NULL, ?, ?, ?)
            """,
            ("wechat-root", "微信公众号", 30, now, now),
        )
        connection.execute(
            """
            INSERT INTO library_source_folder_bindings
                (source_type, source_key, folder_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("provider_root", "wechat", "wechat-root", now, now),
        )
        connection.commit()

    with TestClient(app) as client:
        renamed = client.patch(
            "/api/content/folders/wechat-root",
            json={"name": "核心公众号"},
        )
        listed = client.get("/api/content/folders")

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "核心公众号"
    assert listed.status_code == 200
    folder = next(item for item in listed.json() if item["id"] == "wechat-root")
    assert folder["name"] == "核心公众号"
    assert folder["presentation_group"] == "provider:wechat"


def test_folder_listing_returns_descendant_counts_and_lazy_direct_items(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO library_folders
                (id, name, parent_folder_id, sort_order, created_at, updated_at)
            VALUES
                ('source-root', '来源', NULL, 10, ?, ?),
                ('source-child', '子来源', 'source-root', 20, ?, ?)
            """,
            (now, now, now, now),
        )
        repository = ContentRepository(connection)
        repository.create_content_item(
            source_provider="wechat",
            canonical_source_id="root-article",
            title="根目录文章",
            library_folder_id="source-root",
        )
        repository.create_content_item(
            source_provider="wechat",
            canonical_source_id="child-article",
            title="子目录文章",
            library_folder_id="source-child",
        )
        connection.commit()

    with TestClient(app) as client:
        folders = client.get("/api/content/folders")
        root_page = client.get("/api/content/folders/source-root/items")
        child_page = client.get("/api/content/folders/source-child/items")

    assert folders.status_code == 200
    counts = {folder["id"]: folder["content_count"] for folder in folders.json()}
    assert counts["source-root"] == 2
    assert counts["source-child"] == 1
    assert root_page.status_code == 200
    assert [item["title"] for item in root_page.json()["items"]] == ["根目录文章"]
    assert root_page.json()["total"] == 1
    assert child_page.status_code == 200
    assert [item["title"] for item in child_page.json()["items"]] == ["子目录文章"]
