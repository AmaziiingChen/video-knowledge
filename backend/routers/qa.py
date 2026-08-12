from datetime import datetime
from dataclasses import dataclass
import json
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from services.llm_settings import text_model_configured
from services.cache import cache_dir_for_url, read_cached_transcript_segments
from services.content_source_text import load_content_source_text
from services.database import connect, initialize_database, utc_now_iso
from services.forum_capture_repository import ForumCaptureRepository
from services.markdown_sync import get_markdown_state, replace_content_summary_and_sync, sync_draft_from_obsidian
from services.repository import ContentRepository, new_id
from services.source_context_store import load_source_context
from services.knowledge_library import (
    archive_qa_conversation_in_source_document,
    append_qa_to_source_document,
    markdown_document_path,
    qa_history_from_markdown,
    replace_qa_answer_in_source_document,
)
from services.summarizer import (
    answer_question,
    append_qa_to_markdown,
    resolve_obsidian_note_path,
    stream_regenerated_content_summary,
    stream_answer_question,
)
from services.video_timestamps import normalize_video_summary_timestamps, timestamped_video_transcript


router = APIRouter()


class QAHistoryItem(BaseModel):
    question: str = ""
    answer: str = ""


class QARequest(BaseModel):
    question: str = Field(..., min_length=1)
    display_question: str = ""
    summary: str = ""
    transcript: str = ""
    video_title: str = ""
    source_url: str = ""
    content_item_id: str | None = None
    obsidian_path: str | None = None
    history: list[QAHistoryItem] = Field(default_factory=list)
    append_to_obsidian: bool = True
    ai_model: str | None = None
    regenerate_summary: bool = False
    regenerate_assistant_message_id: str | None = Field(default=None, min_length=1, max_length=100)


class QAResponse(BaseModel):
    success: bool
    answer: str | None = None
    obsidian_path: str | None = None
    saved_to_obsidian: bool = False
    saved_to_markdown: bool = False
    saved_to_content: bool = False
    synced_markdown_draft: bool = False
    obsidian_error: str | None = None
    error: str | None = None
    assistant_message_id: str | None = None


class SavedQAHistoryItem(BaseModel):
    id: str
    question: str
    answer: str
    created_at: str


class QAHistoryResponse(BaseModel):
    items: list[SavedQAHistoryItem] = Field(default_factory=list)
    has_more: bool = False
    next_before: str | None = None


class StartNewConversationResponse(BaseModel):
    archived: bool
    markdown_archived: bool


@dataclass(frozen=True)
class SavedContentQAExchange:
    content_item_id: str
    user_message_id: str
    assistant_message_id: str
    question: str
    answer: str
    created_at: str


def _resolve_qa_source(req: QARequest) -> tuple[str, str, str]:
    """Prefer the actual cached source text for a selected content item."""
    summary = req.summary.strip()
    transcript = req.transcript.strip()
    video_title = req.video_title.strip()

    if req.content_item_id:
        try:
            source = load_content_source_text(req.content_item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc
        except ValueError as exc:
            # An older result may still have a usable summary even when its cache
            # was removed. Keep that backward-compatible fallback.
            if not summary:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            transcript = source.text
            video_title = source.title or video_title

    if not summary and not transcript:
        raise HTTPException(status_code=400, detail="缺少可分析的正文、字幕或转写文本")
    return summary, transcript, video_title


def _display_question(req: QARequest, question: str) -> str:
    return req.display_question.strip() or question


def _require_regenerable_content(content_item_id: str | None) -> str:
    if not content_item_id:
        raise HTTPException(status_code=400, detail="重新生成总结需要指定内容")
    initialize_database()
    try:
        with connect() as connection:
            item = ContentRepository(connection).get_content_item(content_item_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="内容不存在") from exc
    if item.content_type in {"video", "audio"}:
        return item.content_type
    try:
        source = load_content_source_text(content_item_id)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="当前内容尚未识别到可用于生成摘要的原文") from exc
    if source.source_kind == "forum_capture":
        return "forum_capture"
    if source.text.strip():
        return "article"
    raise HTTPException(status_code=400, detail="当前内容尚未识别到可用于生成摘要的原文")


def _video_timestamp_segments(content_item_id: str | None) -> list[dict]:
    if not content_item_id:
        return []
    try:
        initialize_database()
        with connect() as connection:
            item = ContentRepository(connection).get_content_item(content_item_id)
        if item.content_type not in {"video", "audio"} or not item.source_url:
            return []
        return read_cached_transcript_segments(
            cache_dir_for_url(item.source_url),
            duration=item.duration_seconds,
        )
    except (LookupError, OSError, ValueError):
        return []


def _timestamped_qa_transcript(content_item_id: str | None, transcript: str) -> tuple[str, set[int]]:
    """Use precise timed-media material for summaries and follow-up Q&A."""
    segments = _video_timestamp_segments(content_item_id)
    if not segments:
        return str(transcript or ""), set()
    return timestamped_video_transcript(transcript, segments)


def _save_content_qa_exchange(
    content_item_id: str | None,
    question: str,
    answer: str,
) -> SavedContentQAExchange | None:
    """Persist a completed manual answer before projecting it into Markdown."""
    if not content_item_id:
        return None

    try:
        initialize_database()
        now = utc_now_iso()
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM content_items WHERE id = ?",
                (content_item_id,),
            ).fetchone()
            if exists is None:
                return None

            thread = connection.execute(
                """
                SELECT id FROM qa_threads
                WHERE scope = 'content' AND content_item_id = ? AND status = 'active'
                LIMIT 1
                """,
                (content_item_id,),
            ).fetchone()
            if thread is None:
                thread_id = new_id()
                connection.execute(
                    """
                    INSERT INTO qa_threads (
                        id, scope, content_item_id, title, created_at, updated_at
                    ) VALUES (?, 'content', ?, ?, ?, ?)
                    """,
                    (thread_id, content_item_id, question[:120], now, now),
                )
            else:
                thread_id = thread["id"]
                connection.execute(
                    "UPDATE qa_threads SET updated_at = ? WHERE id = ?",
                    (now, thread_id),
                )

            user_message_id = new_id()
            assistant_message_id = new_id()
            connection.executemany(
                """
                INSERT INTO qa_messages (id, thread_id, role, content, write_to_obsidian, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (user_message_id, thread_id, "user", question, 0, now),
                    (assistant_message_id, thread_id, "assistant", answer, 0, now),
                ],
            )
            connection.commit()
    except sqlite3.Error:
        return None
    return SavedContentQAExchange(
        content_item_id=content_item_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        question=question,
        answer=answer,
        created_at=now,
    )


def _latest_content_qa_exchange(
    content_item_id: str | None,
    assistant_message_id: str | None,
) -> SavedContentQAExchange | None:
    """Return a regeneration target only when it is the active conversation tail."""
    if not content_item_id or not assistant_message_id:
        return None
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT assistant.id AS assistant_message_id, assistant.created_at,
                   user.id AS user_message_id, user.content AS question, assistant.content AS answer
            FROM qa_messages AS assistant
            JOIN qa_threads AS thread ON thread.id = assistant.thread_id
            JOIN qa_messages AS user ON user.rowid = (
                SELECT prior.rowid
                FROM qa_messages AS prior
                WHERE prior.thread_id = assistant.thread_id
                  AND prior.role = 'user'
                  AND prior.rowid < assistant.rowid
                ORDER BY prior.rowid DESC
                LIMIT 1
            )
            WHERE assistant.id = ?
              AND assistant.role = 'assistant'
              AND thread.scope = 'content'
              AND thread.content_item_id = ?
              AND thread.status = 'active'
              AND NOT EXISTS (
                SELECT 1 FROM qa_messages AS later
                WHERE later.thread_id = assistant.thread_id AND later.rowid > assistant.rowid
              )
            """,
            (assistant_message_id, content_item_id),
        ).fetchone()
    if row is None:
        return None
    return SavedContentQAExchange(
        content_item_id=content_item_id,
        user_message_id=str(row["user_message_id"]),
        assistant_message_id=str(row["assistant_message_id"]),
        question=str(row["question"]),
        answer=str(row["answer"]),
        created_at=str(row["created_at"]),
    )


def _replace_latest_content_qa_answer(target: SavedContentQAExchange, answer: str) -> SavedContentQAExchange | None:
    """Atomically replace the prevalidated tail answer and mark its Markdown projection dirty."""
    try:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE qa_messages
                SET content = ?, write_to_obsidian = 0
                WHERE id = ? AND role = 'assistant'
                  AND NOT EXISTS (
                    SELECT 1 FROM qa_messages AS later
                    WHERE later.thread_id = qa_messages.thread_id AND later.rowid > qa_messages.rowid
                  )
                """,
                (answer, target.assistant_message_id),
            ).rowcount
            if not updated:
                connection.rollback()
                return None
            connection.execute(
                """
                UPDATE qa_threads SET updated_at = ?
                WHERE id = (SELECT thread_id FROM qa_messages WHERE id = ?)
                """,
                (now, target.assistant_message_id),
            )
            connection.commit()
    except sqlite3.Error:
        return None
    return SavedContentQAExchange(
        content_item_id=target.content_item_id,
        user_message_id=target.user_message_id,
        assistant_message_id=target.assistant_message_id,
        question=target.question,
        answer=answer,
        created_at=target.created_at,
    )


def _markdown_timestamp(created_at: str) -> str:
    try:
        return datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.now().strftime("%Y-%m-%d %H:%M")


def _mark_content_qa_exchange_written(exchange: SavedContentQAExchange) -> None:
    with connect() as connection:
        connection.execute(
            "UPDATE qa_messages SET write_to_obsidian = 1 WHERE id IN (?, ?)",
            (exchange.user_message_id, exchange.assistant_message_id),
        )
        connection.commit()


def _sync_saved_exchange_to_markdown(exchange: SavedContentQAExchange) -> str | None:
    """Project one database-owned exchange into Markdown, safely retrying after a crash."""
    try:
        path = markdown_document_path(exchange.content_item_id)
        marker = f"<!-- qa-message:{exchange.assistant_message_id} -->"
        if path is not None and marker in path.read_text(encoding="utf-8"):
            replace_qa_answer_in_source_document(
                exchange.content_item_id,
                exchange.answer,
                message_id=exchange.assistant_message_id,
            )
        else:
            append_qa_to_source_document(
                exchange.content_item_id,
                exchange.question,
                exchange.answer,
                _markdown_timestamp(exchange.created_at),
                message_id=exchange.assistant_message_id,
            )
        _mark_content_qa_exchange_written(exchange)
    except (LookupError, OSError, ValueError, sqlite3.Error) as exc:
        return str(exc)
    return None


def _pending_content_qa_exchanges(content_item_id: str) -> list[SavedContentQAExchange]:
    """Find unsynced exchanges in the active thread, ordered for Markdown append."""
    with connect() as connection:
        thread = connection.execute(
            """SELECT id FROM qa_threads
               WHERE scope = 'content' AND content_item_id = ? AND status = 'active' LIMIT 1""",
            (content_item_id,),
        ).fetchone()
        if thread is None:
            return []
        rows = connection.execute(
            """SELECT id, role, content, write_to_obsidian, created_at
               FROM qa_messages WHERE thread_id = ? ORDER BY rowid""",
            (thread["id"],),
        ).fetchall()
    pending: list[SavedContentQAExchange] = []
    question = None
    for message in rows:
        if message["role"] == "user":
            question = message
        elif message["role"] == "assistant" and question is not None:
            if not message["write_to_obsidian"]:
                pending.append(SavedContentQAExchange(
                    content_item_id=content_item_id,
                    user_message_id=str(question["id"]),
                    assistant_message_id=str(message["id"]),
                    question=str(question["content"]),
                    answer=str(message["content"]),
                    created_at=str(question["created_at"]),
                ))
            question = None
    return pending


def _repair_pending_markdown_projection(content_item_id: str) -> None:
    for exchange in _pending_content_qa_exchanges(content_item_id):
        if _sync_saved_exchange_to_markdown(exchange):
            break


def _read_content_markdown(content_item_id: str) -> str:
    try:
        return get_markdown_state(content_item_id).markdown
    except (LookupError, OSError, ValueError):
        path = markdown_document_path(content_item_id)
        return path.read_text(encoding="utf-8") if path is not None else ""


def _markdown_created_at(timestamp: str) -> str | None:
    try:
        return datetime.strptime(timestamp[:16], "%Y-%m-%d %H:%M").isoformat()
    except ValueError:
        return None


def _restore_missing_qa_history_from_markdown(content_item_id: str) -> bool:
    """Adopt a Markdown-only active thread into the database-backed sidebar."""
    exchanges = qa_history_from_markdown(_read_content_markdown(content_item_id))
    if not exchanges:
        return False
    try:
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                """SELECT 1 FROM qa_threads
                   WHERE scope = 'content' AND content_item_id = ? AND status = 'active'""",
                (content_item_id,),
            ).fetchone()
            if active is not None:
                connection.commit()
                return False
            thread_id = new_id()
            now = utc_now_iso()
            connection.execute(
                """INSERT INTO qa_threads (id, scope, content_item_id, title, created_at, updated_at)
                   VALUES (?, 'content', ?, ?, ?, ?)""",
                (thread_id, content_item_id, exchanges[0].question[:120], now, now),
            )
            messages = []
            for exchange in exchanges:
                created_at = _markdown_created_at(exchange.timestamp) or now
                messages.extend([
                    (new_id(), thread_id, "user", exchange.question, 1, created_at),
                    (new_id(), thread_id, "assistant", exchange.answer, 1, created_at),
                ])
            connection.executemany(
                """INSERT INTO qa_messages (id, thread_id, role, content, write_to_obsidian, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                messages,
            )
            connection.commit()
    except sqlite3.Error:
        return False
    return True


def _content_qa_history(content_item_id: str, limit: int, before: str | None = None) -> QAHistoryResponse:
    initialize_database()
    with connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM content_items WHERE id = ?",
            (content_item_id,),
        ).fetchone()
        if exists is None:
            raise LookupError(content_item_id)

    _repair_pending_markdown_projection(content_item_id)
    with connect() as connection:
        thread = connection.execute(
            """
            SELECT id FROM qa_threads
            WHERE scope = 'content' AND content_item_id = ? AND status = 'active'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (content_item_id,),
        ).fetchone()
    if thread is None and _restore_missing_qa_history_from_markdown(content_item_id):
        with connect() as connection:
            thread = connection.execute(
                """SELECT id FROM qa_threads
                   WHERE scope = 'content' AND content_item_id = ? AND status = 'active'
                   ORDER BY updated_at DESC, created_at DESC LIMIT 1""",
                (content_item_id,),
            ).fetchone()
    if thread is None:
        return QAHistoryResponse()

    with connect() as connection:
        boundary_rowid = None
        if before:
            cursor = connection.execute(
                "SELECT rowid FROM qa_messages WHERE id = ? AND thread_id = ? AND role = 'assistant'",
                (before, thread["id"]),
            ).fetchone()
            if cursor is None:
                raise ValueError("追问历史游标无效")
            boundary = connection.execute(
                """SELECT rowid FROM qa_messages
                   WHERE thread_id = ? AND role = 'user' AND rowid < ?
                   ORDER BY rowid DESC LIMIT 1""",
                (thread["id"], cursor["rowid"]),
            ).fetchone()
            if boundary is None:
                return QAHistoryResponse()
            boundary_rowid = boundary["rowid"]
        rows = connection.execute(
            """
            SELECT id, role, content, created_at, rowid
            FROM qa_messages
            WHERE thread_id = ? AND (? IS NULL OR rowid < ?)
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (thread["id"], boundary_rowid, boundary_rowid, limit * 2 + 2),
        ).fetchall()

    messages = list(reversed(rows))
    history: list[SavedQAHistoryItem] = []
    question = None
    for message in messages:
        if message["role"] == "user":
            question = message
        elif message["role"] == "assistant" and question is not None:
            history.append(
                SavedQAHistoryItem(
                    id=message["id"],
                    question=question["content"],
                    answer=message["content"],
                    created_at=message["created_at"],
                )
            )
            question = None
    has_more = len(history) > limit
    items = history[-limit:]
    return QAHistoryResponse(
        items=items,
        has_more=has_more,
        next_before=items[0].id if has_more and items else None,
    )


@router.get("/content/{item_id}/qa-history", response_model=QAHistoryResponse)
async def get_content_qa_history(
    item_id: str,
    limit: int = Query(12, ge=1, le=24),
    before: str | None = Query(default=None, min_length=1, max_length=100),
):
    try:
        return _content_qa_history(item_id, limit, before)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="内容不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/content/{item_id}/qa/new-conversation", response_model=StartNewConversationResponse)
async def start_new_content_conversation(item_id: str):
    """Archive the active Q&A thread; the next question creates a fresh thread."""
    initialize_database()
    _repair_pending_markdown_projection(item_id)
    if _pending_content_qa_exchanges(item_id):
        raise HTTPException(status_code=409, detail="当前追问尚未写入 Markdown，请稍后重试")
    now = utc_now_iso()
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        exists = connection.execute("SELECT 1 FROM content_items WHERE id = ?", (item_id,)).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="内容不存在")
        archived = connection.execute(
            """
            UPDATE qa_threads
            SET status = 'archived', updated_at = ?
            WHERE scope = 'content' AND content_item_id = ? AND status = 'active'
            """,
            (now, item_id),
        ).rowcount > 0
        connection.commit()

    markdown_archived = False
    if archived:
        try:
            archive_qa_conversation_in_source_document(item_id)
            markdown_archived = True
        except (LookupError, OSError, ValueError) as exc:
            with connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    UPDATE qa_threads
                    SET status = 'active', updated_at = ?
                    WHERE scope = 'content' AND content_item_id = ? AND status = 'archived' AND updated_at = ?
                    """,
                    (utc_now_iso(), item_id, now),
                )
                connection.commit()
            raise HTTPException(status_code=409, detail=f"无法归档 Markdown 追问记录：{exc}") from exc
    return StartNewConversationResponse(
        archived=archived,
        markdown_archived=markdown_archived,
    )


@router.post("/qa", response_model=QAResponse)
def ask_video_note(req: QARequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入追问内容")
    if not text_model_configured(req.ai_model):
        raise HTTPException(status_code=500, detail="未配置所选文本模型 API Key")
    summary, transcript, video_title = _resolve_qa_source(req)
    transcript, timestamp_seconds = _timestamped_qa_transcript(req.content_item_id, transcript)
    source_context = load_source_context(req.content_item_id) if req.content_item_id else {}

    target_path = None
    obsidian_error = None
    if req.append_to_obsidian and not req.content_item_id:
        if not req.obsidian_path:
            obsidian_error = "缺少 Obsidian 笔记路径"
        else:
            try:
                target_path = resolve_obsidian_note_path(req.obsidian_path)
            except ValueError as exc:
                obsidian_error = str(exc)

    try:
        answer = answer_question(
            question=question,
            summary=summary,
            transcript=transcript,
            video_title=video_title,
            history=[item.model_dump() for item in req.history],
            model=req.ai_model,
            source_context=source_context,
        )
        answer = normalize_video_summary_timestamps(answer, timestamp_seconds)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    saved_to_obsidian = False
    saved_to_markdown = False
    synced_markdown_draft = False
    saved_exchange = _save_content_qa_exchange(
        req.content_item_id,
        _display_question(req, question),
        answer,
    )
    if req.content_item_id:
        if saved_exchange is None:
            obsidian_error = "回答已生成，但内容记录保存失败"
        else:
            obsidian_error = _sync_saved_exchange_to_markdown(saved_exchange)
            target_path = markdown_document_path(req.content_item_id)
            saved_to_markdown = obsidian_error is None
            synced_markdown_draft = saved_to_markdown
    elif target_path:
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            saved_path = append_qa_to_markdown(
                target_path,
                question,
                answer,
                timestamp,
            )
            target_path = saved_path
            saved_to_obsidian = True
            saved_to_markdown = True
            synced_markdown_draft = True
        except (LookupError, OSError, ValueError) as exc:
            obsidian_error = str(exc)
            synced_markdown_draft = False

    return QAResponse(
        success=True,
        answer=answer,
        obsidian_path=str(target_path) if target_path else req.obsidian_path,
        saved_to_obsidian=saved_to_obsidian,
        saved_to_markdown=saved_to_markdown,
        saved_to_content=bool(saved_exchange),
        synced_markdown_draft=synced_markdown_draft,
        obsidian_error=obsidian_error,
    )


@router.post("/qa/stream")
async def ask_video_note_stream(req: QARequest):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入追问内容")
    if not text_model_configured(req.ai_model):
        raise HTTPException(status_code=500, detail="未配置所选文本模型 API Key")
    if req.regenerate_summary and req.regenerate_assistant_message_id:
        raise HTTPException(status_code=400, detail="不能同时重新生成摘要和追问回答")
    regeneration_target = None
    if req.regenerate_assistant_message_id:
        regeneration_target = _latest_content_qa_exchange(
            req.content_item_id,
            req.regenerate_assistant_message_id,
        )
        if regeneration_target is None:
            raise HTTPException(status_code=409, detail="只能重新生成当前会话最后一条已完成回答")
    regeneration_kind = _require_regenerable_content(req.content_item_id) if req.regenerate_summary else None
    summary, transcript, video_title = _resolve_qa_source(req)
    transcript, timestamp_seconds = _timestamped_qa_transcript(req.content_item_id, transcript)
    source_context = load_source_context(req.content_item_id) if req.content_item_id else {}
    transcript_segments = _video_timestamp_segments(req.content_item_id) if regeneration_kind in {"video", "audio"} else []

    target_path = None
    initial_obsidian_error = None
    if req.append_to_obsidian and not req.regenerate_summary and not req.content_item_id:
        if not req.obsidian_path:
            initial_obsidian_error = "缺少 Obsidian 笔记路径"
        else:
            try:
                target_path = resolve_obsidian_note_path(req.obsidian_path)
            except ValueError as exc:
                initial_obsidian_error = str(exc)

    def event_stream():
        chunks: list[str] = []
        ai_call_records = []
        try:
            if req.regenerate_summary:
                yield _sse("log", {
                    "message": "已取得完整正文或转写，正在整理摘要材料",
                    "level": "info",
                    "step": "summarize",
                    "progress": 20,
                    "status": "running",
                })
                stream = stream_regenerated_content_summary(
                    transcript=transcript,
                    video_title=video_title,
                    content_kind=regeneration_kind or "article",
                    content_item_id=req.content_item_id,
                    model=req.ai_model,
                    ai_call_callback=ai_call_records.append,
                    transcript_segments=transcript_segments,
                    source_context=source_context,
                )
                usage_call_type = "article_regeneration"
            else:
                stream = stream_answer_question(
                    question=question,
                    summary=summary,
                    transcript=transcript,
                    video_title=video_title,
                    history=[item.model_dump() for item in req.history],
                    content_item_id=req.content_item_id,
                    model=req.ai_model,
                    ai_call_callback=ai_call_records.append,
                    source_context=source_context,
                )
                usage_call_type = "qa"

            for chunk in stream:
                chunks.append(chunk)
                yield _sse("delta", {"text": chunk})

            if ai_call_records:
                for record in ai_call_records:
                    yield _sse(
                        "usage",
                        {
                            "call_type": record.call_type or usage_call_type,
                            "prompt_tokens": record.prompt_tokens,
                            "completion_tokens": record.completion_tokens,
                            "total_tokens": record.total_tokens,
                            "prompt_cache_hit_tokens": record.prompt_cache_hit_tokens,
                            "prompt_cache_miss_tokens": record.prompt_cache_miss_tokens,
                            "estimated_cost": record.estimated_cost,
                            "elapsed_seconds": record.elapsed_seconds,
                        },
                    )
                if req.regenerate_summary:
                    preparation_count = sum(record.call_type == "article_regeneration_prepare" for record in ai_call_records)
                    reported = [record for record in ai_call_records if record.total_tokens is not None]
                    total_tokens = sum(int(record.total_tokens or 0) for record in reported)
                    cost_records = [record for record in ai_call_records if record.estimated_cost is not None]
                    cost_suffix = (
                        f"；估算费用合计 {sum(float(record.estimated_cost or 0) for record in cost_records):.6f}"
                        if len(cost_records) == len(ai_call_records)
                        else "；费用估算未配置或部分调用未返回"
                    )
                    yield _sse(
                        "log",
                        {
                            "message": f"本次摘要生成：材料压缩 {preparation_count} 次，最终总结 1 次；已返回用量合计 {total_tokens} token{cost_suffix}" if reported else f"本次摘要生成：材料压缩 {preparation_count} 次，最终总结 1 次；服务未返回 token 用量{cost_suffix}",
                            "level": "success",
                            "step": "summarize",
                            "progress": 88,
                            "status": "running",
                        },
                    )

            answer = "".join(chunks)
            if timestamp_seconds:
                answer = normalize_video_summary_timestamps(answer, timestamp_seconds)
            if req.regenerate_summary:
                yield _sse("log", {
                    "message": "AI 摘要已生成，正在写入内容主摘要",
                    "level": "info",
                    "step": "save",
                    "progress": 90,
                    "status": "running",
                })
                if regeneration_kind == "forum_capture":
                    sync_state = ForumCaptureRepository().replace_run_summary_and_sync(
                        str(req.content_item_id),
                        answer,
                    )
                else:
                    sync_state = replace_content_summary_and_sync(
                        req.content_item_id,
                        answer,
                        drop_generated_title=regeneration_kind in {"video", "audio"},
                    )
                automatically_written = sync_state.sync_status == "synced"
                yield _sse("log", {
                    "message": "内容主摘要已更新" + ("并自动写入 Markdown" if automatically_written else "到本地草稿"),
                    "level": "success",
                    "step": "save",
                    "progress": 100,
                    "status": "succeeded",
                })
                yield _sse(
                    "done",
                    {
                        "obsidian_path": sync_state.obsidian_path,
                        "saved_to_obsidian": automatically_written,
                        "saved_to_content": True,
                        "synced_markdown_draft": True,
                        "obsidian_error": None,
                        "markdown_state": sync_state.__dict__,
                    },
                )
                return

            saved_to_obsidian = False
            saved_to_markdown = False
            synced_markdown_draft = False
            obsidian_error = initial_obsidian_error
            final_path = target_path
            saved_exchange = (
                _replace_latest_content_qa_answer(regeneration_target, answer)
                if regeneration_target is not None
                else _save_content_qa_exchange(
                    req.content_item_id,
                    _display_question(req, question),
                    answer,
                )
            )
            if regeneration_target is not None and saved_exchange is None:
                raise ValueError("重新生成期间对话已变化，请重新打开当前内容后再试")
            if req.content_item_id:
                if saved_exchange is None:
                    obsidian_error = "回答已生成，但内容记录保存失败"
                else:
                    obsidian_error = _sync_saved_exchange_to_markdown(saved_exchange)
                    final_path = markdown_document_path(req.content_item_id)
                    saved_to_markdown = obsidian_error is None
                    synced_markdown_draft = saved_to_markdown
            elif final_path:
                try:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
                    saved_path = append_qa_to_markdown(final_path, question, answer, timestamp)
                    final_path = saved_path
                    saved_to_obsidian = True
                    saved_to_markdown = True
                    if req.content_item_id:
                        sync_draft_from_obsidian(req.content_item_id, saved_path)
                        synced_markdown_draft = True
                except (LookupError, OSError, ValueError) as exc:
                    obsidian_error = str(exc)
                    synced_markdown_draft = False
            yield _sse(
                "done",
                {
                    "obsidian_path": str(final_path) if final_path else req.obsidian_path,
                    "saved_to_obsidian": saved_to_obsidian,
                    "saved_to_markdown": saved_to_markdown,
                    "saved_to_content": bool(saved_exchange),
                    "synced_markdown_draft": synced_markdown_draft,
                    "obsidian_error": obsidian_error,
                    "answer": answer,
                    "assistant_message_id": saved_exchange.assistant_message_id if saved_exchange else None,
                },
            )
        except Exception as exc:
            if req.regenerate_summary:
                yield _sse("log", {
                    "message": f"生成 AI 摘要失败：{exc}",
                    "level": "error",
                    "step": "summarize",
                    "progress": 100,
                    "status": "failed",
                })
            yield _sse("error", {"error": str(exc)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
