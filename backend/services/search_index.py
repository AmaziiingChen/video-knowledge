from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
import re

from services.database import connect, ensure_database_initialized
from services.source_context import render_source_context_for_search


_SOURCE_CONTEXT_START = "\n\n[平台互动与评论索引]\n"
_SOURCE_CONTEXT_END = "\n[/平台互动与评论索引]"


@dataclass(frozen=True)
class SearchResult:
    content_key: str
    title: str
    summary_snippet: str
    transcript_snippet: str


@dataclass(frozen=True)
class LocalMarkdownDocument:
    content_key: str
    title: str
    markdown_path: Path | None


def upsert_search_document(
    *,
    content_key: str,
    title: str,
    summary: str,
    transcript: str,
    source_context: dict[str, object] | None = None,
) -> None:
    if not content_key:
        return
    ensure_database_initialized()
    with connect() as connection:
        _upsert(
            connection,
            content_key=content_key,
            title=title,
            summary=summary,
            transcript=_with_source_context(transcript, source_context),
        )
        connection.commit()


def upsert_source_context_document(
    *,
    content_key: str,
    title: str,
    source_context: dict[str, object],
) -> None:
    """Refresh only the auxiliary evidence while preserving indexed source text."""
    if not content_key:
        return
    ensure_database_initialized()
    with connect() as connection:
        existing = connection.execute(
            """
            SELECT title, summary, transcript
            FROM content_search
            WHERE content_item_id = ?
            """,
            (content_key,),
        ).fetchone()
        _upsert(
            connection,
            content_key=content_key,
            title=title or (str(existing["title"] or "") if existing else ""),
            summary=str(existing["summary"] or "") if existing else "",
            transcript=_with_source_context(
                str(existing["transcript"] or "") if existing else "",
                source_context,
            ),
        )
        connection.commit()


def upsert_source_text_document(
    *,
    content_key: str,
    title: str,
    transcript: str,
) -> None:
    """Index captured source text without discarding an existing AI summary."""
    if not content_key:
        return
    ensure_database_initialized()
    with connect() as connection:
        existing = connection.execute(
            """
            SELECT title, summary, transcript
            FROM content_search
            WHERE content_item_id = ?
            """,
            (content_key,),
        ).fetchone()
        _upsert(
            connection,
            content_key=content_key,
            title=title or (existing["title"] if existing else ""),
            summary=existing["summary"] if existing else "",
            transcript=_preserve_source_context(
                transcript,
                str(existing["transcript"] or "") if existing else "",
            ),
        )
        connection.commit()


def search_documents(query: str, *, limit: int = 20) -> list[SearchResult]:
    normalized = query.strip()
    if not normalized:
        return []
    ensure_database_initialized()
    with connect() as connection:
        rows = _search_fts(connection, normalized, limit=limit)
        if not rows:
            rows = _search_like(connection, normalized, limit=limit)
        return _merge_search_rows(rows, normalized, limit=limit)


def rebuild_search_index() -> dict[str, int]:
    """Rebuild the local full-text index from the existing Markdown library.

    This deliberately reads only local Markdown paths already recorded in
    ``content_documents`` or the legacy draft mapping.
    It never fetches a source, invokes a model, or modifies the Markdown files.
    Content without a local document is still indexed by title so it remains
    discoverable through the same search endpoint.
    """
    ensure_database_initialized()
    documents: list[tuple[str, str, str, str]] = []
    markdown_indexed_count = 0
    missing_markdown_count = 0
    for document in local_markdown_documents():
        if document.markdown_path is None:
            missing_markdown_count += 1
            documents.append((document.content_key, document.title, "", ""))
            continue
        try:
            markdown = document.markdown_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            missing_markdown_count += 1
            documents.append((document.content_key, document.title, "", ""))
            continue
        summary, source_text = _markdown_search_fields(markdown)
        documents.append((document.content_key, document.title, summary, source_text))
        markdown_indexed_count += 1

    with connect() as connection:
        connection.execute("DELETE FROM content_search")
        for content_id, title, summary, source_text in documents:
            _upsert(
                connection,
                content_key=content_id,
                title=title,
                summary=summary,
                transcript=source_text,
            )
        connection.commit()

    return {
        "content_count": len(documents),
        "markdown_indexed_count": markdown_indexed_count,
        "missing_markdown_count": missing_markdown_count,
    }


def local_markdown_documents() -> list[LocalMarkdownDocument]:
    """Return each live content item and its canonical or legacy local Markdown."""
    ensure_database_initialized()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.title, COALESCE(d.markdown_path, s.markdown_draft_path) AS markdown_path
            FROM content_items AS c
            LEFT JOIN content_documents AS d ON d.content_item_id = c.id
            LEFT JOIN obsidian_sync AS s ON s.rowid = (
                SELECT latest.rowid
                FROM obsidian_sync AS latest
                WHERE latest.content_item_id = c.id
                ORDER BY latest.rowid DESC
                LIMIT 1
            )
            WHERE c.deleted_at IS NULL
            ORDER BY c.created_at, c.id
            """
        ).fetchall()
    return [
        LocalMarkdownDocument(
            content_key=str(row["id"]),
            title=str(row["title"] or ""),
            markdown_path=Path(str(row["markdown_path"])) if str(row["markdown_path"] or "").strip() else None,
        )
        for row in rows
    ]


def index_local_markdown_document(document: LocalMarkdownDocument) -> bool:
    """Update one search record from an existing local Markdown path.

    Missing files intentionally leave a title-only record, so a moved or
    deleted local document does not keep stale body text in search results.
    """
    markdown = ""
    if document.markdown_path is not None:
        try:
            markdown = document.markdown_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            markdown = ""
    summary, source_text = _markdown_search_fields(markdown)
    upsert_search_document(
        content_key=document.content_key,
        title=document.title,
        summary=summary,
        transcript=source_text,
    )
    return bool(markdown)


def _upsert(
    connection: sqlite3.Connection,
    *,
    content_key: str,
    title: str,
    summary: str,
    transcript: str,
) -> None:
    connection.execute("DELETE FROM content_search WHERE content_item_id = ?", (content_key,))
    connection.execute(
        """
        INSERT INTO content_search (content_item_id, title, summary, transcript)
        VALUES (?, ?, ?, ?)
        """,
        (content_key, title, summary, transcript),
    )


def _with_source_context(transcript: str, source_context: dict[str, object] | None) -> str:
    base = re.sub(
        re.escape(_SOURCE_CONTEXT_START) + r"[\s\S]*?" + re.escape(_SOURCE_CONTEXT_END),
        "",
        str(transcript or ""),
    ).rstrip()
    evidence = render_source_context_for_search(source_context)
    if not evidence:
        return base
    return f"{base}{_SOURCE_CONTEXT_START}{evidence}{_SOURCE_CONTEXT_END}".strip()


def _preserve_source_context(transcript: str, existing_transcript: str) -> str:
    """Keep already indexed platform evidence when source text is refreshed."""
    match = re.search(
        re.escape(_SOURCE_CONTEXT_START) + r"[\s\S]*?" + re.escape(_SOURCE_CONTEXT_END),
        str(existing_transcript or ""),
    )
    base = re.sub(
        re.escape(_SOURCE_CONTEXT_START) + r"[\s\S]*?" + re.escape(_SOURCE_CONTEXT_END),
        "",
        str(transcript or ""),
    ).rstrip()
    if not match:
        return base
    return f"{base}{match.group(0)}".strip()


def _markdown_search_fields(markdown: str) -> tuple[str, str]:
    """Split a Markdown document into its generated summary and source text."""
    text = re.sub(r"\A---\s*\n[\s\S]*?\n---\s*\n?", "", str(markdown or ""), count=1).strip()
    text = re.sub(r"\n## 追问记录\s*$[\s\S]*\Z", "", text, flags=re.MULTILINE)
    summary_match = re.search(
        r"^## AI 摘要\s*$\n([\s\S]*?)(?=^## 追问记录\s*$|\Z)",
        text,
        flags=re.MULTILINE,
    )
    summary = summary_match.group(1).strip() if summary_match else ""
    source_text = re.sub(
        r"^## AI 摘要\s*$\n[\s\S]*?(?=^## 追问记录\s*$|\Z)",
        "",
        text,
        flags=re.MULTILINE,
    ).strip()
    return summary, source_text


def _search_fts(connection: sqlite3.Connection, query: str, *, limit: int) -> list[sqlite3.Row]:
    try:
        return connection.execute(
            """
            SELECT content_search.content_item_id, content_search.title, content_search.summary, content_search.transcript
            FROM content_search
            JOIN content_items ON content_items.id = content_search.content_item_id
            WHERE content_search MATCH ? AND content_items.deleted_at IS NULL
            LIMIT ?
            """,
            (_fts_query(query), limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []


def _search_like(connection: sqlite3.Connection, query: str, *, limit: int) -> list[sqlite3.Row]:
    pattern = f"%{query}%"
    return connection.execute(
        """
        SELECT content_search.content_item_id, content_search.title, content_search.summary, content_search.transcript
        FROM content_search
        JOIN content_items ON content_items.id = content_search.content_item_id
        WHERE content_items.deleted_at IS NULL
          AND (content_search.title LIKE ? OR content_search.summary LIKE ? OR content_search.transcript LIKE ?)
        ORDER BY content_search.title
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
        ).fetchall()


def _merge_search_rows(
    rows: list[sqlite3.Row],
    query: str,
    *,
    limit: int,
) -> list[SearchResult]:
    result: list[SearchResult] = []
    seen: set[str] = set()
    for row in rows:
        content_key = str(row["content_item_id"])
        if content_key in seen:
            continue
        seen.add(content_key)
        result.append(_row_to_result(row, query))
        if len(result) >= limit:
            break
    return result


def _fts_query(query: str) -> str:
    terms = [term.replace('"', '""') for term in query.split() if term.strip()]
    if not terms:
        escaped = query.replace('"', '""')
        return f'"{escaped}"'
    return " OR ".join(f'"{term}"' for term in terms)


def _row_to_result(row: sqlite3.Row, query: str) -> SearchResult:
    return SearchResult(
        content_key=row["content_item_id"],
        title=row["title"] or "未命名内容",
        summary_snippet=_snippet(row["summary"] or "", query),
        transcript_snippet=_snippet(row["transcript"] or "", query),
    )


def _snippet(text: str, query: str, *, max_chars: int = 180) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    index = clean.lower().find(query.lower())
    if index < 0:
        return clean[:max_chars].rstrip() + "..."
    start = max(0, index - max_chars // 3)
    end = min(len(clean), start + max_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(clean) else ""
    return prefix + clean[start:end].strip() + suffix
