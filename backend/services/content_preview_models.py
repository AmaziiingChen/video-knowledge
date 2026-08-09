"""Transport models for locally rendered article previews."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ArticlePreviewResponse(BaseModel):
    content_item_id: str
    title: str
    author: str = ""
    published_at: str = ""
    html: str
    source_html: str = ""
    gallery: list[dict[str, object]] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)
    formatting_status: str = "not_applicable"
    formatting_detail: str = ""
