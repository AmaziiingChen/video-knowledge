"""Read-only source-set catalog and selection validation for Knowledge V2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from config import settings

from services.database import connect
from services.knowledge_retrieval_store import source_scope_clause


@dataclass(frozen=True)
class ScopeReadiness:
    document_count: int
    ready_document_count: int
    child_chunk_count: int
    embedded_child_count: int

    @property
    def ready(self) -> bool:
        return self.document_count > 0 and self.ready_document_count == self.document_count and self.embedded_child_count == self.child_chunk_count


def index_stats(*, source_specs: Iterable[tuple[str, str]] | None = None) -> dict[str, int]:
    clauses = ["content.deleted_at IS NULL"]
    params: list[object] = []
    specs = [(provider.strip(), name.strip()) for provider, name in (source_specs or ()) if provider.strip() and name.strip()]
    if specs:
        scope_clause, scope_params = source_scope_clause(specs)
        clauses.append(scope_clause)
        params.extend(scope_params)
    with connect() as db:
        row = db.execute(
            f"""
            SELECT COUNT(DISTINCT snapshot.content_item_id) AS indexed_documents,
                   COUNT(DISTINCT CASE WHEN chunk.chunk_kind='parent' THEN chunk.id END) AS parent_chunks,
                   COUNT(DISTINCT CASE WHEN chunk.chunk_kind='child' THEN chunk.id END) AS child_chunks,
                   COUNT(DISTINCT embedding.chunk_id) AS embedded_children
            FROM content_items AS content
            LEFT JOIN knowledge_source_snapshots AS snapshot ON snapshot.content_item_id=content.id AND snapshot.state='ready'
            LEFT JOIN knowledge_v2_chunks AS chunk ON chunk.content_item_id=content.id
            LEFT JOIN knowledge_v2_embeddings AS embedding ON embedding.chunk_id=chunk.id
            WHERE {' AND '.join(clauses)}
            """,
            params,
        ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}


def list_source_sets() -> list[dict[str, object]]:
    """List selectable source folders; there is deliberately no all-library set."""
    with connect() as db:
        rows = db.execute(
            """
            WITH eligible_documents AS (
                SELECT content.id,content.source_provider,content.source_name
                FROM content_documents AS document
                JOIN content_items AS content ON content.id=document.content_item_id
                WHERE content.deleted_at IS NULL
                  AND NULLIF(TRIM(content.source_name),'') IS NOT NULL
                  AND content.source_provider NOT IN ('wechat_report')
                  AND content.content_type != 'report'
            ),
            document_counts AS (
                SELECT source_provider,source_name,COUNT(*) AS document_count
                FROM eligible_documents
                GROUP BY source_provider,source_name
            ),
            ready_document_counts AS (
                SELECT document.source_provider,document.source_name,COUNT(*) AS ready_document_count
                FROM eligible_documents AS document
                JOIN knowledge_source_snapshots AS snapshot
                  ON snapshot.content_item_id=document.id AND snapshot.state='ready'
                GROUP BY document.source_provider,document.source_name
            ),
            child_chunk_counts AS (
                SELECT document.source_provider,document.source_name,COUNT(*) AS child_chunk_count
                FROM eligible_documents AS document
                JOIN knowledge_v2_chunks AS child
                  ON child.content_item_id=document.id AND child.chunk_kind='child'
                GROUP BY document.source_provider,document.source_name
            ),
            embedded_child_counts AS (
                SELECT document.source_provider,document.source_name,COUNT(*) AS embedded_child_count
                FROM eligible_documents AS document
                JOIN knowledge_v2_chunks AS child
                  ON child.content_item_id=document.id AND child.chunk_kind='child'
                JOIN knowledge_v2_embeddings AS embedding
                  ON embedding.chunk_id=child.id
                 AND embedding.embedding_model=?
                 AND embedding.dimensions=?
                 AND embedding.source_hash=child.source_hash
                GROUP BY document.source_provider,document.source_name
            )
            SELECT documents.source_provider,documents.source_name,documents.document_count,
                   COALESCE(ready.ready_document_count, 0) AS ready_document_count,
                   COALESCE(children.child_chunk_count, 0) AS child_chunk_count,
                   COALESCE(embedded.embedded_child_count, 0) AS embedded_child_count
            FROM document_counts AS documents
            LEFT JOIN ready_document_counts AS ready
              ON ready.source_provider=documents.source_provider AND ready.source_name=documents.source_name
            LEFT JOIN child_chunk_counts AS children
              ON children.source_provider=documents.source_provider AND children.source_name=documents.source_name
            LEFT JOIN embedded_child_counts AS embedded
              ON embedded.source_provider=documents.source_provider AND embedded.source_name=documents.source_name
            ORDER BY documents.source_provider,documents.source_name COLLATE NOCASE
            """,
            (settings.campus_embedding_api_model, int(settings.campus_embedding_api_dimensions)),
        ).fetchall()
    output: list[dict[str, object]] = []
    for row in rows:
        readiness = ScopeReadiness(*(int(row[key] or 0) for key in ("document_count", "ready_document_count", "child_chunk_count", "embedded_child_count")))
        output.append(
            {
                "id": f"{row['source_provider']}:{row['source_name']}",
                "provider": str(row["source_provider"]),
                "name": str(row["source_name"]),
                "document_count": readiness.document_count,
                "ready_document_count": readiness.ready_document_count,
                "child_chunk_count": readiness.child_chunk_count,
                "embedded_child_count": readiness.embedded_child_count,
                "status": "ready" if readiness.ready else "migrating",
                "selectable": readiness.ready,
            }
        )
    return output


def list_source_set_documents(
    provider: str,
    name: str,
    *,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, object]:
    """List only documents whose current structural index is ready to answer."""
    provider = str(provider or "").strip()
    name = str(name or "").strip()
    if not provider or not name:
        raise ValueError("请选择知识集")
    page_size = min(200, max(1, int(limit)))
    page_offset = max(0, int(offset))
    with connect() as db:
        rows = db.execute(
            """
            SELECT content.id,content.title,content.content_type,content.published_at,content.source_url,
                   COUNT(DISTINCT child.id) AS child_chunk_count
            FROM content_documents AS document
            JOIN content_items AS content ON content.id=document.content_item_id
            JOIN knowledge_source_snapshots AS snapshot
              ON snapshot.content_item_id=content.id AND snapshot.state='ready'
            JOIN knowledge_v2_chunks AS child
              ON child.content_item_id=content.id AND child.chunk_kind='child'
            WHERE content.deleted_at IS NULL
              AND content.source_provider=? AND content.source_name=?
            GROUP BY content.id
            ORDER BY COALESCE(content.published_at, '') DESC, content.id
            LIMIT ? OFFSET ?
            """,
            (provider, name, page_size + 1, page_offset),
        ).fetchall()
    has_more = len(rows) > page_size
    items = [
        {
            "id": str(row["id"]),
            "title": str(row["title"] or "未命名文章"),
            "content_type": str(row["content_type"] or "article"),
            "published_at": str(row["published_at"] or ""),
            "source_url": str(row["source_url"] or ""),
            "child_chunk_count": int(row["child_chunk_count"] or 0),
        }
        for row in rows[:page_size]
    ]
    return {"items": items, "offset": page_offset, "next_offset": page_offset + len(items) if has_more else None}


def validate_source_document_ids(
    provider: str,
    name: str,
    content_item_ids: Iterable[str] | None,
) -> list[str]:
    """Return a canonical, ready-only document selection for one source set."""
    selected = sorted({str(value).strip() for value in (content_item_ids or ()) if str(value).strip()})
    if not selected:
        return []
    provider = str(provider or "").strip()
    name = str(name or "").strip()
    if not provider or not name:
        raise ValueError("请选择知识集")
    placeholders = ",".join("?" for _ in selected)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT DISTINCT content.id
            FROM content_items AS content
            JOIN knowledge_source_snapshots AS snapshot
              ON snapshot.content_item_id=content.id AND snapshot.state='ready'
            JOIN knowledge_v2_chunks AS child
              ON child.content_item_id=content.id AND child.chunk_kind='child'
            WHERE content.deleted_at IS NULL
              AND content.source_provider=? AND content.source_name=?
              AND content.id IN ({placeholders})
            """,
            [provider, name, *selected],
        ).fetchall()
    allowed = {str(row["id"]) for row in rows}
    if allowed != set(selected):
        raise ValueError("所选文章不属于当前知识集，或尚未完成索引")
    return selected


def scope_readiness(*, source_specs: Iterable[tuple[str, str]]) -> ScopeReadiness:
    """A knowledge scope is queryable only after every selected document is ready."""
    specs = [(provider.strip(), name.strip()) for provider, name in source_specs if provider.strip() and name.strip()]
    if not specs:
        raise ValueError("知识库问答必须先选择至少一个知识集")
    where, params = source_scope_clause(specs)
    with connect() as db:
        row = db.execute(
            f"""
            SELECT COUNT(DISTINCT document.content_item_id) AS document_count,
                   COUNT(DISTINCT CASE WHEN snapshot.state='ready' THEN document.content_item_id END) AS ready_document_count,
                   COUNT(DISTINCT child.id) AS child_chunk_count,
                   COUNT(DISTINCT embedding.chunk_id) AS embedded_child_count
            FROM content_documents AS document
            JOIN content_items AS content ON content.id=document.content_item_id
            LEFT JOIN knowledge_source_snapshots AS snapshot ON snapshot.content_item_id=content.id
            LEFT JOIN knowledge_v2_chunks AS child ON child.content_item_id=content.id AND child.chunk_kind='child'
            LEFT JOIN knowledge_v2_embeddings AS embedding
              ON embedding.chunk_id=child.id
             AND embedding.embedding_model=?
             AND embedding.dimensions=?
             AND embedding.source_hash=child.source_hash
            WHERE content.deleted_at IS NULL AND {where}
            """,
            [settings.campus_embedding_api_model, int(settings.campus_embedding_api_dimensions), *params],
        ).fetchone()
    return ScopeReadiness(*(int(row[key] or 0) for key in ("document_count", "ready_document_count", "child_chunk_count", "embedded_child_count")))
