import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from main import app
from routers import content_preparation


def test_article_preparation_routes_keep_their_status_and_priority_contracts(monkeypatch):
    monkeypatch.setattr(content_preparation, "article_source_preparation_status", lambda: {"queued_count": 2})
    monkeypatch.setattr(content_preparation, "article_image_ocr_status", lambda item_id: {"content_item_id": item_id, "status": "queued"})
    monkeypatch.setattr(content_preparation, "prioritize_article_image_ocr", lambda item_id: {"content_item_id": item_id, "status": "queued"})

    with TestClient(app) as client:
        queue = client.get("/api/content/article-preparation-status")
        item = client.get("/api/content/item-1/article-ocr-status")
        prioritized = client.post("/api/content/item-1/prioritize-article-ocr")

    assert queue.json() == {"queued_count": 2}
    assert item.json() == {"content_item_id": "item-1", "status": "queued"}
    assert prioritized.json() == {"content_item_id": "item-1", "status": "queued"}


def test_article_ocr_priority_keeps_its_unavailable_error(monkeypatch):
    monkeypatch.setattr(content_preparation, "prioritize_article_image_ocr", lambda _item_id: {"status": "unavailable"})

    with TestClient(app) as client:
        response = client.post("/api/content/item-1/prioritize-article-ocr")

    assert response.status_code == 404
    assert response.json()["detail"] == "未找到可识别图片的文章"
