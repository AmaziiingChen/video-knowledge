import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from services.database import connect, initialize_database, utc_now_iso
from services.openclaw_conversations import bind_task
from services.openclaw_notifications import deliver_pending_notifications


def test_terminal_delivery_sends_the_deepseek_summary_verbatim_to_live_weixin_route(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    session_key = "agent:main:openclaw-weixin:direct:peer@im.wechat"
    task_id = "task-delivery"
    now = utc_now_iso()
    initialize_database()
    with connect() as connection:
        connection.execute(
            """INSERT INTO tasks(
                   id, task_type, result_json, status, priority, progress,
                   created_at, updated_at, finished_at
               ) VALUES (?, 'process_video', ?, 'succeeded', 100, 100, ?, ?, ?)""",
            (task_id, json.dumps({"summary": "这是 DeepSeek 原始总结。\n\n- 要点一\n- 要点二"}, ensure_ascii=False), now, now, now),
        )
        connection.commit()
    bind_task(session_key=session_key, task_id=task_id)

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "sessions.json").write_text(json.dumps({
        session_key: {
            "lastChannel": "openclaw-weixin",
            "lastAccountId": "local-bot",
            "route": {
                "channel": "openclaw-weixin",
                "accountId": "local-bot",
                "target": {"to": "peer@im.wechat"},
            },
        },
    }), encoding="utf-8")
    sent: list[tuple[dict[str, str], str]] = []

    assert deliver_pending_notifications(indexes=[sessions_dir / "sessions.json"], sender=lambda route, text: sent.append((route, text))) == 1
    assert sent == [(
        {"channel": "openclaw-weixin", "account_id": "local-bot", "recipient": "peer@im.wechat"},
        "这是 DeepSeek 原始总结。\n\n- 要点一\n- 要点二",
    )]
    with connect() as connection:
        row = connection.execute("SELECT notified_at FROM openclaw_task_bindings WHERE task_id = ?", (task_id,)).fetchone()
    assert row["notified_at"]


def test_terminal_delivery_keeps_task_pending_when_live_route_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    session_key = "agent:main:openclaw-weixin:direct:missing@im.wechat"
    task_id = "task-route-missing"
    now = utc_now_iso()
    initialize_database()
    with connect() as connection:
        connection.execute(
            """INSERT INTO tasks(id, task_type, result_json, status, priority, progress, created_at, updated_at)
               VALUES (?, 'process_video', ?, 'succeeded', 100, 100, ?, ?)""",
            (task_id, json.dumps({"summary": "原始总结"}, ensure_ascii=False), now, now),
        )
        connection.commit()
    bind_task(session_key=session_key, task_id=task_id)

    assert deliver_pending_notifications(indexes=[tmp_path / "absent.json"], sender=lambda route, text: None) == 0
    with connect() as connection:
        row = connection.execute(
            "SELECT notified_at, notification_last_error FROM openclaw_task_bindings WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    assert row["notified_at"] is None
    assert "OpenClaw" in row["notification_last_error"]
