from __future__ import annotations

from datetime import date, timedelta
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings
from services.article_preview import ARTICLE_NORMALIZER_VERSION, normalize_article_html
from services.cache import cache_dir_for_url, write_cache_meta
from services.campus_sources import CAMPUS_SOURCES, CampusArticle, discover_campus_articles, get_campus_source
from services.campus_source_settings import (
    ALLOWED_INTERVAL_MINUTES,
    MAX_SOURCE_GROUPS,
    load_campus_source_settings,
    record_campus_source_sync,
    update_campus_source_setting,
)
from services.campus_sync import CampusSyncRecord, enqueue_campus_article_analyses, known_campus_source_urls, persist_campus_articles
from services.database import connect, initialize_database
from services.published_at import PUBLISHED_AT_PARSER_VERSION


router = APIRouter()


class CampusSectionResponse(BaseModel):
    name: str
    url: str


class CampusSourceResponse(BaseModel):
    slug: str
    name: str
    base_url: str
    sections: list[CampusSectionResponse]


class CampusSyncRequest(BaseModel):
    section: str | None = None
    # `limit` remains for scheduler and desktop compatibility.
    limit: int | None = Field(default=None, ge=1, le=300)
    mode: Literal["latest", "count", "date_range", "all"] = "latest"
    max_items: int | None = Field(default=None, ge=1, le=300)
    published_after: date | None = None
    published_before: date | None = None


class CampusSourceSettingRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None
    auto_analyze: bool | None = None
    notify_on_new: bool | None = None
    group_ids: list[str] | None = Field(default=None, max_length=MAX_SOURCE_GROUPS)


class CampusSourceSettingResponse(BaseModel):
    slug: str
    name: str
    base_url: str
    sections: list[str]
    enabled: bool
    interval_minutes: int
    auto_analyze: bool
    notify_on_new: bool
    group_ids: list[str]
    last_sync_at: str
    last_status: str
    last_message: str
    last_discovered: int
    last_created: int


class CampusSnapshotArticle(BaseModel):
    title: str = Field(min_length=4, max_length=500)
    canonical_url: str = Field(min_length=12, max_length=2048)
    body_text: str = Field(min_length=20, max_length=1_000_000)
    body_html: str = Field(min_length=20, max_length=2_000_000)
    author: str = Field(default="深圳技术大学", max_length=200)
    published_at: str = Field(default="", max_length=40)
    images: list[str] = Field(default_factory=list, max_length=200)
    attachments: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class CampusSnapshotImportRequest(BaseModel):
    articles: list[CampusSnapshotArticle] = Field(min_length=1, max_length=50)


class CampusSyncedArticleResponse(BaseModel):
    content_item_id: str
    title: str
    url: str
    published_at: str = ""
    section: str = ""
    created: bool


class CampusSyncResponse(BaseModel):
    source_slug: str
    source_name: str
    discovered: int
    created: int
    duplicates: int
    articles: list[CampusSyncedArticleResponse]


@router.get("/campus-sources", response_model=list[CampusSourceResponse])
def list_campus_sources():
    return [
        CampusSourceResponse(
            slug=source.slug,
            name=source.name,
            base_url=source.base_url,
            sections=[
                CampusSectionResponse(name=name, url=url)
                for name, url in source.sections.items()
            ],
        )
        for source in CAMPUS_SOURCES
    ]


@router.get("/campus-sources/settings", response_model=list[CampusSourceSettingResponse])
def get_campus_source_settings():
    return [CampusSourceSettingResponse(**item) for item in load_campus_source_settings()]


@router.patch("/campus-sources/settings/{source_slug}", response_model=CampusSourceSettingResponse)
def patch_campus_source_setting(source_slug: str, req: CampusSourceSettingRequest):
    if req.enabled is None and req.interval_minutes is None and req.auto_analyze is None and req.notify_on_new is None and req.group_ids is None:
        raise HTTPException(status_code=400, detail="至少提供一个需要更新的设置")
    if req.interval_minutes is not None and req.interval_minutes not in ALLOWED_INTERVAL_MINUTES:
        raise HTTPException(status_code=400, detail="不支持的检查频率")
    group_ids = None
    if req.group_ids is not None:
        group_ids = list(dict.fromkeys(str(value).strip() for value in req.group_ids if str(value).strip()))
        if len(group_ids) > MAX_SOURCE_GROUPS:
            raise HTTPException(status_code=400, detail="一个校园来源最多加入 3 个分组")
        if group_ids:
            initialize_database()
            placeholders = ",".join("?" for _ in group_ids)
            with connect() as connection:
                count = connection.execute(
                    f"SELECT COUNT(*) FROM wechat_subscription_groups WHERE id IN ({placeholders})",
                    tuple(group_ids),
                ).fetchone()[0]
            if count != len(group_ids):
                raise HTTPException(status_code=400, detail="报告分组不存在")
    try:
        return CampusSourceSettingResponse(
            **update_campus_source_setting(
                source_slug,
                enabled=req.enabled,
                interval_minutes=req.interval_minutes,
                auto_analyze=req.auto_analyze,
                notify_on_new=req.notify_on_new,
                group_ids=group_ids,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/campus-sources/{source_slug}/sync", response_model=CampusSyncResponse)
def sync_campus_source(source_slug: str, req: CampusSyncRequest):
    try:
        source = get_campus_source(source_slug)
        if req.mode == "date_range" and (not req.published_after or not req.published_before):
            raise ValueError("请选择完整的发布日期范围")
        if req.published_after and req.published_before and req.published_after > req.published_before:
            raise ValueError("开始日期不能晚于结束日期")
        limit = _sync_limit(req, source.slug)
        published_after = req.published_after
        if req.mode in {"count", "all"} and source.slug == "gwt":
            published_after = date.min
        known_urls = known_campus_source_urls(source.name, source_slug=source.slug) if req.mode == "latest" else None
        if req.mode == "latest" and source.slug != "gwt" and req.section is None:
            discovered = []
            for section in source.sections:
                discovered.extend(discover_campus_articles(
                    source_slug,
                    section=section,
                    limit=10,
                    known_urls=known_urls,
                ))
        else:
            discovered = discover_campus_articles(
                source_slug,
                section=req.section,
                limit=limit,
                published_after=published_after,
                published_before=req.published_before,
                known_urls=known_urls,
            )
        discovered = list({article.url: article for article in discovered}.values())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        record_campus_source_sync(source_slug, status="error", message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        try:
            record_campus_source_sync(source_slug, status="error", message=str(exc))
        except LookupError:
            pass
        raise HTTPException(status_code=502, detail=f"校园来源抓取失败：{exc}") from exc

    rows, created_count = _persist_articles(source.name, discovered)
    source_setting = next((item for item in load_campus_source_settings() if item["slug"] == source.slug), {})
    if bool(source_setting.get("auto_analyze")):
        enqueue_campus_article_analyses([
            CampusSyncRecord(
                content_item_id=item.content_item_id,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
                section=item.section,
                created=item.created,
            )
            for item in rows
        ])
    record_campus_source_sync(
        source.slug,
        status="success",
        message="检查完成",
        discovered=len(rows),
        created=created_count,
    )

    return CampusSyncResponse(
        source_slug=source.slug,
        source_name=source.name,
        discovered=len(rows),
        created=created_count,
        duplicates=len(rows) - created_count,
        articles=rows,
    )


def _sync_limit(req: CampusSyncRequest, source_slug: str) -> int:
    if req.mode == "latest":
        # 公文通的“最新同步”是轻量增量检查：只抓取最新 10 篇。
        # 其余来源的 latest 分支会按各自栏目分别限制，不使用该总量。
        return 10 if source_slug == "gwt" else 300
    if req.mode == "all":
        return 300
    if req.max_items is not None:
        return req.max_items
    if req.limit is not None:
        return req.limit
    return 20


@router.post("/campus-sources/gwt/import-snapshot", response_model=CampusSyncResponse)
def import_gwt_snapshot(req: CampusSnapshotImportRequest):
    """Import pages captured inside Electron's authenticated WebVPN session.

    Authentication material never reaches this API. The desktop process sends
    only canonical article URLs and already-rendered page snapshots, which are
    validated here and stored in the normal article cache.
    """
    source = get_campus_source("gwt")
    discovered = []
    snapshots: dict[str, CampusSnapshotArticle] = {}
    for snapshot in req.articles:
        url = snapshot.canonical_url.strip()
        if len(snapshot.title.strip()) < 4 or len(snapshot.body_text.strip()) < 20 or len(snapshot.body_html.strip()) < 20:
            raise HTTPException(status_code=400, detail="公文通快照的标题或正文为空")
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != "nbw.sztu.edu.cn":
            raise HTTPException(status_code=400, detail="公文通快照包含未授权的来源地址")
        if not parsed.path.startswith("/info/"):
            raise HTTPException(status_code=400, detail="公文通快照的文章地址格式无效")
        if url in snapshots:
            continue
        snapshots[url] = snapshot
        discovered.append(
            _snapshot_article(snapshot, source_slug=source.slug, source_name=source.name)
        )

    rows, created_count = _persist_articles(source.name, discovered)
    source_setting = next((item for item in load_campus_source_settings() if item["slug"] == source.slug), {})
    if bool(source_setting.get("auto_analyze")):
        enqueue_campus_article_analyses([
            CampusSyncRecord(
                content_item_id=item.content_item_id,
                title=item.title,
                url=item.url,
                published_at=item.published_at,
                section=item.section,
                created=item.created,
            )
            for item in rows
        ])
    for article in discovered:
        snapshot = snapshots[article.url]
        safe_images = [
            value.strip()
            for value in snapshot.images
            if value.strip().startswith(("https://", "http://"))
        ]
        safe_attachments = _validated_gwt_attachments(snapshot.attachments)
        write_cache_meta(
            cache_dir_for_url(article.url),
            {
                "source_url": article.url,
                "platform": "campus",
                "article_info": {
                    "title": snapshot.title.strip(),
                    "platform": "campus",
                    "author": snapshot.author.strip() or "深圳技术大学",
                    "published_at": snapshot.published_at.strip(),
                    "published_at_parser_version": PUBLISHED_AT_PARSER_VERSION,
                    "body_text": snapshot.body_text.strip(),
                    "body_html": snapshot.body_html.strip(),
                    "normalized_html": normalize_article_html(snapshot.body_html.strip()),
                    "normalized_html_version": ARTICLE_NORMALIZER_VERSION,
                    "images": safe_images,
                    "attachments": safe_attachments,
                    "capture_transport": "sztu_webvpn",
                },
                "article_capture": {"last_error": ""},
            },
        )

    record_campus_source_sync(
        source.slug,
        status="success",
        message="通过 WebVPN 检查完成",
        discovered=len(rows),
        created=created_count,
    )

    return CampusSyncResponse(
        source_slug=source.slug,
        source_name=source.name,
        discovered=len(rows),
        created=created_count,
        duplicates=len(rows) - created_count,
        articles=rows,
    )


def _validated_gwt_attachments(value: list[dict[str, str]]) -> list[dict[str, str]]:
    attachments: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        url = str(raw.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() != "nbw.sztu.edu.cn":
            continue
        if not any(
            hint in url.lower()
            for hint in ("download.jsp", "downloadattachurl", "clickdown", ".pdf", ".doc", ".xls", ".ppt", ".zip", ".rar")
        ) or url in seen:
            continue
        seen.add(url)
        attachments.append(
            {
                "name": str(raw.get("name") or "未命名附件").strip()[:300] or "未命名附件",
                "url": url,
                "download_type": "direct",
            }
        )
    return attachments


def _snapshot_article(snapshot: CampusSnapshotArticle, *, source_slug: str, source_name: str) -> CampusArticle:
    return CampusArticle(
        title=snapshot.title.strip(),
        url=snapshot.canonical_url.strip(),
        published_at=snapshot.published_at.strip(),
        section="公文通",
        source_slug=source_slug,
        source_name=source_name,
        department=snapshot.author.strip(),
    )


def _persist_articles(source_name: str, discovered) -> tuple[list[CampusSyncedArticleResponse], int]:
    records, created_count = persist_campus_articles(source_name, list(discovered))
    return [
        CampusSyncedArticleResponse(
            content_item_id=record.content_item_id,
            title=record.title,
            url=record.url,
            published_at=record.published_at,
            section=record.section,
            created=record.created,
        )
        for record in records
    ], created_count
