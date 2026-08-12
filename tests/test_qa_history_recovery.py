import sqlite3
from datetime import datetime, timedelta
from unittest.mock import patch

from config import settings
from fastapi.testclient import TestClient
from main import app
from services.ai_response_envelope import AIResponseEnvelope
from services.content_source_text import ContentSourceText
from services.database import connect, initialize_database
from services.knowledge_library import (
    append_qa_to_source_document,
    materialize_source_document,
)
from services.markdown_sync import save_markdown_draft_and_sync
from services.repository import ContentRepository, new_id


def _content_item():
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat_miniprogram",
            content_type="forum_post",
            source_url="https://example.invalid/miniprogram-post",
            canonical_source_id="miniprogram-post",
            title="小程序帖子",
            status="to_read",
        )
        connection.commit()
    return item


def test_qa_history_recovers_markdown_only_miniprogram_conversation():
    item = _content_item()
    document = materialize_source_document(
        item,
        ContentSourceText(
            content_item_id=item.id,
            title=item.title,
            source_url=item.source_url or "",
            text="小程序帖子正文。",
            source_kind="forum_capture",
        ),
    )
    answer = "帖子介绍了一项校园活动。\n\n## 注意事项\n\n记得提前报名。"
    append_qa_to_source_document(item.id, "帖子说了什么？", answer, "2026-07-21 09:00")
    assert "帖子介绍了一项校园活动。" in document.read_text(encoding="utf-8")

    response = TestClient(app).get(f"/api/content/{item.id}/qa-history")

    assert response.status_code == 200
    assert [(entry["question"], entry["answer"]) for entry in response.json()["items"]] == [
        ("帖子说了什么？", answer),
    ]
    with connect() as connection:
        persisted = connection.execute(
            "SELECT COUNT(*) AS count FROM qa_messages WHERE thread_id IN "
            "(SELECT id FROM qa_threads WHERE content_item_id = ? AND status = 'active')",
            (item.id,),
        ).fetchone()
    assert persisted["count"] == 2


def test_qa_history_recovery_uses_the_same_contract_for_generated_reports():
    """A report is a content document, not a sidebar-specific exception."""
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat_report",
            content_type="report",
            canonical_source_id="report:sidebar-contract",
            title="测试周报",
            status="to_read",
        )
        connection.commit()
    save_markdown_draft_and_sync(
        markdown=(
            "# 测试周报\n\n"
            "## AI 摘要\n\n本周生成的报告。\n\n"
            "## 追问记录\n\n### 对话 1（当前）\n\n"
            "#### 2026-07-21 10:00\n\n**问：** 本周重点？\n\n**答：** 报告重点。\n"
        ),
        title=item.title,
        obsidian_path=settings.obsidian_vault / "reports" / "测试周报.md",
        content_item_id=item.id,
    )

    response = TestClient(app).get(f"/api/content/{item.id}/qa-history")

    assert response.status_code == 200
    assert [(entry["question"], entry["answer"]) for entry in response.json()["items"]] == [
        ("本周重点？", "报告重点。"),
    ]


def test_qa_history_paginates_twelve_exchanges_without_losing_order():
    item = _content_item()
    start = datetime(2026, 7, 21, 9, 0)
    with connect() as connection:
        thread_id = new_id()
        connection.execute(
            """INSERT INTO qa_threads (id, scope, content_item_id, title, status, created_at, updated_at)
               VALUES (?, 'content', ?, '分页测试', 'active', ?, ?)""",
            (thread_id, item.id, start.isoformat(), start.isoformat()),
        )
        for number in range(1, 26):
            created_at = (start + timedelta(minutes=number)).isoformat()
            connection.executemany(
                """INSERT INTO qa_messages (id, thread_id, role, content, write_to_obsidian, created_at)
                   VALUES (?, ?, ?, ?, 1, ?)""",
                [
                    (new_id(), thread_id, "user", f"问题 {number}", created_at),
                    (new_id(), thread_id, "assistant", f"回答 {number}", created_at),
                ],
            )
        connection.commit()

    client = TestClient(app)
    latest = client.get(f"/api/content/{item.id}/qa-history", params={"limit": 12})
    assert latest.status_code == 200
    latest_data = latest.json()
    assert [entry["question"] for entry in latest_data["items"]] == [f"问题 {number}" for number in range(14, 26)]
    assert latest_data["has_more"] is True

    middle = client.get(
        f"/api/content/{item.id}/qa-history",
        params={"limit": 12, "before": latest_data["next_before"]},
    )
    assert middle.status_code == 200
    middle_data = middle.json()
    assert [entry["question"] for entry in middle_data["items"]] == [f"问题 {number}" for number in range(2, 14)]
    assert middle_data["has_more"] is True

    oldest = client.get(
        f"/api/content/{item.id}/qa-history",
        params={"limit": 12, "before": middle_data["next_before"]},
    )
    assert oldest.status_code == 200
    assert [entry["question"] for entry in oldest.json()["items"]] == ["问题 1"]
    assert oldest.json()["has_more"] is False


def test_markdown_projection_recovers_after_the_database_acknowledgement_fails():
    item = _content_item()
    source = ContentSourceText(
        content_item_id=item.id,
        title=item.title,
        source_url=item.source_url or "",
        text="小程序帖子正文。",
        source_kind="forum_capture",
    )
    document = materialize_source_document(item, source)
    client = TestClient(app)
    with (
        patch.object(settings, "deepseek_api_key", "test-key"),
        patch("routers.qa.load_content_source_text", return_value=source),
        patch("routers.qa.answer_question_envelope", return_value=AIResponseEnvelope(answer="这是回答。")),
        patch("routers.qa._mark_content_qa_exchange_written", side_effect=sqlite3.OperationalError("temporary lock")),
    ):
        response = client.post(
            "/api/qa",
            json={"question": "这是问题？", "content_item_id": item.id, "append_to_obsidian": False},
        )
    assert response.status_code == 200
    assert response.json()["saved_to_content"] is True
    assert response.json()["saved_to_markdown"] is False

    recovered = client.get(f"/api/content/{item.id}/qa-history")
    assert recovered.status_code == 200
    assert [entry["question"] for entry in recovered.json()["items"]] == ["这是问题？"]
    assert document.read_text(encoding="utf-8").count("这是问题？") == 1
    with connect() as connection:
        pending_count = connection.execute(
            """SELECT COUNT(*) AS count FROM qa_messages WHERE thread_id IN
               (SELECT id FROM qa_threads WHERE content_item_id = ? AND status = 'active')
               AND write_to_obsidian = 0""",
            (item.id,),
        ).fetchone()
    assert pending_count["count"] == 0
