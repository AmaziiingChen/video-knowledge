"""Provider dispatch for durable source-discovery tasks.

The task manager owns persistence, scheduling and user-visible status.  This
module only selects the existing provider service and converts its result into
plain data suitable for a task record.
"""

from __future__ import annotations

from datetime import date
import random
import time
from typing import Any
from collections.abc import Callable

from services.campus_source_settings import load_campus_source_settings, record_campus_source_sync
from services.campus_sources import discover_campus_articles, get_campus_source
from services.campus_sync import enqueue_campus_article_analyses, known_campus_source_urls, persist_campus_articles
from services.creator_sync import sync_creator_source, sync_saved_creator_source
from services.favorite_sync import add_bilibili_favorite, enable_douyin_favorites, sync_saved_favorite
from services.xiaohongshu_ingest import sync_xiaohongshu_favorites
from services.rss_sync import create_rss_source, sync_saved_rss_source
from services.source_context_refresh import backfill_source_contexts, refresh_source_context
from services.wechat_subscription import (
    WeChatAuthorizationError,
    WeChatRemoteError,
    WeChatSubscriptionError,
    WECHAT_CHECK_DELAY_RANGE,
    wechat_subscription_service,
)


class SourceSyncTaskError(ValueError):
    pass


ProgressCallback = Callable[[str, float, str], None]
CancelCheck = Callable[[], bool]


def run_source_sync_task(
    request: dict[str, Any],
    *,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    kind = str(request.get("kind") or "").strip()
    _check_cancel(cancel_check)
    _report(on_progress, "discovering", 10, "正在连接来源")
    if kind == "creator_new":
        result = sync_creator_source(**dict(request.get("payload") or {}))
        payload = dict(result.__dict__)
    elif kind == "creator_saved":
        result = sync_saved_creator_source(
            str(request.get("source_id") or ""),
            retry_existing_items=bool(request.get("retry_existing_items", True)),
        )
        payload = dict(result.__dict__)
    elif kind == "rss_saved":
        payload = sync_saved_rss_source(str(request.get("source_id") or ""))
    elif kind == "rss_create":
        payload = create_rss_source(**dict(request.get("payload") or {}))
    elif kind == "favorite_saved":
        payload = sync_saved_favorite(str(request.get("source_id") or ""))
    elif kind == "favorite_douyin":
        payload = enable_douyin_favorites(auto_analyze=bool(request.get("auto_analyze", True)))
    elif kind == "favorite_bilibili":
        payload = add_bilibili_favorite(
            source_url=str(request.get("source_url") or ""),
            auto_analyze=bool(request.get("auto_analyze", True)),
        )
    elif kind == "favorite_xiaohongshu":
        payload = sync_xiaohongshu_favorites(
            source_id=str(request.get("source_id") or "") or None,
            auto_analyze=bool(request.get("auto_analyze", True)),
        )
    elif kind == "wechat_subscription":
        payload = wechat_subscription_service.sync_subscription(
            str(request.get("subscription_id") or ""),
            max_items=request.get("max_items"),
            mode=str(request.get("mode") or "latest"),
            published_after=_as_date(request.get("published_after")),
            published_before=_as_date(request.get("published_before")),
            force=True,
            on_progress=lambda progress: _report(
                on_progress,
                "importing",
                _wechat_progress_percent(progress),
                f"已发现 {int(progress.get('found_count') or 0)} 篇，正在导入 {int(progress.get('imported_count') or 0)} 篇",
            ),
        )
    elif kind == "wechat_bulk":
        payload = _sync_all_wechat_subscriptions(on_progress=on_progress, cancel_check=cancel_check)
    elif kind == "campus":
        payload = _sync_campus(request, on_progress=on_progress, cancel_check=cancel_check)
    elif kind == "source_context_refresh":
        payload = refresh_source_context(
            str(request.get("source_id") or ""),
            comment_limit=request.get("comment_limit") or 60,
            comment_pages=request.get("comment_pages") or 3,
            on_progress=on_progress,
            cancel_check=cancel_check,
        )
    elif kind == "source_context_backfill":
        payload = backfill_source_contexts(
            limit=request.get("limit") or 50,
            include_ready=bool(request.get("include_ready")),
            on_progress=on_progress,
            cancel_check=cancel_check,
        )
    else:
        raise SourceSyncTaskError("不支持的来源同步任务")
    _check_cancel(cancel_check)
    _report(on_progress, "completed", 100, "来源检查完成")
    return payload


def _sync_all_wechat_subscriptions(
    *,
    on_progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
    sleep: Callable[[float], None] = time.sleep,
    uniform: Callable[[float, float], float] = random.uniform,
) -> dict[str, Any]:
    subscriptions = [item for item in wechat_subscription_service.list_subscriptions() if item.get("enabled")]
    total = len(subscriptions)
    summary = {
        "total": total,
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "imported_count": 0,
        "incomplete_count": 0,
    }
    if not subscriptions:
        return summary
    for index, subscription in enumerate(subscriptions, start=1):
        _check_cancel(cancel_check)
        if index > 1:
            lower, upper = WECHAT_CHECK_DELAY_RANGE
            sleep(uniform(max(0.0, lower), max(lower, upper)))
            _check_cancel(cancel_check)
        name = str(subscription.get("mp_name") or "公众号")
        _report(on_progress, "importing", 5 + (index - 1) / total * 90, f"正在检查 {index}/{total}：{name}")
        try:
            result = wechat_subscription_service.sync_subscription(
                str(subscription["id"]),
                mode="latest",
                max_items=10,
                force=False,
                on_progress=lambda progress, current=index, label=name: _report(
                    on_progress,
                    "importing",
                    5 + (current - 1 + min(1.0, _wechat_progress_percent(progress) / 100)) / total * 90,
                    f"正在检查 {current}/{total}：{label}，已导入 {int(progress.get('imported_count') or 0)} 篇",
                ),
            )
            summary["completed"] += 1
            summary["succeeded"] += 1
            summary["imported_count"] += int(result.get("imported_count") or 0)
            summary["incomplete_count"] += 0 if result.get("coverage_complete", True) else 1
        except (WeChatAuthorizationError, WeChatRemoteError) as exc:
            summary["completed"] += 1
            summary["failed"] += 1
            summary["skipped"] = total - index
            raise SourceSyncTaskError(f"检查在 {name} 停止：{exc}") from exc
        except WeChatSubscriptionError:
            summary["completed"] += 1
            summary["failed"] += 1
    return summary


def _sync_campus(
    request: dict[str, Any],
    *,
    on_progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> dict[str, Any]:
    source_slug = str(request.get("source_slug") or "")
    source = get_campus_source(source_slug)
    mode = str(request.get("mode") or "latest")
    if mode not in {"latest", "count", "date_range", "all"}:
        raise SourceSyncTaskError("校园来源同步模式无效")
    published_after = _as_date(request.get("published_after"))
    published_before = _as_date(request.get("published_before"))
    if mode == "date_range" and (not published_after or not published_before):
        raise SourceSyncTaskError("请选择完整的发布日期范围")
    if published_after and published_before and published_after > published_before:
        raise SourceSyncTaskError("开始日期不能晚于结束日期")
    if mode in {"count", "all"} and source.slug == "gwt":
        raise SourceSyncTaskError("公文通历史同步需要本机 WebVPN，会在桌面端分批导入")
    limit = _campus_limit(request, source.slug)
    known_urls = known_campus_source_urls(source.name, source_slug=source.slug) if mode == "latest" else None
    _report(on_progress, "discovering", 20, "正在读取校园来源列表")
    _check_cancel(cancel_check)
    if mode == "latest" and source.slug != "gwt" and request.get("section") is None:
        discovered = []
        sections = list(source.sections)
        for index, section in enumerate(sections, start=1):
            _check_cancel(cancel_check)
            discovered.extend(discover_campus_articles(source.slug, section=section, limit=10, known_urls=known_urls))
            _report(on_progress, "discovering", 20 + 45 * index / max(1, len(sections)), f"已检查 {index}/{len(sections)} 个栏目")
    else:
        discovered = discover_campus_articles(
            source.slug,
            section=str(request.get("section") or "") or None,
            limit=limit,
            published_after=published_after,
            published_before=published_before,
            known_urls=known_urls,
        )
    _check_cancel(cancel_check)
    discovered = list({article.url: article for article in discovered}.values())
    _report(on_progress, "saving", 75, f"正在保存 {len(discovered)} 篇校园内容")
    rows, created_count = persist_campus_articles(source.name, discovered)
    source_setting = next((item for item in load_campus_source_settings() if item["slug"] == source.slug), {})
    if bool(source_setting.get("auto_analyze")):
        enqueue_campus_article_analyses(rows)
    record_campus_source_sync(
        source.slug,
        status="success",
        message="检查完成",
        discovered=len(rows),
        created=created_count,
    )
    return {
        "source_slug": source.slug,
        "source_name": source.name,
        "discovered": len(rows),
        "created": created_count,
        "duplicates": len(rows) - created_count,
        "articles": [row.__dict__ for row in rows],
    }


def _campus_limit(request: dict[str, Any], source_slug: str) -> int:
    mode = str(request.get("mode") or "latest")
    if mode == "latest":
        return 10 if source_slug == "gwt" else 300
    if mode == "all":
        return 300
    for field in ("max_items", "limit"):
        try:
            value = int(request.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return max(1, min(value, 300))
    return 20


def _as_date(value: object) -> date | None:
    if value in {None, ""}:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise SourceSyncTaskError("发布日期格式无效") from exc


def _wechat_progress_percent(progress: dict[str, int]) -> float:
    found = max(1, int(progress.get("eligible_count") or progress.get("found_count") or 1))
    imported = int(progress.get("imported_count") or 0)
    return min(95.0, 20.0 + imported / found * 70.0)


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise SourceSyncTaskError("同步任务已取消")


def _report(callback: ProgressCallback | None, stage: str, progress: float, message: str) -> None:
    if callback:
        callback(stage, max(0.0, min(100.0, progress)), message)
