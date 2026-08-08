from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from services.database import connect, ensure_database_initialized, utc_now_iso
from services.repository import new_id
from services.wechat_article_candidate import (
    import_verified_article as _import_verified_article,
    verify_article as _verify_article,
)
from services.wechat_browser import fetch_wechat_page
from services.wechat_discovery_models import VerifiedArticle, WeChatDiscoveryError
from services.wechat_public_search import SearchResult, search_public_wechat_articles
from services.wechat_urls import (
    album_endpoint,
    album_identity,
    canonical_wechat_article_id,
    extract_wechat_urls,
    is_wechat_album_url,
    is_wechat_article_url,
    normalize_wechat_url,
)


MAX_DIRECT_ARTICLES = 500
MAX_REVIEW_IMPORT_ARTICLES = 500
MAX_ALBUM_PAGES = 50
DEFAULT_ALBUM_SYNC_INTERVAL_MINUTES = 720
MIN_ALBUM_SYNC_INTERVAL_MINUTES = 360
MAX_ALBUM_SYNC_INTERVAL_MINUTES = 1440

ProgressCallback = Callable[[str, float, str], None]
CancelCheck = Callable[[], bool]


def create_discovery_run(
    input_text: str,
    *,
    auto_analyze: bool = False,
    strategy: str = "direct",
    subscribe_album: bool = False,
    sync_interval_minutes: int = DEFAULT_ALBUM_SYNC_INTERVAL_MINUTES,
) -> dict[str, Any]:
    ensure_database_initialized()
    raw = str(input_text or "").strip()
    if not raw:
        raise WeChatDiscoveryError("请粘贴公众号文章链接或一个合集链接")
    urls = extract_wechat_urls(raw)
    if not urls:
        raise WeChatDiscoveryError("没有识别到微信公众号链接")

    discovery_strategy = str(strategy or "direct").strip().lower()
    if discovery_strategy not in {"direct", "seed"}:
        raise WeChatDiscoveryError("不支持的公众号发现方式")
    album_urls = [url for url in urls if is_wechat_album_url(url)]
    article_urls = [url for url in urls if is_wechat_article_url(url)]
    if album_urls:
        if discovery_strategy == "seed":
            raise WeChatDiscoveryError("种子扩展需要粘贴一篇公众号文章，不能使用合集链接")
        if len(urls) != 1 or len(album_urls) != 1:
            raise WeChatDiscoveryError("一次只能导入一个合集；文章链接请另建批次")
        mode = "album"
        source_url = album_urls[0]
        biz, album_id = album_identity(source_url)
        source_key = f"album:{biz}:{album_id}"
        source_title = "公众号合集"
        request = {
            "album_url": source_url,
            "biz": biz,
            "album_id": album_id,
            "auto_analyze": bool(auto_analyze),
            "incremental": False,
        }
        coverage_label = "仅覆盖该合集当前公开文章"
        discovery_strategy = "direct"
    else:
        if not article_urls:
            raise WeChatDiscoveryError("链接不是可识别的公众号文章或合集")
        if discovery_strategy == "seed" and len(article_urls) != 1:
            raise WeChatDiscoveryError("种子扩展一次需要且只能使用一篇公众号文章")
        if len(article_urls) > MAX_DIRECT_ARTICLES:
            raise WeChatDiscoveryError(f"一次最多导入 {MAX_DIRECT_ARTICLES} 篇文章")
        mode = "manual"
        source_url = article_urls[0] if discovery_strategy == "seed" else None
        if discovery_strategy == "seed":
            seed_id = canonical_wechat_article_id(article_urls[0]) or article_urls[0]
            source_key = f"seed:{seed_id}"
            source_title = "公众号种子扩展"
            request = {
                "seed_url": article_urls[0],
                "auto_analyze": bool(auto_analyze),
            }
            coverage_label = "公开搜索发现，结果不保证完整"
        else:
            source_key = "manual"
            source_title = "手动批量导入"
            request = {
                "urls": article_urls,
                "auto_analyze": bool(auto_analyze),
            }
            coverage_label = "仅覆盖本次粘贴的文章链接"
        biz = ""
        album_id = ""
    request["strategy"] = discovery_strategy

    now = utc_now_iso()
    with connect() as connection:
        source = connection.execute(
            "SELECT id FROM wechat_public_sources WHERE source_key = ?",
            (source_key,),
        ).fetchone()
        source_id = str(source["id"]) if source else new_id()
        connection.execute(
            """
            INSERT INTO wechat_public_sources (
                id, source_key, source_kind, title, source_url, biz, album_id,
                coverage_label, discovery_strategy, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_key) DO UPDATE SET
                title = excluded.title,
                source_url = excluded.source_url,
                biz = excluded.biz,
                album_id = excluded.album_id,
                coverage_label = excluded.coverage_label,
                discovery_strategy = excluded.discovery_strategy,
                updated_at = excluded.updated_at
            """,
            (
                source_id,
                source_key,
                mode,
                source_title,
                source_url,
                biz or None,
                album_id or None,
                coverage_label,
                discovery_strategy,
                now,
                now,
            ),
        )
        if mode == "album" and subscribe_album:
            interval = _valid_album_sync_interval(sync_interval_minutes)
            connection.execute(
                """
                UPDATE wechat_public_sources
                SET enabled = 1, auto_analyze = ?, sync_interval_minutes = ?,
                    next_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(auto_analyze),
                    interval,
                    _time_after_minutes(interval),
                    now,
                    source_id,
                ),
            )
        run_id = new_id()
        connection.execute(
            """
            INSERT INTO wechat_discovery_runs (
                id, source_id, mode, discovery_strategy, status, request_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?)
            """,
            (
                run_id,
                source_id,
                mode,
                discovery_strategy,
                json.dumps(request, ensure_ascii=False),
                now,
                now,
            ),
        )
        connection.commit()
    return get_discovery_run(run_id)


def list_public_album_sources() -> list[dict[str, Any]]:
    ensure_database_initialized()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM wechat_public_sources
            WHERE source_kind = 'album'
            ORDER BY enabled DESC, COALESCE(last_discovery_at, created_at) DESC, created_at DESC
            """
        ).fetchall()
    return [_serialize_public_album_source(row) for row in rows]


def get_public_album_source(source_id: str) -> dict[str, Any]:
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM wechat_public_sources WHERE id = ? AND source_kind = 'album'",
            (source_id,),
        ).fetchone()
    if not row:
        raise LookupError("公众号合集来源不存在")
    return _serialize_public_album_source(row)


def update_public_album_source(
    source_id: str,
    *,
    enabled: bool | None = None,
    auto_analyze: bool | None = None,
    sync_interval_minutes: int | None = None,
) -> dict[str, Any]:
    current = get_public_album_source(source_id)
    next_enabled = current["enabled"] if enabled is None else bool(enabled)
    next_auto_analyze = current["auto_analyze"] if auto_analyze is None else bool(auto_analyze)
    next_interval = _valid_album_sync_interval(
        current["sync_interval_minutes"] if sync_interval_minutes is None else sync_interval_minutes
    )
    if not next_enabled:
        next_sync_at = None
    elif not current["enabled"] or sync_interval_minutes is not None:
        next_sync_at = _time_after_minutes(next_interval)
    else:
        next_sync_at = current.get("next_sync_at") or utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_public_sources
            SET enabled = ?, auto_analyze = ?, sync_interval_minutes = ?,
                next_sync_at = ?, updated_at = ?
            WHERE id = ? AND source_kind = 'album'
            """,
            (
                int(next_enabled),
                int(next_auto_analyze),
                next_interval,
                next_sync_at,
                utc_now_iso(),
                source_id,
            ),
        )
        connection.commit()
    return get_public_album_source(source_id)


def create_album_sync_run(source_id: str) -> dict[str, Any]:
    source = get_public_album_source(source_id)
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        active = connection.execute(
            """
            SELECT id FROM wechat_discovery_runs
            WHERE source_id = ? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
            """,
            (source_id,),
        ).fetchone()
        if active:
            raise WeChatDiscoveryError("该合集已有检查任务正在进行")
        now = utc_now_iso()
        run_id = new_id()
        request = {
            "album_url": source["source_url"],
            "biz": source["biz"],
            "album_id": source["album_id"],
            "auto_analyze": bool(source["auto_analyze"]),
            "incremental": True,
            "strategy": "direct",
        }
        connection.execute(
            """
            INSERT INTO wechat_discovery_runs (
                id, source_id, mode, discovery_strategy, status, request_json,
                created_at, updated_at
            ) VALUES (?, ?, 'album', 'direct', 'queued', ?, ?, ?)
            """,
            (run_id, source_id, json.dumps(request, ensure_ascii=False), now, now),
        )
        if source["enabled"]:
            connection.execute(
                """
                UPDATE wechat_public_sources
                SET next_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (_time_after_minutes(source["sync_interval_minutes"]), now, source_id),
            )
        connection.commit()
    return get_discovery_run(run_id)


def bind_discovery_task(run_id: str, task_id: str) -> dict[str, Any]:
    ensure_database_initialized()
    with connect() as connection:
        connection.execute(
            "UPDATE wechat_discovery_runs SET task_id = ?, updated_at = ? WHERE id = ?",
            (task_id, utc_now_iso(), run_id),
        )
        connection.commit()
    return get_discovery_run(run_id)


def bind_review_import_task(run_id: str, task_id: str) -> dict[str, Any]:
    ensure_database_initialized()
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_runs
            SET task_id = ?, review_import_status = 'queued', updated_at = ?
            WHERE id = ?
            """,
            (task_id, utc_now_iso(), run_id),
        )
        connection.commit()
    return get_discovery_run(run_id)


def fail_discovery_submission(run_id: str, message: str) -> None:
    _finish_run(run_id, "failed", str(message or "任务创建失败"))


def fail_review_import_submission(run_id: str) -> None:
    _set_review_import_status(run_id, "failed")


def mark_discovery_cancelled(run_id: str) -> dict[str, Any]:
    run = get_discovery_run(run_id)
    if run["status"] in {"queued", "running"}:
        _finish_run(run_id, "cancelled", "任务已取消")
    elif run.get("review_import_status") in {"queued", "running"}:
        _set_review_import_status(run_id, "cancelled")
    return get_discovery_run(run_id)


def list_discovery_runs(*, limit: int = 30) -> list[dict[str, Any]]:
    ensure_database_initialized()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT run.id, run.source_id, run.task_id, run.mode, run.status,
                   run.discovery_strategy, run.review_required, run.reviewed_at,
                   run.review_import_status,
                   run.candidate_count, run.verified_count, run.imported_count,
                   run.duplicate_count, run.failed_count, run.error_message,
                   run.started_at, run.finished_at, run.created_at, run.updated_at,
                   source.title AS source_title, source.source_url,
                   source.biz, source.album_id, source.coverage_label
            FROM wechat_discovery_runs AS run
            JOIN wechat_public_sources AS source ON source.id = run.source_id
            ORDER BY run.created_at DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    return [_serialize_run(row, include_request=False) for row in rows]


def get_discovery_run(run_id: str) -> dict[str, Any]:
    ensure_database_initialized()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT run.*, source.title AS source_title, source.source_url,
                   source.biz, source.album_id, source.coverage_label
            FROM wechat_discovery_runs AS run
            JOIN wechat_public_sources AS source ON source.id = run.source_id
            WHERE run.id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        raise LookupError("公众号发现批次不存在")
    return _serialize_run(row)


def list_discovery_candidates(run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    ensure_database_initialized()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM wechat_discovery_candidates
            WHERE run_id = ?
            ORDER BY created_at, id
            LIMIT ?
            """,
            (run_id, max(1, min(int(limit), 500))),
        ).fetchall()
    return [dict(row) for row in rows]


def run_wechat_discovery(
    run_id: str,
    *,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    run = get_discovery_run(run_id)
    request = dict(run.get("request") or {})
    _start_run(run_id)
    try:
        _check_cancel(cancel_check)
        if str(run.get("discovery_strategy") or request.get("strategy") or "direct") == "seed":
            result = _run_seed_discovery(
                run_id,
                request,
                on_progress=on_progress,
                cancel_check=cancel_check,
            )
            _finish_run(run_id, "succeeded")
            result = get_discovery_run(run_id)
            review_count = _pending_review_count(run_id)
            _report(
                on_progress,
                "completed",
                100,
                (
                    f"种子扩展完成：{review_count} 篇同公众号文章待确认"
                    if review_count
                    else "种子扩展完成，暂未发现可确认的新文章"
                ),
            )
            return result
        album_folder_id: str | None = None
        if run["mode"] == "album":
            _discover_album(
                run_id,
                request,
                on_progress=on_progress,
                cancel_check=cancel_check,
            )
            album_folder_id = _prepare_album_folder(run_id)
        else:
            for url in list(request.get("urls") or []):
                _insert_candidate(run_id, str(url), discovered_via="manual")

        candidates = list_discovery_candidates(run_id)
        total = len(candidates)
        if not total:
            if run["mode"] == "album" and bool(request.get("incremental")):
                _finish_run(run_id, "succeeded")
                result = get_discovery_run(run_id)
                _report(on_progress, "completed", 100, "合集检查完成，没有发现新增文章")
                return result
            raise WeChatDiscoveryError("没有发现可导入的公众号文章")
        _refresh_run_counts(run_id)
        expected_biz = str(request.get("biz") or "")
        auto_analyze = bool(request.get("auto_analyze"))
        for index, candidate in enumerate(candidates, start=1):
            _check_cancel(cancel_check)
            _report(
                on_progress,
                "verifying",
                35 + (index - 1) / total * 55,
                f"正在校验并导入 {index}/{total}",
            )
            _process_candidate(
                candidate,
                expected_biz=expected_biz,
                auto_analyze=auto_analyze,
                library_folder_id=album_folder_id,
            )
            _refresh_run_counts(run_id)
        _finish_run(run_id, "succeeded")
        result = get_discovery_run(run_id)
        _report(
            on_progress,
            "completed",
            100,
            f"导入完成：新增 {result['imported_count']}，重复 {result['duplicate_count']}，失败 {result['failed_count']}",
        )
        return result
    except Exception as exc:
        status = "cancelled" if cancel_check and cancel_check() else "failed"
        _finish_run(run_id, status, "任务已取消" if status == "cancelled" else str(exc))
        raise


def _run_seed_discovery(
    run_id: str,
    request: dict[str, Any],
    *,
    on_progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> dict[str, Any]:
    seed_url = str(request.get("seed_url") or "")
    if not _insert_candidate(run_id, seed_url, discovered_via="seed"):
        raise WeChatDiscoveryError("种子文章链接无法识别")
    seed = list_discovery_candidates(run_id)[0]
    _report(on_progress, "verifying", 12, "正在验证种子文章和公众号身份")
    verified_seed = _verify_article(seed_url)
    if not verified_seed.biz:
        raise WeChatDiscoveryError("种子文章未提供可校验的公众号身份")
    _mark_verified(str(seed["id"]), verified_seed)
    item_id, duplicate = _import_verified_article(
        verified_seed,
        auto_analyze=bool(request.get("auto_analyze")),
    )
    _mark_imported(str(seed["id"]), item_id=item_id, duplicate=duplicate)
    _update_seed_source(run_id, verified_seed)
    _refresh_run_counts(run_id)

    _check_cancel(cancel_check)
    _report(on_progress, "discovering", 28, f"正在公开搜索“{verified_seed.source_name or '同公众号'}”")
    results, provider_states = search_public_wechat_articles(
        verified_seed.source_name or verified_seed.biz
    )
    _save_cursor(
        run_id,
        seed_biz=verified_seed.biz,
        seed_source_name=verified_seed.source_name,
        search_providers=provider_states,
    )
    for result in results:
        _insert_search_candidate(run_id, result)

    candidates = [
        candidate
        for candidate in list_discovery_candidates(run_id)
        if candidate["discovered_via"] == "search"
    ]
    total = len(candidates)
    for index, candidate in enumerate(candidates, start=1):
        _check_cancel(cancel_check)
        _report(
            on_progress,
            "verifying",
            42 + (index - 1) / max(1, total) * 50,
            f"正在严格校验搜索候选 {index}/{total}",
        )
        try:
            verified = _verify_article(
                str(candidate["normalized_url"]),
                expected_biz=verified_seed.biz,
            )
            _mark_verified(str(candidate["id"]), verified)
        except Exception as exc:
            _mark_candidate_failed(str(candidate["id"]), str(exc))
        _refresh_run_counts(run_id)
    _set_review_required(run_id, _pending_review_count(run_id) > 0)
    return get_discovery_run(run_id)


def import_reviewed_candidates(
    run_id: str,
    candidate_ids: list[str],
    *,
    auto_analyze: bool = False,
    on_progress: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> dict[str, Any]:
    rows = validate_review_candidate_selection(run_id, candidate_ids)
    _set_review_import_status(run_id, "running")
    try:
        for index, row in enumerate(rows, start=1):
            _check_cancel(cancel_check)
            _report(
                on_progress,
                "importing",
                10 + (index - 1) / len(rows) * 80,
                f"正在导入已确认文章 {index}/{len(rows)}",
            )
            article = VerifiedArticle(
                url=str(row["normalized_url"]),
                canonical_source_id=str(row["canonical_source_id"] or ""),
                title=str(row["observed_title"] or "未命名公众号文章"),
                source_name=str(row["observed_source_name"] or ""),
                biz=str(row["observed_biz"] or ""),
                published_at=str(row["published_at"] or ""),
            )
            try:
                item_id, duplicate = _import_verified_article(article, auto_analyze=auto_analyze)
                _mark_imported(str(row["id"]), item_id=item_id, duplicate=duplicate)
            except Exception as exc:
                _mark_import_failed(str(row["id"]), str(exc))
            _refresh_run_counts(run_id)
        _set_review_import_status(run_id, "succeeded", reviewed=True)
        _set_review_required(run_id, _pending_review_count(run_id) > 0)
        return get_discovery_run(run_id)
    except Exception:
        _set_review_import_status(run_id, "failed")
        raise


def validate_review_candidate_selection(run_id: str, candidate_ids: list[str]) -> list[Any]:
    get_discovery_run(run_id)
    unique_ids = list(dict.fromkeys(str(value or "").strip() for value in candidate_ids))
    unique_ids = [value for value in unique_ids if value]
    if not unique_ids:
        raise WeChatDiscoveryError("请至少选择一篇已校验文章")
    if len(unique_ids) > MAX_REVIEW_IMPORT_ARTICLES:
        raise WeChatDiscoveryError(f"一次最多导入 {MAX_REVIEW_IMPORT_ARTICLES} 篇文章")
    if any(len(value) > 100 for value in unique_ids):
        raise WeChatDiscoveryError("候选文章标识无效")
    placeholders = ",".join("?" for _ in unique_ids)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM wechat_discovery_candidates
            WHERE run_id = ? AND id IN ({placeholders})
              AND verification_state = 'verified' AND import_state = 'pending'
            ORDER BY created_at, id
            """,
            (run_id, *unique_ids),
        ).fetchall()
    if len(rows) != len(unique_ids):
        raise WeChatDiscoveryError("选中的文章包含未校验、已导入或不属于该批次的记录")
    return list(rows)


def _discover_album(
    run_id: str,
    request: dict[str, Any],
    *,
    on_progress: ProgressCallback | None,
    cancel_check: CancelCheck | None,
) -> None:
    biz = str(request.get("biz") or "")
    album_id = str(request.get("album_id") or "")
    begin_msgid = ""
    begin_itemidx = ""
    seen_cursors: set[tuple[str, str]] = set()
    incremental = bool(request.get("incremental"))
    for page in range(1, MAX_ALBUM_PAGES + 1):
        _check_cancel(cancel_check)
        _report(on_progress, "discovering", min(30, 5 + page * 2), f"正在读取合集第 {page} 页")
        endpoint = album_endpoint(
            biz=biz,
            album_id=album_id,
            begin_msgid=begin_msgid,
            begin_itemidx=begin_itemidx,
        )
        payload = _fetch_album_payload(endpoint, referer=str(request.get("album_url") or ""))
        album_title = _album_title(payload)
        if album_title:
            _update_album_source_title(run_id, album_title)
        articles = _album_articles(payload)
        known_ids = _known_article_ids(articles) if incremental else set()
        known_count = 0
        inserted = 0
        for article in articles:
            canonical_id = canonical_wechat_article_id(str(article.get("url") or ""))
            if canonical_id in known_ids:
                known_count += 1
                continue
            if _insert_candidate(
                run_id,
                str(article.get("url") or ""),
                discovered_via="album",
                title=str(article.get("title") or ""),
                published_at=str(article.get("published_at") or ""),
            ):
                inserted += 1
        last_article = articles[-1] if articles else {}
        next_msgid = str(last_article.get("msgid") or "")
        next_itemidx = str(last_article.get("itemidx") or "")
        cursor = (next_msgid, next_itemidx)
        _save_cursor(run_id, page=page, begin_msgid=next_msgid, begin_itemidx=next_itemidx)
        continue_flag = _deep_value(payload, "continue_flag")
        if incremental and articles and known_count == len(articles):
            break
        if not articles or inserted == 0 or str(continue_flag).lower() in {"0", "false", "none"}:
            break
        if not next_msgid or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
        begin_msgid, begin_itemidx = cursor


def _fetch_album_payload(url: str, *, referer: str) -> dict[str, Any]:
    try:
        response = fetch_wechat_page(
            url,
            timeout=30,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Referer": referer or "https://mp.weixin.qq.com/",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        response.raise_for_status()
        payload = response.json()
    except WeChatDiscoveryError:
        raise
    except Exception as exc:
        raise WeChatDiscoveryError("公众号合集读取失败，请稍后重试或确认合集仍可公开访问") from exc
    if not isinstance(payload, dict):
        raise WeChatDiscoveryError("公众号合集返回了无法识别的数据")
    ret = _deep_value(payload, "ret")
    if ret not in {None, "", 0, "0"}:
        message = str(_deep_value(payload, "errmsg") or _deep_value(payload, "msg") or "")
        raise WeChatDiscoveryError(message or "公众号合集暂时拒绝访问")
    return payload


def _album_articles(payload: Any) -> list[dict[str, str]]:
    collected: list[dict[str, str]] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            raw_url = value.get("url") or value.get("link") or value.get("content_url")
            if raw_url:
                normalized = normalize_wechat_url(str(raw_url))
                if is_wechat_article_url(normalized) and normalized not in seen:
                    seen.add(normalized)
                    collected.append(
                        {
                            "url": normalized,
                            "title": str(value.get("title") or value.get("name") or ""),
                            "msgid": str(value.get("msgid") or value.get("mid") or ""),
                            "itemidx": str(value.get("itemidx") or value.get("idx") or ""),
                            "published_at": _timestamp_text(
                                value.get("create_time") or value.get("publish_time") or value.get("update_time")
                            ),
                        }
                    )
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    return collected


def _album_title(payload: Any) -> str:
    """Read the album title without mistaking an article title for metadata."""
    for metadata_key in ("base_info", "album_info"):
        metadata = _deep_value(payload, metadata_key)
        if not isinstance(metadata, dict):
            continue
        for title_key in ("title", "album_name", "name"):
            title = " ".join(str(metadata.get(title_key) or "").split())
            if title:
                return title[:160]
    return ""


def _known_article_ids(articles: list[dict[str, str]]) -> set[str]:
    canonical_ids = [
        canonical_wechat_article_id(str(article.get("url") or ""))
        for article in articles
    ]
    canonical_ids = [value for value in canonical_ids if value]
    if not canonical_ids:
        return set()
    placeholders = ",".join("?" for _ in canonical_ids)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT canonical_source_id
            FROM content_items
            WHERE source_provider = 'wechat'
              AND canonical_source_id IN ({placeholders})
            """,
            tuple(canonical_ids),
        ).fetchall()
    return {str(row["canonical_source_id"] or "") for row in rows}


def _process_candidate(
    candidate: dict[str, Any],
    *,
    expected_biz: str,
    auto_analyze: bool,
    library_folder_id: str | None = None,
) -> None:
    candidate_id = str(candidate["id"])
    try:
        verified = _verify_article(str(candidate["normalized_url"]), expected_biz=expected_biz)
        if not _mark_verified(candidate_id, verified):
            return
        _update_album_source_identity(str(candidate.get("run_id") or ""), verified)
        import_options: dict[str, Any] = {"auto_analyze": auto_analyze}
        if library_folder_id:
            import_options["library_folder_id"] = library_folder_id
        item_id, duplicate = _import_verified_article(verified, **import_options)
        _mark_imported(candidate_id, item_id=item_id, duplicate=duplicate)
    except Exception as exc:
        _mark_candidate_failed(candidate_id, str(exc))


def _insert_candidate(
    run_id: str,
    url: str,
    *,
    discovered_via: str,
    title: str = "",
    published_at: str = "",
) -> bool:
    normalized = normalize_wechat_url(url)
    if not is_wechat_article_url(normalized):
        return False
    now = utc_now_iso()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO wechat_discovery_candidates (
                id, run_id, normalized_url, canonical_source_id, discovered_via,
                observed_title, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                run_id,
                normalized,
                canonical_wechat_article_id(normalized),
                discovered_via,
                title,
                published_at or None,
                now,
                now,
            ),
        )
        connection.commit()
    return cursor.rowcount > 0


def _insert_search_candidate(run_id: str, result: SearchResult) -> bool:
    normalized = normalize_wechat_url(result.url)
    if not is_wechat_article_url(normalized):
        return False
    now = utc_now_iso()
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO wechat_discovery_candidates (
                id, run_id, normalized_url, canonical_source_id, discovered_via,
                observed_title, search_provider, search_query, search_rank,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'search', ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                run_id,
                normalized,
                canonical_wechat_article_id(normalized),
                result.title,
                result.provider,
                result.query,
                result.rank,
                now,
                now,
            ),
        )
        connection.commit()
    return cursor.rowcount > 0


def _start_run(run_id: str) -> None:
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_runs
            SET status = 'running', started_at = COALESCE(started_at, ?),
                finished_at = NULL, error_message = '', updated_at = ?
            WHERE id = ?
            """,
            (now, now, run_id),
        )
        connection.commit()


def _finish_run(run_id: str, status: str, error_message: str = "") -> None:
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_runs
            SET status = ?, error_message = ?, finished_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, error_message[:1000], now, now, run_id),
        )
        row = connection.execute(
            """
            SELECT run.source_id, run.imported_count, source.source_kind,
                   source.enabled, source.sync_interval_minutes,
                   source.consecutive_failure_count
            FROM wechat_discovery_runs AS run
            JOIN wechat_public_sources AS source ON source.id = run.source_id
            WHERE run.id = ?
            """,
            (run_id,),
        ).fetchone()
        if row:
            enabled_album = row["source_kind"] == "album" and bool(row["enabled"])
            next_sync_at = (
                _time_after_minutes(_valid_album_sync_interval(row["sync_interval_minutes"]))
                if enabled_album
                else None
            )
            failures = 0 if status == "succeeded" else int(row["consecutive_failure_count"] or 0) + 1
            connection.execute(
                """
                UPDATE wechat_public_sources
                SET last_discovery_at = ?, last_error = ?, next_sync_at = ?,
                    consecutive_failure_count = ?,
                    last_new_count = CASE WHEN ? = 'succeeded' THEN ? ELSE last_new_count END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    now,
                    error_message[:1000],
                    next_sync_at,
                    failures,
                    status,
                    int(row["imported_count"] or 0),
                    now,
                    row["source_id"],
                ),
            )
        connection.commit()


def _refresh_run_counts(run_id: str) -> None:
    now = utc_now_iso()
    with connect() as connection:
        counts = connection.execute(
            """
            SELECT
                COUNT(*) AS candidate_count,
                SUM(CASE WHEN verification_state = 'verified' THEN 1 ELSE 0 END) AS verified_count,
                SUM(CASE WHEN import_state = 'imported' THEN 1 ELSE 0 END) AS imported_count,
                SUM(CASE WHEN import_state = 'duplicate' THEN 1 ELSE 0 END) AS duplicate_count,
                SUM(CASE WHEN import_state = 'failed' THEN 1 ELSE 0 END) AS failed_count
            FROM wechat_discovery_candidates
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        connection.execute(
            """
            UPDATE wechat_discovery_runs
            SET candidate_count = ?, verified_count = ?, imported_count = ?,
                duplicate_count = ?, failed_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                int(counts["candidate_count"] or 0),
                int(counts["verified_count"] or 0),
                int(counts["imported_count"] or 0),
                int(counts["duplicate_count"] or 0),
                int(counts["failed_count"] or 0),
                now,
                run_id,
            ),
        )
        connection.commit()


def _mark_verified(candidate_id: str, article: VerifiedArticle) -> bool:
    with connect() as connection:
        current = connection.execute(
            "SELECT run_id FROM wechat_discovery_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        duplicate = connection.execute(
            """
            SELECT id, content_item_id
            FROM wechat_discovery_candidates
            WHERE run_id = ? AND id <> ? AND canonical_source_id = ?
              AND verification_state = 'verified'
            LIMIT 1
            """,
            (
                current["run_id"] if current else "",
                candidate_id,
                article.canonical_source_id,
            ),
        ).fetchone()
        if duplicate:
            connection.execute(
                """
                UPDATE wechat_discovery_candidates
                SET canonical_source_id = ?, observed_title = ?,
                    observed_source_name = ?, observed_biz = ?,
                    published_at = COALESCE(NULLIF(?, ''), published_at),
                    verification_state = 'verified', import_state = 'duplicate',
                    content_item_id = ?, error_message = '候选文章重复，已跳过',
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    article.canonical_source_id,
                    article.title,
                    article.source_name,
                    article.biz,
                    article.published_at,
                    duplicate["content_item_id"],
                    utc_now_iso(),
                    candidate_id,
                ),
            )
            connection.commit()
            return False
        connection.execute(
            """
            UPDATE wechat_discovery_candidates
            SET canonical_source_id = ?, observed_title = ?,
                observed_source_name = ?, observed_biz = ?,
                published_at = COALESCE(NULLIF(?, ''), published_at),
                verification_state = 'verified', error_message = '', updated_at = ?
            WHERE id = ?
            """,
            (
                article.canonical_source_id,
                article.title,
                article.source_name,
                article.biz,
                article.published_at,
                utc_now_iso(),
                candidate_id,
            ),
        )
        connection.commit()
    return True


def _mark_imported(candidate_id: str, *, item_id: str, duplicate: bool) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_candidates
            SET import_state = ?, content_item_id = ?, updated_at = ?
            WHERE id = ?
            """,
            ("duplicate" if duplicate else "imported", item_id, utc_now_iso(), candidate_id),
        )
        connection.commit()


def _mark_import_failed(candidate_id: str, message: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_candidates
            SET import_state = 'failed', error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (str(message or "导入失败")[:1000], utc_now_iso(), candidate_id),
        )
        connection.commit()


def _mark_candidate_failed(candidate_id: str, message: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_candidates
            SET verification_state = CASE
                    WHEN verification_state = 'verified' THEN verification_state
                    ELSE 'rejected'
                END,
                import_state = 'failed', error_message = ?, updated_at = ?
            WHERE id = ?
            """,
            (str(message or "处理失败")[:1000], utc_now_iso(), candidate_id),
        )
        connection.commit()


def _update_seed_source(run_id: str, article: VerifiedArticle) -> None:
    now = utc_now_iso()
    with connect() as connection:
        row = connection.execute(
            "SELECT source_id FROM wechat_discovery_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row:
            connection.execute(
                """
                UPDATE wechat_public_sources
                SET title = ?, biz = ?, source_url = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    article.source_name or article.title,
                    article.biz or None,
                    article.url,
                    now,
                    row["source_id"],
                ),
            )
        connection.commit()


def _update_album_source_identity(run_id: str, article: VerifiedArticle) -> None:
    if not run_id or not article.biz:
        return
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_public_sources
            SET biz = COALESCE(NULLIF(?, ''), biz), updated_at = ?
            WHERE source_kind = 'album' AND id = (
                SELECT source_id FROM wechat_discovery_runs WHERE id = ?
            )
            """,
            (article.biz, now, run_id),
        )
        connection.commit()


def _update_album_source_title(run_id: str, album_title: str) -> None:
    title = " ".join(str(album_title or "").split())[:160]
    if not run_id or not title:
        return
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_public_sources
            SET title = ?, updated_at = ?
            WHERE source_kind = 'album' AND id = (
                SELECT source_id FROM wechat_discovery_runs WHERE id = ?
            )
            """,
            (title, utc_now_iso(), run_id),
        )
        connection.commit()


def _prepare_album_folder(run_id: str) -> str:
    from services.content_index import (
        assign_wechat_public_album_items,
        ensure_wechat_public_album_folder,
    )

    with connect() as connection:
        source = connection.execute(
            """
            SELECT source.id, source.title
            FROM wechat_discovery_runs AS run
            JOIN wechat_public_sources AS source ON source.id = run.source_id
            WHERE run.id = ? AND source.source_kind = 'album'
            """,
            (run_id,),
        ).fetchone()
        if not source:
            raise WeChatDiscoveryError("公众号合集来源不存在")
        folder_id = ensure_wechat_public_album_folder(
            connection,
            str(source["id"]),
            str(source["title"] or ""),
        )
        assign_wechat_public_album_items(connection, str(source["id"]), folder_id)
        connection.commit()
    return folder_id


def _pending_review_count(run_id: str) -> int:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM wechat_discovery_candidates
            WHERE run_id = ? AND verification_state = 'verified'
              AND import_state = 'pending'
            """,
            (run_id,),
        ).fetchone()
    return int(row["count"] or 0)


def _set_review_required(run_id: str, required: bool) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_runs
            SET review_required = ?, updated_at = ?
            WHERE id = ?
            """,
            (int(required), utc_now_iso(), run_id),
        )
        connection.commit()


def _set_review_import_status(run_id: str, status: str, *, reviewed: bool = False) -> None:
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """
            UPDATE wechat_discovery_runs
            SET review_import_status = ?,
                reviewed_at = CASE WHEN ? = 1 THEN ? ELSE reviewed_at END,
                updated_at = ?
            WHERE id = ?
            """,
            (status, int(reviewed), now, now, run_id),
        )
        connection.commit()


def enqueue_due_album_sources() -> list[str]:
    """Create durable background checks for every due public album source."""
    ensure_database_initialized()
    now = utc_now_iso()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, title, source_url
            FROM wechat_public_sources
            WHERE source_kind = 'album' AND enabled = 1
              AND (next_sync_at IS NULL OR next_sync_at = '' OR next_sync_at <= ?)
            ORDER BY COALESCE(next_sync_at, created_at), created_at
            """,
            (now,),
        ).fetchall()
    from services.task_manager import task_manager

    run_ids: list[str] = []
    for row in rows:
        run: dict[str, Any] | None = None
        try:
            run = create_album_sync_run(str(row["id"]))
            task = task_manager.create_source_sync(
                {
                    "kind": "wechat_public_discovery",
                    "source_id": str(row["id"]),
                    "payload": {"run_id": run["id"]},
                },
                source_title=f"自动检查合集：{row['title'] or '公众号合集'}",
                source_url=str(row["source_url"] or "") or None,
                execution_mode="background",
            )
            bind_discovery_task(run["id"], task.task_id)
        except WeChatDiscoveryError:
            continue
        except Exception as exc:
            if run:
                fail_discovery_submission(run["id"], str(exc))
            continue
        run_ids.append(run["id"])
    return run_ids


def _save_cursor(run_id: str, **cursor: Any) -> None:
    with connect() as connection:
        row = connection.execute(
            "SELECT cursor_json FROM wechat_discovery_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        merged = _json_object(row["cursor_json"] if row else "{}")
        merged.update(cursor)
        connection.execute(
            "UPDATE wechat_discovery_runs SET cursor_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), utc_now_iso(), run_id),
        )
        connection.commit()
    _refresh_run_counts(run_id)


def _serialize_public_album_source(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["enabled"] = bool(payload.get("enabled"))
    payload["auto_analyze"] = bool(payload.get("auto_analyze"))
    payload["sync_interval_minutes"] = _valid_album_sync_interval(
        payload.get("sync_interval_minutes")
    )
    payload["consecutive_failure_count"] = max(
        0,
        int(payload.get("consecutive_failure_count") or 0),
    )
    payload["last_new_count"] = max(0, int(payload.get("last_new_count") or 0))
    return payload


def _valid_album_sync_interval(value: Any) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = DEFAULT_ALBUM_SYNC_INTERVAL_MINUTES
    if not MIN_ALBUM_SYNC_INTERVAL_MINUTES <= interval <= MAX_ALBUM_SYNC_INTERVAL_MINUTES:
        raise WeChatDiscoveryError(
            f"合集自动检测间隔需要在 {MIN_ALBUM_SYNC_INTERVAL_MINUTES} 到 "
            f"{MAX_ALBUM_SYNC_INTERVAL_MINUTES} 分钟之间"
        )
    return interval


def _time_after_minutes(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=int(minutes))).isoformat()


def _serialize_run(row: Any, *, include_request: bool = True) -> dict[str, Any]:
    payload = dict(row)
    request = _json_object(payload.pop("request_json", "{}"))
    if include_request:
        payload["request"] = request
    payload["cursor"] = _json_object(payload.pop("cursor_json", "{}"))
    return payload


def _json_object(value: Any) -> dict[str, Any]:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _deep_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for nested in value.values():
            found = _deep_value(nested, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _deep_value(nested, key)
            if found is not None:
                return found
    return None


def _timestamp_text(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    china = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(timestamp, china).isoformat()


def _check_cancel(cancel_check: CancelCheck | None) -> None:
    if cancel_check and cancel_check():
        raise WeChatDiscoveryError("任务已取消")


def _report(callback: ProgressCallback | None, stage: str, progress: float, message: str) -> None:
    if callback:
        callback(stage, max(0.0, min(100.0, progress)), message)
