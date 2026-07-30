from __future__ import annotations

import base64
import json
from datetime import date, datetime, timezone
from email.utils import format_datetime
from typing import Any, Literal
from xml.etree import ElementTree

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from services.content_source_text import ContentSourceText, load_content_source_text
from services.database import connect, initialize_database
from services.wechat_subscription import wechat_subscription_service


router = APIRouter()


class FeedArticleResponse(BaseModel):
    id: str
    content_item_id: str
    subscription_id: str
    fakeid: str
    publisher: str
    title: str
    source_url: str
    cover_url: str | None = None
    published_at: str | None = None
    discovered_at: str


class FeedPageResponse(BaseModel):
    articles: list[FeedArticleResponse]
    next_cursor: str | None = None


class SubscriptionExportResponse(BaseModel):
    version: int = 1
    exported_at: str
    subscriptions: list[dict[str, Any]]


@router.get("/wechat-feed/articles.json", response_model=FeedPageResponse)
async def list_wechat_feed_articles(
    cursor: str | None = Query(default=None),
    subscription_id: str | None = Query(default=None, min_length=1),
    published_on: date | None = Query(default=None, description="Only articles published on this local calendar date."),
    order: Literal["discovered", "published_desc"] = Query(default="discovered"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """List locally discovered articles in a stable cursor order.

    The cursor represents discovery order rather than publish time, so articles
    published at exactly the same second cannot be skipped by an incremental
    consumer.
    """
    initialize_database()
    cursor_value = _decode_cursor(cursor) if cursor else None
    where = ["item.content_item_id IS NOT NULL"]
    parameters: list[Any] = []
    if subscription_id:
        where.append("item.subscription_id = ?")
        parameters.append(subscription_id)
    if published_on:
        where.append("substr(item.published_at, 1, 10) = ?")
        parameters.append(published_on.isoformat())
    if cursor and order != "discovered":
        raise HTTPException(status_code=400, detail="按发布时间排序时不支持 discovery cursor")
    if cursor_value:
        where.append("(item.discovered_at > ? OR (item.discovered_at = ? AND item.id > ?))")
        parameters.extend((cursor_value[0], cursor_value[0], cursor_value[1]))
    parameters.append(limit)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT item.id, item.content_item_id, item.subscription_id, item.source_url,
                   item.title, item.published_at, item.discovered_at,
                   subscription.fakeid, subscription.mp_name AS publisher,
                   content.cover_url
            FROM wechat_subscription_items AS item
            JOIN wechat_subscriptions AS subscription ON subscription.id = item.subscription_id
            JOIN content_items AS content ON content.id = item.content_item_id
            WHERE {' AND '.join(where)}
            ORDER BY {'item.discovered_at ASC, item.id ASC' if order == 'discovered' else 'COALESCE(item.published_at, item.discovered_at) DESC, item.id DESC'}
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    articles = [FeedArticleResponse(**dict(row)) for row in rows]
    next_cursor = _encode_cursor(articles[-1].discovered_at, articles[-1].id) if articles and order == "discovered" else None
    return FeedPageResponse(articles=articles, next_cursor=next_cursor)


@router.get("/wechat-feed/article/{article_id}.md", response_class=PlainTextResponse)
async def export_wechat_feed_article_markdown(article_id: str):
    """Return one subscribed article as portable Markdown with YAML frontmatter."""
    initialize_database()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT item.id, item.content_item_id, item.source_url, item.title, item.published_at,
                   subscription.fakeid, subscription.mp_name AS publisher
            FROM wechat_subscription_items AS item
            JOIN wechat_subscriptions AS subscription ON subscription.id = item.subscription_id
            WHERE item.id = ?
            """,
            (article_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订阅文章不存在")
    try:
        source = load_content_source_text(str(row["content_item_id"]))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlainTextResponse(
        _markdown_for_article(dict(row), source),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="wechat-{article_id}.md"'},
    )


@router.get("/wechat-feed/subscriptions.json", response_model=SubscriptionExportResponse)
async def export_wechat_subscriptions():
    """Export portable subscription metadata without exposing WeChat credentials."""
    return SubscriptionExportResponse(
        exported_at=datetime.now(timezone.utc).isoformat(),
        subscriptions=wechat_subscription_service.list_subscriptions(),
    )


@router.get("/wechat-feed/rss.xml")
@router.get("/wechat-feed/rss/{subscription_id}.xml")
async def get_wechat_rss(subscription_id: str | None = None, limit: int = Query(default=30, ge=1, le=100)):
    """Expose locally discovered articles as a lightweight RSS 2.0 feed."""
    initialize_database()
    where = ["item.content_item_id IS NOT NULL"]
    parameters: list[Any] = []
    title = "KnowledgeHub 微信公众号订阅"
    if subscription_id:
        where.append("item.subscription_id = ?")
        parameters.append(subscription_id)
    parameters.append(limit)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT item.id, item.source_url, item.title, item.published_at, item.discovered_at,
                   subscription.mp_name AS publisher
            FROM wechat_subscription_items AS item
            JOIN wechat_subscriptions AS subscription ON subscription.id = item.subscription_id
            WHERE {' AND '.join(where)}
            ORDER BY COALESCE(item.published_at, item.discovered_at) DESC, item.id DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    if subscription_id and not rows:
        with connect() as connection:
            subscription = connection.execute("SELECT mp_name FROM wechat_subscriptions WHERE id = ?", (subscription_id,)).fetchone()
        if not subscription:
            raise HTTPException(status_code=404, detail="公众号订阅不存在")
        title = f"KnowledgeHub · {subscription['mp_name']}"
    elif subscription_id and rows:
        title = f"KnowledgeHub · {rows[0]['publisher']}"
    return PlainTextResponse(_rss_document(title, [dict(row) for row in rows]), media_type="application/rss+xml; charset=utf-8")


def _encode_cursor(discovered_at: str, article_id: str) -> str:
    payload = json.dumps([discovered_at, article_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, list) or len(value) != 2 or not all(isinstance(part, str) and part for part in value):
            raise ValueError
        return value[0], value[1]
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="无效的 feed cursor") from exc


def _markdown_for_article(article: dict[str, Any], source: ContentSourceText) -> str:
    frontmatter = {
        "title": source.title or article["title"],
        "publisher": article["publisher"],
        "fakeid": article["fakeid"],
        "published_at": article["published_at"] or "",
        "source_url": article["source_url"],
        "wechat_article_id": article["id"],
    }
    lines = ["---"]
    lines.extend(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in frontmatter.items())
    lines.extend(["---", "", f"# {source.title or article['title']}", "", source.text.strip(), ""])
    return "\n".join(lines)


def _rss_document(title: str, articles: list[dict[str, Any]]) -> str:
    rss = ElementTree.Element("rss", version="2.0")
    channel = ElementTree.SubElement(rss, "channel")
    ElementTree.SubElement(channel, "title").text = title
    ElementTree.SubElement(channel, "description").text = "KnowledgeHub 已发现的微信公众号文章"
    ElementTree.SubElement(channel, "link").text = "http://127.0.0.1:8000/api/wechat-feed/rss.xml"
    for article in articles:
        item = ElementTree.SubElement(channel, "item")
        ElementTree.SubElement(item, "guid", isPermaLink="false").text = str(article["id"])
        ElementTree.SubElement(item, "title").text = str(article["title"])
        ElementTree.SubElement(item, "link").text = str(article["source_url"])
        ElementTree.SubElement(item, "description").text = f"来源：{article['publisher']}"
        if article.get("published_at"):
            ElementTree.SubElement(item, "pubDate").text = _rss_date(str(article["published_at"]))
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ElementTree.tostring(rss, encoding="unicode")


def _rss_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return format_datetime(parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc), usegmt=True)
    except ValueError:
        return value
