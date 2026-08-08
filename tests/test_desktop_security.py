from __future__ import annotations

from fastapi.testclient import TestClient

from main import app
from routers import runtime_components


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
        hidden = client.get("/api/health")
        response = client.get(
            "/api/health",
            headers={"X-KnowledgeHub-Token": "desktop-launch-token"},
        )

    assert hidden.json()["instance_token"] == ""
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "knowledgehub-backend",
        "version": "0.1.0",
        "instance_token": "desktop-launch-token",
    }


def test_mutating_local_api_requires_the_desktop_instance_token(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")
    monkeypatch.setattr(runtime_components, "install_browser", lambda: {"state": "ready"})

    with TestClient(app) as client:
        rejected = client.post("/api/runtime-components/browser/install")
        accepted = client.post(
            "/api/runtime-components/browser/install",
            headers={
                "Origin": "knowledgehub://app",
                "X-KnowledgeHub-Token": "desktop-launch-token",
            },
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"state": "ready"}


def test_source_mode_never_allows_an_unconfigured_mutating_api(monkeypatch):
    monkeypatch.delenv("KNOWLEDGEHUB_INSTANCE_TOKEN", raising=False)
    monkeypatch.delenv("KNOWLEDGEHUB_ALLOW_UNAUTHENTICATED_LOCAL_API", raising=False)

    with TestClient(app) as client:
        response = client.post("/api/runtime-components/browser/install")

    assert response.status_code == 503


def test_mutating_local_api_rejects_an_untrusted_browser_origin(monkeypatch):
    monkeypatch.setenv("KNOWLEDGEHUB_INSTANCE_TOKEN", "desktop-launch-token")

    with TestClient(app) as client:
        response = client.post(
            "/api/runtime-components/browser/install",
            headers={
                "Origin": "https://attacker.invalid",
                "X-KnowledgeHub-Token": "desktop-launch-token",
            },
        )

    assert response.status_code == 403
