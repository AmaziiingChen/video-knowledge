"""Durable archives for conversations that search across the knowledge library."""
from __future__ import annotations

import json
from pathlib import Path

from config import settings
from services.ai_call_logger import ai_call_usage_detail_for_task
from services.database import connect, initialize_database, utc_now_iso
from services.repository import new_id


def list_conversations() -> dict[str, object]:
    initialize_database()
    with connect() as db:
        rows = db.execute(
            """SELECT c.id,c.title,c.scope_json,c.created_at,c.updated_at,
                      COUNT(m.id) AS message_count
               FROM knowledge_conversations c
               LEFT JOIN knowledge_conversation_messages m ON m.conversation_id=c.id
               WHERE c.deleted_at IS NULL
               GROUP BY c.id
               ORDER BY c.updated_at DESC, c.created_at DESC"""
        ).fetchall()
    return {"items": [_conversation_payload(row) for row in rows]}


def conversation_detail(conversation_id: str) -> dict[str, object]:
    initialize_database()
    with connect() as db:
        conversation = _conversation_row(db, conversation_id)
        if conversation is None:
            raise LookupError(conversation_id)
        messages = db.execute(
            """SELECT id,role,content,citations_json,error,created_at
               FROM knowledge_conversation_messages
               WHERE conversation_id=? ORDER BY created_at,id""",
            (conversation_id,),
        ).fetchall()
    payload = _conversation_payload(conversation)
    payload["messages"] = [_message_payload(row) for row in messages]
    payload["usage"] = ai_call_usage_detail_for_task(conversation_id)
    return payload


def start_exchange(*, question: str, scope: dict[str, object], conversation_id: str | None = None) -> dict[str, object]:
    """Create (or resume) a conversation and commit the user's question first."""
    initialize_database()
    value = str(question or "").strip()
    if not value:
        raise ValueError("问题不能为空")
    now = utc_now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if conversation_id:
            row = _conversation_row(db, conversation_id)
            if row is None:
                raise LookupError(conversation_id)
            identifier = conversation_id
            db.execute(
                "UPDATE knowledge_conversations SET scope_json=?,updated_at=? WHERE id=?",
                (_json(scope), now, identifier),
            )
        else:
            identifier = new_id()
            title = _title_from_question(value)
            path = _archive_path(identifier)
            db.execute(
                """INSERT INTO knowledge_conversations
                   (id,title,scope_json,markdown_path,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (identifier, title, _json(scope), str(path), now, now),
            )
        db.execute(
            """INSERT INTO knowledge_conversation_messages
               (id,conversation_id,role,content,citations_json,error,created_at)
               VALUES (?,?,'user',?,'[]','',?)""",
            (new_id(), identifier, value, now),
        )
        db.commit()
    _write_archive(identifier)
    return conversation_detail(identifier)


def finish_exchange(conversation_id: str, *, answer: str, citations: list[dict[str, object]], error: str = "") -> dict[str, object]:
    """Commit the complete assistant outcome after the streamed response finishes."""
    initialize_database()
    now = utc_now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if _conversation_row(db, conversation_id) is None:
            raise LookupError(conversation_id)
        db.execute(
            """INSERT INTO knowledge_conversation_messages
               (id,conversation_id,role,content,citations_json,error,created_at)
               VALUES (?,?,'assistant',?,?,?,?)""",
            (new_id(), conversation_id, str(answer or ""), _json(citations), str(error or ""), now),
        )
        db.execute("UPDATE knowledge_conversations SET updated_at=? WHERE id=?", (now, conversation_id))
        db.commit()
    _write_archive(conversation_id)
    return conversation_detail(conversation_id)


def _write_archive(conversation_id: str) -> None:
    detail = conversation_detail(conversation_id)
    path = Path(str(detail["markdown_path"])).resolve()
    root = _archive_root().resolve()
    if root not in path.parents:
        raise ValueError("知识库会话归档路径不合法")
    path.parent.mkdir(parents=True, exist_ok=True)
    scope = detail.get("scope") or {}
    lines = [
        "---",
        f"conversation_id: {detail['id']}",
        f"created_at: {detail['created_at']}",
        f"updated_at: {detail['updated_at']}",
        f"scope: {_json(scope)}",
        "---",
        "",
        f"# {detail['title']}",
        "",
    ]
    for message in detail["messages"]:
        if message["role"] == "user":
            lines.extend(["## 问题", "", message["content"], ""])
            continue
        lines.extend(["## 回答", "", message["content"] or "回答暂不可用", ""])
        if message["error"]:
            lines.extend([f"> 生成异常：{message['error']}", ""])
        if message["citations"]:
            lines.extend(["### 参考来源", ""])
            for citation in message["citations"]:
                title = str(citation.get("title") or "未命名内容")
                url = str(citation.get("source_url") or "")
                label = str(citation.get("source_label") or "本地内容")
                published = str(citation.get("published_at") or "日期未知")
                source = f"[{title}](<{url}>)" if url else title
                lines.append(f"- {source} · {label} · {published}")
            lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _conversation_row(db, conversation_id: str):
    return db.execute(
        """SELECT id,title,scope_json,markdown_path,created_at,updated_at
           FROM knowledge_conversations WHERE id=? AND deleted_at IS NULL""",
        (conversation_id,),
    ).fetchone()


def _conversation_payload(row) -> dict[str, object]:
    payload = dict(row)
    try:
        payload["scope"] = json.loads(payload.pop("scope_json") or "{}")
    except json.JSONDecodeError:
        payload["scope"] = {}
    return payload


def _message_payload(row) -> dict[str, object]:
    payload = dict(row)
    try:
        payload["citations"] = json.loads(payload.pop("citations_json") or "[]")
    except json.JSONDecodeError:
        payload["citations"] = []
    return payload


def _archive_root() -> Path:
    return settings.data_dir / "knowledge_conversations"


def _archive_path(conversation_id: str) -> Path:
    return _archive_root() / f"{conversation_id}.md"


def _title_from_question(question: str) -> str:
    compact = " ".join(question.split())
    return compact[:40] + ("…" if len(compact) > 40 else "")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
