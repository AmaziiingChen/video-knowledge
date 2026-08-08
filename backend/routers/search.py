from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.search_index import search_documents


router = APIRouter()


class SearchResultResponse(BaseModel):
    content_key: str
    title: str
    summary_snippet: str
    transcript_snippet: str


@router.get("/search", response_model=list[SearchResultResponse])
def search_content(
    q: str = Query("", min_length=0),
    limit: int = Query(200, ge=1, le=300),
    scope: Literal["all", "title", "source"] = Query("all"),
):
    # Full-text lookup may need to scan large locally indexed documents.  A
    # regular FastAPI handler runs in its worker pool, keeping the event loop
    # responsive for task status, cancellation and local health checks while a
    # search is in progress.
    return [SearchResultResponse(**result.__dict__) for result in search_documents(q, limit=limit, scope=scope)]
