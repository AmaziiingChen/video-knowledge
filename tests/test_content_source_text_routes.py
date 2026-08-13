import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from main import app
from routers import content_source_text
from services.content_source_text import ContentTextReadiness


def test_text_readiness_route_uses_the_existing_response_contract(monkeypatch):
    item = SimpleNamespace(id="item-1", source_provider="wechat", content_type="article")
    readiness = ContentTextReadiness(
        status="ready", label="正文可用", detail="已采集", source_kind="article", can_ask_ai=True
    )
    monkeypatch.setattr(content_source_text, "_require_content_item", lambda item_id: item if item_id == "item-1" else None)
    monkeypatch.setattr(content_source_text, "inspect_content_text_readiness", lambda _item: readiness)

    with TestClient(app) as client:
        response = client.get("/api/content/item-1/text-readiness")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready", "label": "正文可用", "detail": "已采集",
        "source_kind": "article", "can_ask_ai": True, "retryable": False,
    }


def test_source_refresh_rejects_unsupported_content_before_fetching(monkeypatch):
    monkeypatch.setattr(
        content_source_text,
        "_require_content_item",
        lambda _item_id: SimpleNamespace(id="item-1", source_provider="local_file", content_type="document"),
    )
    called = []
    monkeypatch.setattr(content_source_text, "load_content_source_text", lambda *_args, **_kwargs: called.append(True))

    with TestClient(app) as client:
        response = client.post("/api/content/item-1/source-text/refresh")

    assert response.status_code == 400
    assert response.json()["detail"] == "仅已支持的文章来源可以重新抓取正文"
    assert called == []
