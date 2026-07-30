from __future__ import annotations

from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app


def test_disconnect_removes_app_managed_platform_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    client = TestClient(app)

    assert client.post("/api/cookie", json={"cookie": "sessionid=douyin-session; sid_guard=guard"}).json()["success"]
    assert client.post("/api/bilibili-cookie", json={"cookie": "SESSDATA=bili-session; bili_jct=csrf"}).json()["success"]

    assert client.delete("/api/cookie").json()["success"]
    assert client.delete("/api/bilibili-cookie").json()["success"]

    assert not (settings.data_dir / "douyin_cookies.txt").exists()
    assert not (settings.data_dir / "bilibili_cookies.txt").exists()
