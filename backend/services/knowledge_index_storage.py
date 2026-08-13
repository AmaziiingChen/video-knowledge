"""Deterministic SQLite projections for the V2 knowledge index."""
from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from services.knowledge_chunking import clean_source_markdown
from services.knowledge_retrieval_store import tokenize_searchable

if TYPE_CHECKING:
    from services.knowledge_chunking import ChildChunk


CHUNKER_VERSION = "knowledge-structural-v2"


def insert_chunk(
    db,
    chunk_id: str,
    document: dict[str, object],
    parent_chunk_id: str | None,
    chunk_kind: str,
    ordinal: int,
    heading_path: str,
    text: str,
    token_count: int,
    source_hash: str,
    now: str,
) -> None:
    """Write one parent or child chunk using the existing bound-value schema."""
    db.execute(
        """INSERT INTO knowledge_v2_chunks
           (id,content_item_id,parent_chunk_id,chunk_kind,ordinal,heading_path,text,token_count,source_hash,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (chunk_id, document["content_item_id"], parent_chunk_id, chunk_kind, ordinal, heading_path, text, token_count, source_hash, now, now),
    )


def source_hash(document: dict[str, object]) -> str:
    """Hash the source identity and cleaned Markdown used for indexing."""
    fields = [
        CHUNKER_VERSION,
        str(document.get("title") or ""),
        str(document.get("source_provider") or ""),
        str(document.get("source_name") or ""),
        str(document.get("source_url") or ""),
        clean_source_markdown(str(document.get("markdown") or "")),
    ]
    return sha256("\n".join(fields).encode("utf-8")).hexdigest()


def searchable(document: dict[str, object], chunk: ChildChunk) -> str:
    """Project source metadata and child text to the bounded FTS token form."""
    return tokenize_searchable(
        " ".join(
            (
                str(document.get("title") or ""),
                str(document.get("source_name") or ""),
                chunk.heading_path,
                chunk.text,
            )
        )
    )
