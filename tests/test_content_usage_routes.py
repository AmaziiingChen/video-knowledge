from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from services.database import connect, initialize_database
from services.repository import ContentRepository


def test_usage_routes_keep_missing_content_and_ocr_limit_contracts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        content_a = ContentRepository(connection).create_content_item(
            source_provider="test",
            source_url="https://example.test/a",
            canonical_source_id="content-a",
            title="A",
        )
        content_b = ContentRepository(connection).create_content_item(
            source_provider="test",
            source_url="https://example.test/b",
            canonical_source_id="content-b",
            title="B",
        )
        connection.execute(
            """
            INSERT INTO ocr_calls (
                content_item_id, image_url, image_bytes, model, status,
                cloud_submitted, retry_count, elapsed_seconds, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (content_a.id, "https://example.test/a.png", 12, "ocr-a", "succeeded", 0, 0, 0.1, "", "2026-01-01T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO ocr_calls (
                content_item_id, image_url, image_bytes, model, status,
                cloud_submitted, retry_count, elapsed_seconds, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (content_b.id, "https://example.test/b.png", 24, "ocr-b", "succeeded", 0, 0, 0.2, "", "2026-01-02T00:00:00Z"),
        )
        connection.commit()

    client = TestClient(app)
    missing = client.get("/api/content/missing/ai-calls")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "内容不存在"}

    ocr = client.get(f"/api/ocr-calls?content_item_id={content_a.id}&limit=0")
    assert ocr.status_code == 200
    assert [row["content_item_id"] for row in ocr.json()] == [content_a.id]
