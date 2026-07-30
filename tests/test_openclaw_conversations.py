from __future__ import annotations

from config import settings
from services.database import connect, initialize_database
from services.openclaw_conversations import (
    bind_task,
    claim_terminal_notification,
    get_conversation_settings,
    list_conversation_tasks,
    list_conversations,
    record_conversation_turn,
    update_conversation_settings,
)
from services.repository import TaskRepository


def _create_task(tmp_path, monkeypatch, *, task_id: str = "task-1", status: str = "queued") -> None:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        repository = TaskRepository(connection)
        repository.create_task(task_type="process_video", task_id=task_id)
        if status != "queued":
            repository.update_task_state(task_id, status=status)
        connection.commit()


def test_conversation_task_binding_is_hashed_and_scoped(tmp_path, monkeypatch):
    _create_task(tmp_path, monkeypatch)

    result = bind_task(session_key="agent:main:weixin:peer-a", task_id="task-1")
    tasks = list_conversation_tasks(session_key="agent:main:weixin:peer-a")

    assert result["conversation_id"].startswith("oc_")
    assert tasks[0]["task_id"] == "task-1"
    assert list_conversation_tasks(session_key="agent:main:weixin:peer-b") == []
    with connect() as connection:
        raw_key_rows = connection.execute(
            "SELECT session_hash FROM openclaw_conversations WHERE session_hash = ?",
            ("agent:main:weixin:peer-a",),
        ).fetchall()
    assert raw_key_rows == []


def test_terminal_notification_can_only_be_claimed_once(tmp_path, monkeypatch):
    _create_task(tmp_path, monkeypatch, status="succeeded")
    bind_task(session_key="session-a", task_id="task-1")

    first = claim_terminal_notification(session_key="session-a", task_id="task-1")
    second = claim_terminal_notification(session_key="session-a", task_id="task-1")

    assert first["should_notify"] is True
    assert second["should_notify"] is False
    assert second["reason"] == "完成结果已通知"


def test_conversation_mirror_is_opt_in_and_respects_retention_setting(tmp_path, monkeypatch):
    _create_task(tmp_path, monkeypatch)

    off = record_conversation_turn(session_key="session-a", role="user", text="先不要保存")
    configured = update_conversation_settings(transcript_mirror_enabled=True, transcript_retention_days=7)
    on = record_conversation_turn(session_key="session-a", role="user", text="现在保存", turn_id="message-1")
    duplicate = record_conversation_turn(session_key="session-a", role="user", text="现在保存", turn_id="message-1")
    conversations = list_conversations()

    assert off["stored"] is False
    assert configured == get_conversation_settings()
    assert on["stored"] is True
    assert duplicate["stored"] is True
    assert conversations[0]["mirrored_message_count"] == 1


def test_conversation_write_prunes_expired_mirrored_messages(tmp_path, monkeypatch):
    _create_task(tmp_path, monkeypatch)
    update_conversation_settings(transcript_mirror_enabled=True, transcript_retention_days=7)
    record_conversation_turn(session_key="session-a", role="assistant", text="过期消息", turn_id="expired")
    with connect() as connection:
        connection.execute(
            "UPDATE openclaw_conversation_messages SET created_at = '2000-01-01T00:00:00+00:00'"
        )
        connection.commit()

    # Dashboard status reads stay read-only, so they cannot contend with the
    # workbench's first library request during startup. A later write applies
    # the retention policy instead.
    record_conversation_turn(session_key="session-a", role="assistant", text="触发清理", turn_id="fresh")

    assert list_conversations()[0]["mirrored_message_count"] == 1
