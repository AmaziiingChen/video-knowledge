from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from main import app
from services.wechat_content_filters import apply_filters


def test_global_filter_rule_removes_selected_nodes_and_text(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/wechat-content-filters", json={"name": "去除广告", "selectors": [".ad", "#recommend"], "text_patterns": ["关注后回复"]})
        assert created.status_code == 200
        soup = BeautifulSoup('<div><p>正文</p><p class="ad">广告</p><p id="recommend">推荐</p><p>关注后回复关键词</p></div>', "lxml")
        apply_filters(soup, "https://mp.weixin.qq.com/s/unsubscribed")
        assert soup.get_text(" ", strip=True) == "正文"
        listed = client.get("/api/wechat-content-filters")
        assert listed.json()[0]["name"] == "去除广告"
        assert client.delete(f"/api/wechat-content-filters/{created.json()['id']}").json() == {"success": True}


def test_filter_rule_rejects_invalid_selector(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/wechat-content-filters", json={"name": "错误规则", "selectors": ["["]})
    assert response.status_code == 400
