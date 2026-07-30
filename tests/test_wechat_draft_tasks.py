from __future__ import annotations

import time
from threading import Event
from types import SimpleNamespace

from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.wechat_draft_tasks import WeChatDraftTaskManager


def test_wechat_draft_job_runs_in_background_and_deduplicates(monkeypatch):
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="campus",
            content_type="article",
            title="测试报告",
        )
        connection.commit()
    monkeypatch.setattr(
        "services.wechat_draft_tasks.get_markdown_state",
        lambda content_item_id: SimpleNamespace(markdown="# 报告\n\n正文"),
    )
    calls: list[dict] = []
    started = Event()
    release = Event()

    def fake_create_draft(content_item_id, *, title, digest, author, progress_callback):
        calls.append({"content_item_id": content_item_id, "title": title})
        started.set()
        release.wait(timeout=2)
        progress_callback("deploying_public_site", 40)
        return {"id": "publication-1", "status": "draft_created", "report_title": title}

    monkeypatch.setattr(
        "services.wechat_publishing.wechat_publishing_service.create_draft",
        fake_create_draft,
    )
    manager = WeChatDraftTaskManager()
    try:
        first = manager.create(content_item_id=item.id, title="测试报告", digest="", author="")
        assert started.wait(timeout=1)
        second = manager.create(content_item_id=item.id, title="测试报告", digest="", author="")
        assert first["task_id"] == second["task_id"]
        release.set()

        for _ in range(100):
            state = manager.get(first["task_id"])
            if state["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)

        assert state["status"] == "succeeded"
        assert state["stage"] == "completed"
        assert state["publication"] == {
            "id": "publication-1",
            "status": "draft_created",
            "report_title": "测试报告",
        }
        assert calls == [{"content_item_id": item.id, "title": "测试报告"}]
    finally:
        manager.shutdown()
