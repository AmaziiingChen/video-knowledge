from fastapi.testclient import TestClient

from config import settings
from main import app


def test_forum_capture_api_is_hidden_when_release_gate_is_disabled(monkeypatch):
    monkeypatch.setattr(settings, "miniprogram_forum_capture_enabled", False)

    with TestClient(app) as client:
        response = client.get("/api/miniprogram-forum/status")

    assert response.status_code == 404
    assert response.json()["detail"] == "微信小程序视觉采集当前未开放"


def test_runtime_config_exposes_forum_capture_release_gate(monkeypatch):
    monkeypatch.setattr(settings, "miniprogram_forum_capture_enabled", True)

    with TestClient(app) as client:
        response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json()["miniprogram_forum_capture_enabled"] is True
