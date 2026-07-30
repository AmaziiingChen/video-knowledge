from __future__ import annotations

import json
import time

from services.database import connect
from services.openclaw_report_tasks import OpenClawReportTaskManager


def test_report_task_persists_the_exact_generated_markdown(monkeypatch):
    generated = "# DeepSeek 日报\n\n这是模型生成的原文。"

    def fake_generate_report(*args, **kwargs):
        callback = kwargs["progress_callback"]
        callback({"stage": "writing", "progress": 66})
        return {"content_item_id": "", "markdown": generated, "source_count": 3, "cited_source_count": 2}

    monkeypatch.setattr("services.openclaw_report_tasks.generate_report", fake_generate_report)
    manager = OpenClawReportTaskManager()
    try:
        created = manager.create(
            group_id="group-1",
            report_type="daily",
            window_start=None,
            window_end=None,
            include_history_context=True,
            file_name=None,
        )
        for _ in range(100):
            task = manager.get(created["task_id"])
            if task["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)

        assert task["status"] == "succeeded"
        assert task["source_count"] == 3
        with connect() as connection:
            row = connection.execute("SELECT result_json FROM tasks WHERE id=?", (created["task_id"],)).fetchone()
        assert json.loads(row["result_json"])["summary"] == generated
    finally:
        manager.shutdown()
