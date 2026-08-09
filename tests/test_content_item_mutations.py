import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from routers import content_mutations
from services.content_index import ensure_content_item_for_media
from services.database import connect, initialize_database


def test_content_rename_relocates_its_managed_document(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        item = ensure_content_item_for_media(
            source_provider="wechat",
            source_url="https://example.test/articles/rename",
            video_info={"title": "重命名前"},
            content_type="article",
        )
        connection.commit()

    relocated = []
    monkeypatch.setattr(content_mutations, "relocate_managed_documents", lambda item_ids: relocated.append(item_ids) or 0)

    with TestClient(app) as client:
        response = client.patch(f"/api/content/{item.id}", json={"title": "重命名后"})

    assert response.status_code == 200
    assert response.json()["title"] == "重命名后"
    assert relocated == [[item.id]]


def test_content_deletion_keeps_the_durable_trash_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        item = ensure_content_item_for_media(
            source_provider="wechat",
            source_url="https://example.test/articles/delete",
            video_info={"title": "待删除"},
            content_type="article",
        )
        connection.commit()

    with TestClient(app) as client:
        response = client.delete(f"/api/content/{item.id}")

    assert response.status_code == 200
    assert response.json() == {"success": True}
    with connect() as connection:
        row = connection.execute(
            "SELECT deleted_at, trash_batch_id FROM content_items WHERE id = ?", (item.id,)
        ).fetchone()
    assert row["deleted_at"]
    assert row["trash_batch_id"]
