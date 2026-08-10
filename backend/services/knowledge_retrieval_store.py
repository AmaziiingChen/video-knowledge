"""Read-only scope filtering and lexical retrieval for knowledge chunks."""
from __future__ import annotations

import re

from services.database import connect


_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}")


def tokenize_searchable(value: str) -> str:
    """Produce bounded FTS terms rather than interpolating raw query text."""
    plain = re.sub(r"\s+", " ", str(value or "")).strip()
    cjk = "".join(_CJK_RE.findall(plain))
    cjk_terms = [cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))]
    words = [word.lower() for word in _WORD_RE.findall(plain)]
    return " ".join(dict.fromkeys(cjk_terms + words))


def source_scope_clause(specs: list[tuple[str, str]]) -> tuple[str, list[object]]:
    pieces: list[str] = []
    params: list[object] = []
    for provider, name in specs:
        pieces.append("(content.source_provider=? AND content.source_name=?)")
        params.extend((provider, name))
    return "(" + " OR ".join(pieces) + ")", params


def _content_filter_clause(
    content_item_ids: list[str] | None,
    excluded_content_item_ids: list[str] | None,
) -> tuple[str, list[object]]:
    params: list[object] = []
    document_ids = [str(value).strip() for value in (content_item_ids or ()) if str(value).strip()]
    excluded_document_ids = [str(value).strip() for value in (excluded_content_item_ids or ()) if str(value).strip()]
    clause = ""
    if document_ids:
        clause += " AND child.content_item_id IN (" + ",".join("?" for _ in document_ids) + ")"
        params.extend(document_ids)
    if excluded_document_ids:
        clause += " AND child.content_item_id NOT IN (" + ",".join("?" for _ in excluded_document_ids) + ")"
        params.extend(excluded_document_ids)
    return clause, params


def scoped_child_rows(
    specs: list[tuple[str, str]],
    content_item_ids: list[str] | None = None,
    excluded_content_item_ids: list[str] | None = None,
) -> list[dict[str, object]]:
    where, params = source_scope_clause(specs)
    document_clause, document_params = _content_filter_clause(content_item_ids, excluded_content_item_ids)
    params.extend(document_params)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT child.id,child.parent_chunk_id,child.content_item_id,child.heading_path,
                   child.text,parent.text AS parent_text,content.title,content.source_name,
                   content.source_provider,content.source_url,content.published_at
            FROM knowledge_v2_chunks AS child
            JOIN knowledge_v2_chunks AS parent ON parent.id=child.parent_chunk_id
            JOIN content_items AS content ON content.id=child.content_item_id
            WHERE child.chunk_kind='child' AND content.deleted_at IS NULL AND {where}{document_clause}
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def fts_ranks(
    question: str,
    specs: list[tuple[str, str]],
    limit: int,
    content_item_ids: list[str] | None = None,
    excluded_content_item_ids: list[str] | None = None,
) -> dict[str, int]:
    terms = tokenize_searchable(question).split()
    if not terms:
        return {}
    where, params = source_scope_clause(specs)
    document_clause, document_params = _content_filter_clause(content_item_ids, excluded_content_item_ids)
    params.extend(document_params)
    match = " OR ".join(f'"{term}"' for term in terms[:36])
    try:
        with connect() as db:
            rows = db.execute(
                f"""
                SELECT search.chunk_id
                FROM knowledge_v2_search AS search
                JOIN knowledge_v2_chunks AS child ON child.id=search.chunk_id
                JOIN content_items AS content ON content.id=child.content_item_id
                WHERE knowledge_v2_search MATCH ?
                  AND child.chunk_kind='child'
                  AND content.deleted_at IS NULL
                  AND {where}{document_clause}
                ORDER BY bm25(knowledge_v2_search)
                LIMIT ?
                """,
                [match, *params, max(1, limit)],
            ).fetchall()
        return {str(row["chunk_id"]): index for index, row in enumerate(rows, 1)}
    except Exception:
        return {}


def lexical_ranks(question: str, rows: list[dict[str, object]], limit: int) -> dict[str, int]:
    terms = set(tokenize_searchable(question).split())
    scored: list[tuple[int, str]] = []
    for row in rows:
        searchable = tokenize_searchable(" ".join((str(row["title"] or ""), str(row["heading_path"] or ""), str(row["text"] or ""))))
        score = sum(term in searchable for term in terms)
        if score:
            scored.append((score, str(row["id"])))
    scored.sort(key=lambda value: value[0], reverse=True)
    return {chunk_id: index for index, (_, chunk_id) in enumerate(scored[: max(1, limit)], 1)}
