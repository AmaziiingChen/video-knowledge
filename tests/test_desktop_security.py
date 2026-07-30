from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_custom_desktop_origin_is_allowed_to_call_the_local_api():
    with TestClient(app) as client:
        response = client.options(
            "/api/health",
            headers={
                "Origin": "knowledgehub://app",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "knowledgehub://app"


def test_health_identifies_the_exact_desktop_backend_instance(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")

    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "knowledgehub-backend",
        "version": "0.0.0",
        "instance_token": "desktop-launch-token",
    }
