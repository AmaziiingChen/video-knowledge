"""Archived SQLite migrations: first schema segment. Append-only."""

from __future__ import annotations

import sqlite3

from services.database_migrations.common import _add_column_if_missing, utc_now_iso

def _migration_001_initial_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS series (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            source_provider TEXT,
            source_url TEXT,
            cover_url TEXT,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS content_items (
            id TEXT PRIMARY KEY,
            content_type TEXT NOT NULL DEFAULT 'video',
            source_provider TEXT NOT NULL,
            source_url TEXT,
            canonical_source_id TEXT,
            title TEXT NOT NULL DEFAULT '',
            cover_url TEXT,
            duration_seconds REAL,
            status TEXT NOT NULL DEFAULT 'inbox',
            series_id TEXT REFERENCES series(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(source_provider, canonical_source_id)
        );

        CREATE TABLE IF NOT EXISTS series_items (
            series_id TEXT NOT NULL REFERENCES series(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            source_page INTEGER,
            title_override TEXT,
            PRIMARY KEY(series_id, content_item_id)
        );

        CREATE TABLE IF NOT EXISTS media_assets (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            asset_type TEXT NOT NULL,
            path TEXT NOT NULL,
            mime_type TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            retention_policy TEXT NOT NULL DEFAULT 'default',
            expires_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS text_assets (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            asset_type TEXT NOT NULL,
            source TEXT NOT NULL,
            provider TEXT,
            model TEXT,
            mode TEXT,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transcript_segments (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            text_asset_id TEXT REFERENCES text_assets(id) ON DELETE CASCADE,
            start_seconds REAL,
            end_seconds REAL,
            text TEXT NOT NULL,
            confidence REAL,
            source TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id TEXT PRIMARY KEY,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE CASCADE,
            series_id TEXT REFERENCES series(id) ON DELETE CASCADE,
            summary_type TEXT NOT NULL,
            prompt_template_id TEXT,
            prompt_version TEXT,
            llm_provider TEXT,
            model TEXT,
            json_path TEXT,
            markdown_path TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS qa_threads (
            id TEXT PRIMARY KEY,
            scope TEXT NOT NULL,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE CASCADE,
            series_id TEXT REFERENCES series(id) ON DELETE CASCADE,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS qa_messages (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES qa_threads(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            write_to_obsidian INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS prompt_templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            version TEXT NOT NULL,
            template TEXT NOT NULL,
            variables_schema TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(name, task_type, version)
        );

        CREATE TABLE IF NOT EXISTS ai_calls (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE SET NULL,
            series_id TEXT REFERENCES series(id) ON DELETE SET NULL,
            call_type TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_template_id TEXT,
            prompt_version TEXT,
            input_chars INTEGER NOT NULL DEFAULT 0,
            output_chars INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            prompt_cache_hit_tokens INTEGER,
            prompt_cache_miss_tokens INTEGER,
            estimated_cost REAL,
            elapsed_seconds REAL,
            cache_hit INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            finish_reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE SET NULL,
            series_id TEXT REFERENCES series(id) ON DELETE SET NULL,
            request_json TEXT,
            result_json TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            priority INTEGER NOT NULL DEFAULT 100,
            current_stage TEXT,
            progress REAL NOT NULL DEFAULT 0,
            error_type TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS task_events (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            stage TEXT,
            level TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            progress REAL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS obsidian_sync (
            id TEXT PRIMARY KEY,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE CASCADE,
            series_id TEXT REFERENCES series(id) ON DELETE CASCADE,
            markdown_draft_path TEXT NOT NULL,
            obsidian_path TEXT,
            last_synced_hash TEXT,
            external_hash TEXT,
            sync_status TEXT NOT NULL DEFAULT 'dirty',
            last_synced_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_content_items_status ON content_items(status);
        CREATE INDEX IF NOT EXISTS idx_content_items_provider ON content_items(source_provider);
        CREATE INDEX IF NOT EXISTS idx_content_items_series ON content_items(series_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status_priority ON tasks(status, priority, created_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_content_item ON tasks(content_item_id);
        CREATE INDEX IF NOT EXISTS idx_transcript_segments_content ON transcript_segments(content_item_id, position);
        """
    )
    _create_optional_fts(connection)


def _create_optional_fts(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS content_search
            USING fts5(content_item_id UNINDEXED, title, summary, transcript)
            """
        )
    except sqlite3.OperationalError:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS content_search (
                content_item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                transcript TEXT NOT NULL DEFAULT ''
            )
            """
        )


def _migration_002_library_tree(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_folder_id TEXT REFERENCES library_folders(id) ON DELETE CASCADE,
            sort_order REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_library_folders_parent
        ON library_folders(parent_folder_id, sort_order, name);
        """
    )
    _add_column_if_missing(connection, "content_items", "library_folder_id", "TEXT REFERENCES library_folders(id) ON DELETE SET NULL")
    _add_column_if_missing(connection, "content_items", "sort_order", "REAL NOT NULL DEFAULT 0")
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_content_items_library_folder
        ON content_items(library_folder_id, sort_order, created_at)
        """
    )

def _migration_003_wechat_subscriptions(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_accounts (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT '',
            keychain_ref TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'active',
            last_validated_at TEXT,
            reauth_required_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wechat_subscriptions (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES wechat_accounts(id) ON DELETE CASCADE,
            fakeid TEXT NOT NULL,
            biz TEXT,
            mp_name TEXT NOT NULL,
            avatar_url TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            auto_process INTEGER NOT NULL DEFAULT 0,
            sync_interval_minutes INTEGER NOT NULL DEFAULT 1440,
            last_sync_at TEXT,
            next_sync_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, fakeid)
        );

        CREATE TABLE IF NOT EXISTS wechat_subscription_items (
            id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL REFERENCES wechat_subscriptions(id) ON DELETE CASCADE,
            remote_article_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE SET NULL,
            title TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            discovered_at TEXT NOT NULL,
            UNIQUE(subscription_id, remote_article_id)
        );

        CREATE TABLE IF NOT EXISTS wechat_sync_runs (
            id TEXT PRIMARY KEY,
            subscription_id TEXT NOT NULL REFERENCES wechat_subscriptions(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            found_count INTEGER NOT NULL DEFAULT 0,
            imported_count INTEGER NOT NULL DEFAULT 0,
            error_category TEXT,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_wechat_subscriptions_due
        ON wechat_subscriptions(enabled, next_sync_at);
        CREATE INDEX IF NOT EXISTS idx_wechat_subscription_items_subscription
        ON wechat_subscription_items(subscription_id, published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_wechat_sync_runs_subscription
        ON wechat_sync_runs(subscription_id, started_at DESC);
        """
    )


def _migration_004_show_wechat_subscription_items_in_library(connection: sqlite3.Connection) -> None:
    """Move legacy subscription imports out of the retired inbox-only state."""
    connection.execute(
        """
        UPDATE content_items
        SET status = 'to_read', updated_at = ?
        WHERE status = 'inbox'
          AND EXISTS (
              SELECT 1
              FROM wechat_subscription_items item
              JOIN wechat_subscriptions subscription ON subscription.id = item.subscription_id
              WHERE item.content_item_id = content_items.id
                AND subscription.auto_process = 0
          )
          AND NOT EXISTS (
              SELECT 1
              FROM wechat_subscription_items item
              JOIN wechat_subscriptions subscription ON subscription.id = item.subscription_id
              WHERE item.content_item_id = content_items.id
                AND subscription.auto_process = 1
          )
        """,
        (utc_now_iso(),),
    )


def _migration_005_qa_history_indexes(connection: sqlite3.Connection) -> None:
    """Support loading a content item's saved manual AI conversation efficiently."""
    connection.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_threads_content_scope
        ON qa_threads(scope, content_item_id)
        WHERE scope = 'content' AND content_item_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS idx_qa_messages_thread_created
        ON qa_messages(thread_id, created_at);
        """
    )


def _migration_006_wechat_sync_backoff(connection: sqlite3.Connection) -> None:
    """Track consecutive subscription failures so retries can back off safely."""
    _add_column_if_missing(
        connection,
        "wechat_subscriptions",
        "consecutive_failure_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(connection, "wechat_subscriptions", "last_error_category", "TEXT")


def _migration_007_content_analyses(connection: sqlite3.Connection) -> None:
    """Persist independent, repeatable manual AI analyses for content items."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS content_analyses (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            prompt_template_id TEXT REFERENCES prompt_templates(id) ON DELETE SET NULL,
            prompt_template_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            model TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_content_analyses_content_created
        ON content_analyses(content_item_id, created_at DESC);
        """
    )


def _migration_008_remove_content_tags(connection: sqlite3.Connection) -> None:
    """Remove the retired manual tag feature and its existing data."""
    connection.execute("DROP TABLE IF EXISTS content_tags")
    connection.execute("DROP TABLE IF EXISTS tags")


def _migration_009_remove_retired_external_wechat_accounts(connection: sqlite3.Connection) -> None:
    """Retire the Docker-backed source while retaining already imported content."""
    connection.execute(
        "DELETE FROM wechat_accounts WHERE keychain_ref = 'wechat-collector:external'"
    )


def _migration_010_wechat_content_filter_rules(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS wechat_content_filter_rules (
            id TEXT PRIMARY KEY,
            subscription_id TEXT REFERENCES wechat_subscriptions(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            selectors_json TEXT NOT NULL DEFAULT '[]',
            text_patterns_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_filter_rules_subscription
        ON wechat_content_filter_rules(subscription_id, enabled, priority DESC);
    """)


def _migration_011_wechat_groups_and_reports(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS wechat_subscription_groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            sort_order REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS wechat_reports (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL CHECK(report_type IN ('daily', 'weekly')),
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_reports_group_period ON wechat_reports(group_id, period_start DESC);
    """)
    _add_column_if_missing(connection, "wechat_subscriptions", "group_id", "TEXT REFERENCES wechat_subscription_groups(id) ON DELETE SET NULL")


def _migration_012_wechat_report_prompts(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS wechat_report_prompts (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL CHECK(report_type IN ('daily', 'weekly')),
            template TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(group_id, report_type)
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_report_prompts_group
        ON wechat_report_prompts(group_id, report_type);
    """)


def _migration_013_wechat_subscription_group_memberships(connection: sqlite3.Connection) -> None:
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS wechat_subscription_group_memberships (
            subscription_id TEXT NOT NULL REFERENCES wechat_subscriptions(id) ON DELETE CASCADE,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY(subscription_id, group_id)
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_group_memberships_group
        ON wechat_subscription_group_memberships(group_id, subscription_id);
    """)
    connection.execute(
        """INSERT OR IGNORE INTO wechat_subscription_group_memberships
           (subscription_id, group_id, created_at)
           SELECT id, group_id, updated_at FROM wechat_subscriptions
           WHERE group_id IS NOT NULL AND group_id != ''"""
    )


def _migration_014_wechat_subscription_descriptions(connection: sqlite3.Connection) -> None:
    """Keep the public account introduction shown at subscription time."""
    _add_column_if_missing(
        connection,
        "wechat_subscriptions",
        "mp_description",
        "TEXT NOT NULL DEFAULT ''",
    )


def _migration_015_library_trash(connection: sqlite3.Connection) -> None:
    """Keep deleted library nodes restorable until explicitly removed."""
    _add_column_if_missing(connection, "library_folders", "deleted_at", "TEXT")
    _add_column_if_missing(connection, "library_folders", "trash_batch_id", "TEXT")
    _add_column_if_missing(connection, "content_items", "deleted_at", "TEXT")
    _add_column_if_missing(connection, "content_items", "trash_batch_id", "TEXT")
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_library_folders_deleted
        ON library_folders(deleted_at, trash_batch_id);
        CREATE INDEX IF NOT EXISTS idx_content_items_deleted
        ON content_items(deleted_at, trash_batch_id);
        """
    )


def _migration_016_wechat_report_source_digests(connection: sqlite3.Connection) -> None:
    """Cache report-oriented fact cards for unchanged WeChat articles."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_report_source_digests (
            content_item_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            model TEXT NOT NULL,
            digest_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_report_digests_hash
        ON wechat_report_source_digests(source_hash, prompt_version);
        """
    )


def _migration_017_content_source_metadata(connection: sqlite3.Connection) -> None:
    """Persist publication and source labels for campus and future article providers."""
    _add_column_if_missing(connection, "content_items", "published_at", "TEXT")
    _add_column_if_missing(connection, "content_items", "source_name", "TEXT")
    _add_column_if_missing(connection, "content_items", "source_section", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_items_published ON content_items(published_at DESC)"
    )


def _migration_018_wechat_report_source_coverage(connection: sqlite3.Connection) -> None:
    """Persist why each analyzed article was cited or excluded from a report."""
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "source_coverage_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )


def _migration_019_miniprogram_forum_capture(connection: sqlite3.Connection) -> None:
    """Persist visual mini-program capture evidence separately from reports.

    A forum post is also promoted to ``content_items`` so it can participate in
    the existing library and search flows.  The capture-specific tables retain
    the raw, replayable evidence that does not fit the generic content model.
    """
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS miniprogram_capture_runs (
            id TEXT PRIMARY KEY,
            source_key TEXT NOT NULL,
            status TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'incremental',
            window_pattern TEXT NOT NULL DEFAULT '猹话会',
            current_stage TEXT NOT NULL DEFAULT 'preparing',
            posts_seen INTEGER NOT NULL DEFAULT 0,
            posts_created INTEGER NOT NULL DEFAULT 0,
            comments_captured INTEGER NOT NULL DEFAULT 0,
            frames_captured INTEGER NOT NULL DEFAULT 0,
            options_json TEXT NOT NULL DEFAULT '{}',
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            last_error TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS forum_posts (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL UNIQUE REFERENCES content_items(id) ON DELETE CASCADE,
            source_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            author_label TEXT NOT NULL DEFAULT '',
            display_time TEXT NOT NULL DEFAULT '',
            estimated_from TEXT,
            estimated_to TEXT,
            body_text TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            category TEXT NOT NULL DEFAULT '',
            collect_count INTEGER,
            comment_count INTEGER,
            like_count INTEGER,
            capture_complete INTEGER NOT NULL DEFAULT 0,
            detail_frame_path TEXT NOT NULL DEFAULT '',
            raw_json TEXT NOT NULL DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE(source_key, fingerprint)
        );

        CREATE TABLE IF NOT EXISTS forum_comments (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
            fingerprint TEXT NOT NULL,
            author_label TEXT NOT NULL DEFAULT '',
            display_time TEXT NOT NULL DEFAULT '',
            body_text TEXT NOT NULL DEFAULT '',
            like_count INTEGER,
            images_json TEXT NOT NULL DEFAULT '[]',
            raw_json TEXT NOT NULL DEFAULT '{}',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            UNIQUE(post_id, fingerprint)
        );

        CREATE TABLE IF NOT EXISTS forum_metric_snapshots (
            id TEXT PRIMARY KEY,
            post_id TEXT NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
            collect_count INTEGER,
            comment_count INTEGER,
            like_count INTEGER,
            captured_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS miniprogram_capture_frames (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES miniprogram_capture_runs(id) ON DELETE CASCADE,
            post_id TEXT REFERENCES forum_posts(id) ON DELETE SET NULL,
            frame_kind TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 0,
            image_path TEXT NOT NULL,
            image_hash TEXT NOT NULL DEFAULT '',
            ocr_json TEXT NOT NULL DEFAULT '{}',
            captured_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_miniprogram_capture_runs_started
        ON miniprogram_capture_runs(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_forum_posts_source_seen
        ON forum_posts(source_key, last_seen_at DESC);
        CREATE INDEX IF NOT EXISTS idx_forum_comments_post_seen
        ON forum_comments(post_id, first_seen_at);
        CREATE INDEX IF NOT EXISTS idx_forum_metric_snapshots_post
        ON forum_metric_snapshots(post_id, captured_at DESC);
        CREATE INDEX IF NOT EXISTS idx_miniprogram_frames_run_sequence
        ON miniprogram_capture_frames(run_id, sequence);
        """
    )


def _migration_020_campus_digest_generation(connection: sqlite3.Connection) -> None:
    """Persist campus fact cards, conservative event clusters and schedule state."""
    _add_column_if_missing(
        connection,
        "wechat_subscription_groups",
        "include_campus_sources",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(connection, "wechat_reports", "window_start", "TEXT")
    _add_column_if_missing(connection, "wechat_reports", "window_end", "TEXT")
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "generation_trigger",
        "TEXT NOT NULL DEFAULT 'manual'",
    )
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "generation_mode",
        "TEXT NOT NULL DEFAULT 'legacy'",
    )
    _add_column_if_missing(
        connection,
        "wechat_reports",
        "cover_status",
        "TEXT NOT NULL DEFAULT 'none'",
    )
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS campus_report_facts (
            content_item_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            model TEXT NOT NULL,
            fact_json TEXT NOT NULL,
            filter_status TEXT NOT NULL DEFAULT 'include',
            filter_reason TEXT NOT NULL DEFAULT '',
            embedding_model TEXT NOT NULL DEFAULT '',
            embedding_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campus_event_clusters (
            id TEXT PRIMARY KEY,
            canonical_title TEXT NOT NULL DEFAULT '',
            category TEXT NOT NULL DEFAULT '其他动态',
            signature_json TEXT NOT NULL DEFAULT '{}',
            brief_hash TEXT NOT NULL DEFAULT '',
            brief_model TEXT NOT NULL DEFAULT '',
            brief_json TEXT NOT NULL DEFAULT '{}',
            first_published_at TEXT,
            last_published_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campus_event_members (
            cluster_id TEXT NOT NULL REFERENCES campus_event_clusters(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL UNIQUE REFERENCES content_items(id) ON DELETE CASCADE,
            relation_type TEXT NOT NULL DEFAULT 'same_event',
            event_stage TEXT NOT NULL DEFAULT 'unknown',
            match_method TEXT NOT NULL DEFAULT 'new_cluster',
            confidence REAL NOT NULL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(cluster_id, content_item_id)
        );

        CREATE TABLE IF NOT EXISTS campus_digest_scheduler_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_campus_report_facts_updated
        ON campus_report_facts(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_campus_event_clusters_updated
        ON campus_event_clusters(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_campus_event_members_cluster
        ON campus_event_members(cluster_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_wechat_reports_schedule_window
        ON wechat_reports(group_id, report_type, window_end, generation_trigger);
        """
    )


def _migration_021_version_wechat_report_prompts(connection: sqlite3.Connection) -> None:
    """Track default prompt upgrades without overwriting user-authored templates."""
    _add_column_if_missing(
        connection,
        "wechat_report_prompts",
        "template_version",
        "TEXT NOT NULL DEFAULT ''",
    )


def _migration_022_link_miniprogram_run_documents(connection: sqlite3.Connection) -> None:
    """Expose each visual-capture run as a first-class library document."""
    _add_column_if_missing(
        connection,
        "miniprogram_capture_runs",
        "content_item_id",
        "TEXT REFERENCES content_items(id) ON DELETE SET NULL",
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_miniprogram_capture_runs_content
        ON miniprogram_capture_runs(content_item_id)
        """
    )


def _migration_023_support_range_reports(connection: sqlite3.Connection) -> None:
    """Allow manually selected time ranges without classifying them as daily reports."""
    connection.executescript(
        """
        CREATE TABLE wechat_reports_v23 (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL CHECK(report_type IN ('daily', 'weekly', 'range')),
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            source_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            source_coverage_json TEXT NOT NULL DEFAULT '[]',
            window_start TEXT,
            window_end TEXT,
            generation_trigger TEXT NOT NULL DEFAULT 'manual',
            generation_mode TEXT NOT NULL DEFAULT 'legacy',
            cover_status TEXT NOT NULL DEFAULT 'none'
        );

        INSERT INTO wechat_reports_v23 (
            id, group_id, content_item_id, report_type, period_start, period_end,
            source_count, created_at, source_coverage_json, window_start, window_end,
            generation_trigger, generation_mode, cover_status
        )
        SELECT
            id, group_id, content_item_id, report_type, period_start, period_end,
            source_count, created_at, source_coverage_json, window_start, window_end,
            generation_trigger, generation_mode, cover_status
        FROM wechat_reports;

        DROP TABLE wechat_reports;
        ALTER TABLE wechat_reports_v23 RENAME TO wechat_reports;

        CREATE INDEX idx_wechat_reports_group_period
        ON wechat_reports(group_id, period_start DESC);
        CREATE INDEX idx_wechat_reports_schedule_window
        ON wechat_reports(group_id, report_type, window_end, generation_trigger);
        """
    )


def _migration_024_prompt_workspace(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prompt_folders (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            task_type TEXT NOT NULL,
            parent_folder_id TEXT REFERENCES prompt_folders(id) ON DELETE CASCADE,
            sort_order REAL NOT NULL DEFAULT 0,
            deleted_at TEXT,
            trash_batch_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_prompt_folders_tree
        ON prompt_folders(task_type, parent_folder_id, deleted_at, sort_order);
        CREATE INDEX IF NOT EXISTS idx_prompt_folders_trash
        ON prompt_folders(deleted_at, trash_batch_id);
        """
    )
    _add_column_if_missing(connection, "prompt_templates", "folder_id", "TEXT REFERENCES prompt_folders(id) ON DELETE SET NULL")
    _add_column_if_missing(connection, "prompt_templates", "sort_order", "REAL NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "prompt_templates", "deleted_at", "TEXT")
    _add_column_if_missing(connection, "prompt_templates", "trash_batch_id", "TEXT")
    _add_column_if_missing(connection, "wechat_report_prompts", "display_name", "TEXT")
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_prompt_templates_tree
        ON prompt_templates(task_type, folder_id, deleted_at, sort_order);
        CREATE INDEX IF NOT EXISTS idx_prompt_templates_trash
        ON prompt_templates(deleted_at, trash_batch_id);
        """
    )


def _migration_025_ai_call_summary_indexes(connection: sqlite3.Connection) -> None:
    """Keep live task and daily Token summaries efficient as call history grows."""
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_ai_calls_task
        ON ai_calls(task_id);
        CREATE INDEX IF NOT EXISTS idx_ai_calls_success_created_type
        ON ai_calls(created_at, call_type) WHERE error IS NULL;
        """
    )


def _migration_026_content_documents(connection: sqlite3.Connection) -> None:
    """Index Markdown-first source documents without duplicating their text in SQLite."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS content_documents (
            content_item_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            markdown_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_content_documents_path ON content_documents(markdown_path)")


def _migration_027_prompt_default_keys(connection: sqlite3.Connection) -> None:
    """Keep a built-in prompt's identity stable when its display name changes."""
    _add_column_if_missing(connection, "prompt_templates", "default_key", "TEXT")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_templates_default_key
        ON prompt_templates(default_key)
        WHERE default_key IS NOT NULL AND deleted_at IS NULL
        """
    )


def _migration_028_ai_call_cache_usage(connection: sqlite3.Connection) -> None:
    """Persist provider-reported prompt cache usage for per-content cost visibility."""
    _add_column_if_missing(connection, "ai_calls", "prompt_cache_hit_tokens", "INTEGER")
    _add_column_if_missing(connection, "ai_calls", "prompt_cache_miss_tokens", "INTEGER")


def _migration_029_group_report_prompt_type(connection: sqlite3.Connection) -> None:
    """Allow one reusable interval-report prompt per source group."""
    connection.executescript(
        """
        CREATE TABLE wechat_report_prompts_v29 (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            report_type TEXT NOT NULL CHECK(report_type IN ('daily', 'weekly', 'range')),
            template TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            template_version TEXT NOT NULL DEFAULT '',
            display_name TEXT,
            UNIQUE(group_id, report_type)
        );

        INSERT INTO wechat_report_prompts_v29 (
            id, group_id, report_type, template, created_at, updated_at,
            template_version, display_name
        )
        SELECT id, group_id, report_type, template, created_at, updated_at,
               COALESCE(template_version, ''), display_name
        FROM wechat_report_prompts;

        DROP TABLE wechat_report_prompts;
        ALTER TABLE wechat_report_prompts_v29 RENAME TO wechat_report_prompts;

        CREATE INDEX idx_wechat_report_prompts_group
        ON wechat_report_prompts(group_id, report_type);
        """
    )


def _migration_030_group_report_source_summaries(connection: sqlite3.Connection) -> None:
    """Cache short source summaries used only for report section planning."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS group_report_source_summaries (
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            model TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (content_item_id, prompt_hash, model)
        );
        CREATE INDEX IF NOT EXISTS idx_group_report_source_summary_hash
        ON group_report_source_summaries(source_hash, prompt_hash, model);
        """
    )
