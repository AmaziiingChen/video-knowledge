from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services import source_sync_tasks


class FakeWeChatBulkService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_subscriptions(self) -> list[dict]:
        return [
            {"id": "source-1", "mp_name": "公众号一", "enabled": True},
            {"id": "source-2", "mp_name": "公众号二", "enabled": True},
        ]

    def sync_subscription(self, subscription_id: str, **_kwargs) -> dict:
        self.calls.append(subscription_id)
        return {"imported_count": 0, "coverage_complete": True}


def test_durable_wechat_bulk_sync_paces_sources(monkeypatch):
    service = FakeWeChatBulkService()
    delays: list[float] = []
    monkeypatch.setattr(source_sync_tasks, "wechat_subscription_service", service)

    result = source_sync_tasks._sync_all_wechat_subscriptions(
        on_progress=None,
        cancel_check=None,
        sleep=delays.append,
        uniform=lambda lower, upper: (lower + upper) / 2,
    )

    assert service.calls == ["source-1", "source-2"]
    assert delays == [22.5]
    assert result["succeeded"] == 2
