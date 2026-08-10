"""Load durable Markdown sources for V2 index rebuilds without side effects."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from services.database import connect, ensure_database_initialized
from services.knowledge_chunking import clean_source_markdown
from services.knowledge_retrieval_store import source_scope_clause


def source_documents(
    *,
    source_specs: Iterable[tuple[str, str]] | None = None,
    content_item_ids: Iterable[str] | None = None,
) -> list[dict[str, object]]:
    """Read only already materialized source Markdown, scoped before indexing."""
    specs = [(provider.strip(), name.strip()) for provider, name in (source_specs or ()) if provider.strip() and name.strip()]
    ids = [str(item).strip() for item in (content_item_ids or ()) if str(item).strip()]
    clauses = ["content.deleted_at IS NULL"]
    params: list[object] = []
    if specs:
        scope_clause, scope_params = source_scope_clause(specs)
        clauses.append(scope_clause)
        params.extend(scope_params)
    if ids:
        clauses.append("content.id IN (" + ",".join("?" for _ in ids) + ")")
        params.extend(ids)
    ensure_database_initialized()
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT content.id AS content_item_id, content.title, content.source_provider,
                   content.source_name, content.source_url, content.published_at,
                   content.created_at, document.markdown_path
            FROM content_documents AS document
            JOIN content_items AS content ON content.id = document.content_item_id
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(content.published_at, content.created_at) DESC, content.id
            """,
            params,
        ).fetchall()
    documents: list[dict[str, object]] = []
    for row in rows:
        path = Path(str(row["markdown_path"] or ""))
        try:
            markdown = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if clean_source_markdown(markdown):
            documents.append(dict(row) | {"markdown": markdown})
    return documents
