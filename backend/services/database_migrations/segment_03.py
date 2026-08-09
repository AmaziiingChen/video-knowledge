"""Archived SQLite migrations: third schema segment. Append-only."""

from __future__ import annotations

import json
import re
import sqlite3

from services.database_migrations.common import _add_column_if_missing, utc_now_iso

def _migration_060_group_report_stage_adapters(connection: sqlite3.Connection) -> None:
    """Replace the single interval guide with a group context and four adapters."""
    connection.executescript(
        """
        CREATE TABLE wechat_report_prompts_v60 (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL CHECK(report_type IN (
                'group_context',
                'group_report_source_summary',
                'group_report_section_plan',
                'group_report_section_writer',
                'group_report_overview'
            )),
            template TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            template_version TEXT NOT NULL DEFAULT '',
            display_name TEXT,
            UNIQUE(group_id, report_type)
        );

        INSERT INTO wechat_report_prompts_v60 (
            id, group_id, report_type, template, created_at, updated_at,
            template_version, display_name
        )
        SELECT id, group_id, 'group_context', template, created_at, updated_at,
               COALESCE(template_version, ''), '组别说明'
        FROM wechat_report_prompts
        WHERE report_type = 'range';

        INSERT OR IGNORE INTO wechat_report_prompts_v60 (
            id, group_id, report_type, template, created_at, updated_at,
            template_version, display_name
        )
        SELECT id, group_id, 'group_context', template, created_at, updated_at,
               COALESCE(template_version, ''), '组别说明'
        FROM wechat_report_prompts
        WHERE report_type IN ('daily', 'weekly');

        DROP TABLE wechat_report_prompts;
        ALTER TABLE wechat_report_prompts_v60 RENAME TO wechat_report_prompts;
        CREATE INDEX idx_wechat_report_prompts_group
        ON wechat_report_prompts(group_id, report_type);
        """
    )


def _migration_062_group_report_event_ledger(connection: sqlite3.Connection) -> None:
    """Add the event fact-ledger adapter without invalidating saved prompts."""
    connection.executescript(
        """
        CREATE TABLE wechat_report_prompts_v61 (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL CHECK(report_type IN (
                'group_context',
                'group_report_source_summary',
                'group_report_section_plan',
                'group_report_event_ledger',
                'group_report_section_writer',
                'group_report_overview'
            )),
            template TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            template_version TEXT NOT NULL DEFAULT '',
            display_name TEXT,
            UNIQUE(group_id, report_type)
        );

        INSERT INTO wechat_report_prompts_v61 (
            id, group_id, report_type, template, created_at, updated_at,
            template_version, display_name
        )
        SELECT id, group_id, report_type, template, created_at, updated_at,
               COALESCE(template_version, ''), display_name
        FROM wechat_report_prompts;

        DROP TABLE wechat_report_prompts;
        ALTER TABLE wechat_report_prompts_v61 RENAME TO wechat_report_prompts;
        CREATE INDEX idx_wechat_report_prompts_group
        ON wechat_report_prompts(group_id, report_type);
        """
    )
    from services.prompt_file_store import write_report_prompt_file
    from services.wechat_reports import (
        CUSTOM_REPORT_PROMPT_VERSION,
        DEFAULT_REPORT_PROMPT_VERSION,
        REPORT_PROMPT_TYPE,
        _campus_report_prompts,
        _ensure_default_prompts,
    )

    groups = connection.execute("SELECT id, name FROM wechat_subscription_groups").fetchall()
    for group in groups:
        group_id = str(group["id"])
        _ensure_default_prompts(connection, group_id)
        if str(group["name"]) == "校园生活":
            now = utc_now_iso()
            connection.execute(
                """UPDATE wechat_report_prompts
                   SET template=?, template_version=?, display_name=?, updated_at=?
                   WHERE group_id=? AND report_type=? AND template_version != ?""",
                (
                    _campus_report_prompts(REPORT_PROMPT_TYPE),
                    DEFAULT_REPORT_PROMPT_VERSION,
                    "组别说明",
                    now,
                    group_id,
                    REPORT_PROMPT_TYPE,
                    CUSTOM_REPORT_PROMPT_VERSION,
                ),
            )
        rows = connection.execute(
            """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                      COALESCE(NULLIF(p.display_name, ''), '分组报告提示词') AS display_name,
                      p.updated_at, g.name AS group_name
               FROM wechat_report_prompts p JOIN wechat_subscription_groups g ON g.id=p.group_id
               WHERE p.group_id=?""",
            (group_id,),
        ).fetchall()
        for row in rows:
            write_report_prompt_file(dict(row))


def _migration_061_openclaw_notification_delivery(connection: sqlite3.Connection) -> None:
    """Make terminal WeChat delivery retryable without retaining recipient IDs."""
    _add_column_if_missing(
        connection,
        "openclaw_task_bindings",
        "notification_reservation_id",
        "TEXT",
    )
    _add_column_if_missing(
        connection,
        "openclaw_task_bindings",
        "notification_reserved_at",
        "TEXT",
    )
    _add_column_if_missing(
        connection,
        "openclaw_task_bindings",
        "notification_attempts",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection,
        "openclaw_task_bindings",
        "notification_last_error",
        "TEXT",
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_openclaw_task_bindings_notification
        ON openclaw_task_bindings(notified_at, notification_reserved_at, updated_at)
        """
    )
    # This delivery mechanism is opt-in from the upgrade onward.  Do not turn
    # every historical terminal task into an unexpected Weixin notification.
    connection.execute(
        """
        UPDATE openclaw_task_bindings
        SET notified_at = COALESCE(notified_at, tasks.updated_at)
        FROM tasks
        WHERE tasks.id = openclaw_task_bindings.task_id
          AND tasks.status IN ('succeeded', 'failed', 'cancelled')
          AND openclaw_task_bindings.notified_at IS NULL
        """
    )


def _migration_063_report_prompt_history_and_generation_metadata(
    connection: sqlite3.Connection,
) -> None:
    """Preserve prompt revisions and the exact generation configuration."""
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "generation_metadata_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_report_prompt_versions (
            id TEXT PRIMARY KEY,
            prompt_id TEXT NOT NULL REFERENCES wechat_report_prompts(id) ON DELETE CASCADE,
            group_id TEXT NOT NULL,
            report_type TEXT NOT NULL,
            template TEXT NOT NULL,
            template_hash TEXT NOT NULL,
            template_version TEXT NOT NULL,
            display_name TEXT,
            change_kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(prompt_id, template_hash, template_version)
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_report_prompt_versions_prompt
        ON wechat_report_prompt_versions(prompt_id, created_at DESC);
        """
    )
    from hashlib import sha256
    import uuid

    rows = connection.execute("SELECT * FROM wechat_report_prompts").fetchall()
    for row in rows:
        template = str(row["template"])
        connection.execute(
            """INSERT OR IGNORE INTO wechat_report_prompt_versions
               (id,prompt_id,group_id,report_type,template,template_hash,
                template_version,display_name,change_kind,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                uuid.uuid4().hex,
                row["id"],
                row["group_id"],
                row["report_type"],
                template,
                sha256(template.encode("utf-8")).hexdigest(),
                str(row["template_version"] or ""),
                row["display_name"],
                "migration_snapshot",
                str(row["updated_at"]),
            ),
        )


def _migration_064_ai_call_finish_reason(connection: sqlite3.Connection) -> None:
    """Keep enough provider metadata to distinguish truncation from schema drift."""
    _add_column_if_missing(connection, "ai_calls", "finish_reason", "TEXT")


def _migration_065_wechat_cover_planning_and_local_assets(
    connection: sqlite3.Connection,
) -> None:
    """Persist approved cover plans and local files without storing image blobs."""
    _add_column_if_missing(connection, "wechat_reports", "cover_path", "TEXT")
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "cover_plan_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "cover_prompt_metadata_json",
        "TEXT NOT NULL DEFAULT '{}'",
    )
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "cover_last_error",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(connection, "wechat_reports", "cover_plan_updated_at", "TEXT")
    _add_column_if_missing(connection, "wechat_reports", "cover_generated_at", "TEXT")


def _migration_066_image_generation_usage(connection: sqlite3.Connection) -> None:
    """Track image calls separately from token-metered text calls."""
    _add_column_if_missing(
        connection,
        "ai_calls",
        "usage_unit",
        "TEXT NOT NULL DEFAULT 'tokens'",
    )
    _add_column_if_missing(
        connection,
        "ai_calls",
        "image_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(connection, "ai_calls", "unit_price_cny", "REAL")
    _add_column_if_missing(connection, "ai_calls", "billing_region", "TEXT")
    _add_column_if_missing(connection, "ai_calls", "request_id", "TEXT")
    _add_column_if_missing(connection, "ai_calls", "image_width", "INTEGER")
    _add_column_if_missing(connection, "ai_calls", "image_height", "INTEGER")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_calls_usage_created
        ON ai_calls(usage_unit, created_at DESC)
        """
    )

    account = connection.execute(
        "SELECT cover_endpoint FROM wechat_publishing_accounts WHERE id=1"
    ).fetchone()
    endpoint = str(account["cover_endpoint"] or "") if account else ""
    reports = connection.execute(
        """
        SELECT report.content_item_id, report.cover_generated_at,
               report.cover_prompt_metadata_json
        FROM wechat_reports AS report
        WHERE report.cover_status='qwen_generated'
          AND report.cover_generated_at IS NOT NULL
        """
    ).fetchall()
    for report in reports:
        content_item_id = str(report["content_item_id"] or "")
        already_recorded = connection.execute(
            """
            SELECT 1 FROM ai_calls
            WHERE content_item_id=? AND usage_unit='images'
            LIMIT 1
            """,
            (content_item_id,),
        ).fetchone()
        if already_recorded:
            continue
        try:
            metadata = json.loads(str(report["cover_prompt_metadata_json"] or "{}"))
        except (TypeError, ValueError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        provider = str(metadata.get("provider") or "qwen")
        model = str(metadata.get("model") or "qwen-image-2.0")
        size_match = re.fullmatch(r"\s*(\d+)\s*[*x×]\s*(\d+)\s*", str(metadata.get("size") or ""))
        width = int(size_match.group(1)) if size_match else None
        height = int(size_match.group(2)) if size_match else None
        region, unit_price = _qwen_image_catalog_price(model, endpoint)
        generated_at = str(report["cover_generated_at"] or utc_now_iso())
        connection.execute(
            """
            INSERT OR IGNORE INTO ai_calls (
                id, content_item_id, call_type, provider, model,
                input_chars, output_chars, prompt_tokens, completion_tokens,
                estimated_cost, elapsed_seconds, error, created_at,
                usage_unit, image_count, unit_price_cny, billing_region,
                request_id, image_width, image_height
            ) VALUES (?, ?, 'wechat_cover_image', ?, ?, ?, 0, NULL, NULL, ?, NULL, NULL, ?,
                      'images', 1, ?, ?, ?, ?, ?)
            """,
            (
                f"wechat-cover-backfill-{content_item_id}",
                content_item_id,
                provider,
                model,
                len(str(metadata.get("resolved_image_prompt") or "")),
                unit_price,
                generated_at,
                unit_price,
                region,
                str(metadata.get("request_id") or "") or None,
                width,
                height,
            ),
        )


def _qwen_image_catalog_price(model: str, endpoint: str) -> tuple[str, float | None]:
    """Return the July 2026 public list price used only for local estimates."""
    normalized_model = str(model or "").strip().lower()
    normalized_endpoint = str(endpoint or "").strip().lower()
    international = "intl" in normalized_endpoint or "ap-southeast" in normalized_endpoint
    region = "international" if international else "cn-mainland"
    if normalized_model.startswith("qwen-image-2.0-pro"):
        return region, 0.550443 if international else 0.5
    if normalized_model.startswith("qwen-image-2.0"):
        return region, 0.256873 if international else 0.2
    return region, None



def _migration_074_completion_notifications(connection: sqlite3.Connection) -> None:
    """Persist local-only completion events for the unsigned desktop shell."""
    _add_column_if_missing(connection, "wechat_subscriptions", "notify_on_new", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "rss_sources", "notify_on_new", "INTEGER NOT NULL DEFAULT 0")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS completion_notifications (
            id TEXT PRIMARY KEY,
            event_key TEXT NOT NULL UNIQUE,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            content_item_id TEXT REFERENCES content_items(id) ON DELETE CASCADE,
            target_view TEXT NOT NULL DEFAULT 'library',
            created_at TEXT NOT NULL,
            seen_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_completion_notifications_pending
        ON completion_notifications(seen_at, created_at DESC);
        """
    )


def _migration_075_library_folder_pinning(connection: sqlite3.Connection) -> None:
    """Keep the sidebar's pinned-folder projection local and reversible."""
    _add_column_if_missing(connection, "library_folders", "is_pinned", "INTEGER NOT NULL DEFAULT 0")


def _migration_076_report_group_schedules(connection: sqlite3.Connection) -> None:
    """Persist one explicit local report-generation plan per source group."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_report_group_schedules (
            group_id TEXT PRIMARY KEY REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            enabled INTEGER NOT NULL DEFAULT 0,
            report_type TEXT NOT NULL DEFAULT 'weekly' CHECK(report_type IN ('daily', 'weekly')),
            weekdays_json TEXT NOT NULL DEFAULT '[1]',
            time_of_day TEXT NOT NULL DEFAULT '09:00',
            last_run_slot TEXT NOT NULL DEFAULT '',
            last_status TEXT NOT NULL DEFAULT 'idle',
            last_error TEXT NOT NULL DEFAULT '',
            last_run_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_report_group_schedules_due
        ON wechat_report_group_schedules(enabled, time_of_day);
        """
    )


def _migration_077_xiaohongshu_favorites(connection: sqlite3.Connection) -> None:
    """Store XHS personal favorites without changing legacy video-source rows."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS xiaohongshu_favorite_sources (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '我的小红书收藏',
            library_folder_id TEXT REFERENCES library_folders(id) ON DELETE SET NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            auto_analyze INTEGER NOT NULL DEFAULT 1,
            sync_interval_minutes INTEGER NOT NULL DEFAULT 360,
            sync_limit INTEGER NOT NULL DEFAULT 5,
            last_sync_at TEXT,
            next_sync_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS xiaohongshu_favorite_items (
            source_id TEXT NOT NULL REFERENCES xiaohongshu_favorite_sources(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            note_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_id, note_id)
        );
        """
    )


def _migration_079_backfill_wechat_source_names(connection: sqlite3.Connection) -> None:
    """Restore publisher labels for legacy WeChat subscription articles."""
    connection.execute(
        """
        UPDATE content_items AS content
        SET source_name = (
                SELECT subscription.mp_name
                FROM wechat_subscription_items AS subscription_item
                JOIN wechat_subscriptions AS subscription
                  ON subscription.id = subscription_item.subscription_id
                WHERE subscription_item.content_item_id = content.id
                  AND NULLIF(TRIM(subscription.mp_name), '') IS NOT NULL
                ORDER BY subscription_item.discovered_at DESC
                LIMIT 1
            ),
            updated_at = ?
        WHERE content.source_provider = 'wechat'
          AND NULLIF(TRIM(content.source_name), '') IS NULL
          AND EXISTS (
                SELECT 1
                FROM wechat_subscription_items AS subscription_item
                JOIN wechat_subscriptions AS subscription
                  ON subscription.id = subscription_item.subscription_id
                WHERE subscription_item.content_item_id = content.id
                  AND NULLIF(TRIM(subscription.mp_name), '') IS NOT NULL
            )
        """,
        (utc_now_iso(),),
    )


def _migration_090_unify_video_source_subscriptions(connection: sqlite3.Connection) -> None:
    """Move legacy Bilibili/Douyin favorites into the durable source model.

    Favorites used to be scheduled through a separate table despite being the
    same kind of incremental media source as a creator page.  Preserve every
    old row and history record, but let the creator-source scheduler become
    the only active scheduler for these two providers.  Xiaohongshu remains
    intentionally untouched until its URL-based source contract is proven.
    """
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS creator_source_items (
            source_id TEXT NOT NULL REFERENCES creator_sources(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            remote_item_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_id, remote_item_id)
        );
        CREATE INDEX IF NOT EXISTS idx_creator_source_items_content
        ON creator_source_items(content_item_id, source_id);
        """
    )
    rows = connection.execute(
        """SELECT * FROM favorite_sources
           WHERE provider IN ('bilibili', 'douyin')"""
    ).fetchall()
    for row in rows:
        provider = str(row["provider"])
        source_url = str(row["source_url"])
        if provider == "douyin":
            source_kind, creator_key = "favorites", "self"
        else:
            match = re.search(r"space\\.bilibili\\.com/(\\d+)/favlist[^#]*[?&]fid=(\\d+)", source_url)
            if not match:
                # Keep an unrecognised legacy row intact and disabled in its
                # original table instead of guessing an identity.
                continue
            source_kind, creator_key = "favorites", f"{match.group(1)}:{match.group(2)}"
        identity = f"{provider}:{source_kind}:{creator_key}"
        existing = connection.execute(
            "SELECT id FROM creator_sources WHERE source_identity=?", (identity,)
        ).fetchone()
        target_id = str(existing["id"]) if existing else str(row["id"])
        if not existing:
            connection.execute(
                """INSERT INTO creator_sources (
                    id, provider, source_url, source_kind, creator_key, creator_name,
                    source_identity, library_folder_id, enabled, auto_process,
                    processing_mode, sync_interval_minutes, sync_limit, queue_limit,
                    last_sync_at, next_sync_at, last_seen_published_at, last_error,
                    consecutive_failure_count, last_discovered_count, last_created_count,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)""",
                (
                    target_id, provider, source_url, source_kind, creator_key,
                    str(row["title"] or ("我的抖音收藏" if provider == "douyin" else "B站收藏夹")),
                    identity, row["library_folder_id"], row["enabled"], row["auto_analyze"],
                    "full" if bool(row["auto_analyze"]) else "metadata",
                    row["sync_interval_minutes"], row["sync_limit"], 1,
                    row["last_sync_at"], row["next_sync_at"], row["last_error"],
                    row["consecutive_failure_count"], row["last_discovered_count"],
                    row["last_created_count"], row["created_at"], row["updated_at"],
                ),
            )
        connection.execute(
            """INSERT OR IGNORE INTO creator_source_items
               (source_id, content_item_id, remote_item_id, created_at)
               SELECT ?, content_item_id, remote_video_id, created_at
               FROM favorite_source_items WHERE source_id=?""",
            (target_id, str(row["id"])),
        )
        connection.execute(
            """INSERT OR IGNORE INTO creator_sync_runs
               (id, source_id, status, message, discovered_count, created_count, created_at)
               SELECT id, ?, CASE WHEN status='success' THEN 'succeeded' ELSE status END,
                      message, discovered_count, created_count, created_at
               FROM favorite_sync_runs WHERE source_id=?""",
            (target_id, str(row["id"])),
        )
        # A migrated source is now scheduled only by creator_scheduler.  The
        # old rows remain as a recoverable audit trail and for downgrade safety.
        connection.execute("UPDATE favorite_sources SET enabled=0 WHERE id=?", (str(row["id"]),))


def _migration_091_unify_xiaohongshu_favorite_subscription(connection: sqlite3.Connection) -> None:
    """Move the session-scoped XHS favorites source into creator subscriptions.

    The old implementation had its own five-item scheduler.  It is retained
    as an audit record only; active checks, source membership and de-duplication
    now all live in the shared creator-source contract.
    """
    rows = connection.execute("SELECT * FROM xiaohongshu_favorite_sources").fetchall()
    for row in rows:
        legacy_id = str(row["id"])
        identity = "xiaohongshu:favorites:self"
        existing = connection.execute(
            "SELECT id FROM creator_sources WHERE source_identity=?", (identity,)
        ).fetchone()
        target_id = str(existing["id"]) if existing else legacy_id
        if not existing:
            connection.execute(
                """INSERT INTO creator_sources (
                    id, provider, source_url, source_kind, creator_key, creator_name,
                    source_identity, library_folder_id, enabled, auto_process,
                    processing_mode, sync_interval_minutes, sync_limit, queue_limit,
                    last_sync_at, next_sync_at, last_seen_published_at, last_error,
                    consecutive_failure_count, last_discovered_count, last_created_count,
                    created_at, updated_at
                ) VALUES (?, 'xiaohongshu', ?, 'favorites', 'self', ?, ?, ?, ?, ?, ?, ?, 1,
                          ?, ?, ?, NULL, ?, 0, 0, 0, ?, ?)""",
                (
                    target_id,
                    "https://www.xiaohongshu.com/user/profile/self?tab=collect",
                    str(row["title"] or "我的小红书收藏"),
                    identity,
                    row["library_folder_id"],
                    row["enabled"],
                    row["auto_analyze"],
                    "full" if bool(row["auto_analyze"]) else "metadata",
                    row["sync_interval_minutes"],
                    row["sync_limit"],
                    row["last_sync_at"],
                    row["next_sync_at"],
                    row["last_error"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        connection.execute(
            """INSERT OR IGNORE INTO creator_source_items
               (source_id, content_item_id, remote_item_id, created_at)
               SELECT ?, content_item_id, note_id, created_at
               FROM xiaohongshu_favorite_items WHERE source_id=?""",
            (target_id, legacy_id),
        )
        connection.execute(
            "UPDATE xiaohongshu_favorite_sources SET enabled=0 WHERE id=?", (legacy_id,)
        )


def _migration_092_repair_placeholder_content_items(connection: sqlite3.Connection) -> None:
    """Repair legacy rows that were created before metadata/title contracts settled."""
    rows = connection.execute(
        """
        SELECT id, source_provider, content_type, canonical_source_id, source_url, title
        FROM content_items
        WHERE source_provider = 'xiaohongshu'
           OR trim(COALESCE(title, '')) = ''
           OR (source_provider IN ('bilibili', 'douyin') AND title = '未命名视频')
        """
    ).fetchall()
    for row in rows:
        provider = str(row["source_provider"] or "")
        content_type = "article" if provider == "xiaohongshu" else str(row["content_type"] or "video")
        raw_title = " ".join(str(row["title"] or "").split())
        placeholder_titles = {"", "未命名视频", "无标题小红书笔记", "小红书图文"}
        title = raw_title
        if raw_title in placeholder_titles:
            labels = {
                "bilibili": "B站视频",
                "douyin": "抖音视频",
                "xiaohongshu": "小红书图文",
            }
            identity = str(row["canonical_source_id"] or row["source_url"] or "").strip()
            title = f"{labels.get(provider, '未命名内容')} · {identity[:40]}" if identity else labels.get(provider, "未命名内容")
        connection.execute(
            "UPDATE content_items SET content_type=?, title=? WHERE id=?",
            (content_type, title, row["id"]),
        )
