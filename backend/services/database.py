from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

from config import ensure_private_data_directory, ensure_private_data_file, settings


SCHEMA_VERSION = 92
_DATABASE_INITIALIZE_LOCK = RLock()
_INITIALIZED_DATABASES: set[Path] = set()
DATABASE_BUSY_TIMEOUT_MS = 30_000
_WAL_ENABLE_RETRY_INTERVAL_SECONDS = 0.1


class ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path() -> Path:
    return settings.data_dir / "app.db"


def connect(
    path: Path | None = None,
    *,
    busy_timeout_ms: int = DATABASE_BUSY_TIMEOUT_MS,
) -> sqlite3.Connection:
    db_path = path or database_path()
    timeout_ms = max(0, int(busy_timeout_ms))
    ensure_private_data_directory(db_path.parent)
    # Pre-create with a private mode so a new database is never briefly
    # world-readable before SQLite opens it.
    ensure_private_data_file(db_path, create=True)
    connection = sqlite3.connect(
        db_path,
        timeout=timeout_ms / 1000,
        factory=ManagedConnection,
    )
    try:
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        _ensure_wal_mode(connection, timeout_ms=timeout_ms)
        connection.execute("PRAGMA synchronous = NORMAL")
        ensure_private_data_file(db_path)
        ensure_private_data_file(Path(f"{db_path}-wal"))
        ensure_private_data_file(Path(f"{db_path}-shm"))
    except Exception:
        connection.close()
        raise
    return connection


def _ensure_wal_mode(
    connection: sqlite3.Connection,
    *,
    timeout_ms: int = DATABASE_BUSY_TIMEOUT_MS,
) -> None:
    """Require WAL instead of silently serving concurrent work in DELETE mode."""
    current = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    if current in {"wal", "memory"}:
        return
    deadline = time.monotonic() + (timeout_ms / 1000)
    while True:
        try:
            current = str(
                connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            ).lower()
            if current == "wal":
                return
        except sqlite3.OperationalError as exc:
            if not is_database_busy_error(exc):
                raise
        if time.monotonic() >= deadline:
            raise sqlite3.OperationalError(
                "database remained busy while enabling WAL mode"
            )
        time.sleep(_WAL_ENABLE_RETRY_INTERVAL_SECONDS)


def is_database_busy_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def initialize_database(path: Path | None = None) -> Path:
    db_path = path or database_path()
    database_key = db_path.expanduser().resolve()
    with _DATABASE_INITIALIZE_LOCK:
        if database_key in _INITIALIZED_DATABASES and db_path.exists():
            return db_path
        with connect(db_path) as connection:
            _ensure_migrations_table(connection)
            current_version = _current_schema_version(connection)
            migrated = False
            for version, migration in _MIGRATIONS:
                if version > current_version:
                    migration(connection)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, utc_now_iso()),
                    )
                    migrated = True
            # Default prompts are part of initial schema setup.  Re-running
            # their maintenance writes on every ordinary read path creates
            # needless writer contention with source ingestion (especially a
            # first batch of WeChat articles).  Prompt changes must instead be
            # introduced with a migration, which also preserves user edits.
            if migrated:
                from services.prompt_templates import seed_default_prompt_templates

                seed_default_prompt_templates(connection)
            # During active development, built-in prompt source lives in code
            # as well as the editable workspace.  A code change is propagated
            # once to SQLite and its Markdown mirror; unchanged source never
            # overwrites an edit made from the UI or the Markdown file.
            from services.prompt_templates import sync_builtin_prompt_definitions
            from services.wechat_reports import sync_builtin_report_prompt_definitions

            sync_builtin_prompt_definitions(connection)
            sync_builtin_report_prompt_definitions(connection)
            connection.commit()
        _INITIALIZED_DATABASES.add(database_key)
    return db_path


def ensure_database_initialized(path: Path | None = None) -> Path:
    """Initialize once for hot request/background paths without rerunning maintenance."""
    db_path = path or database_path()
    database_key = db_path.expanduser().resolve()
    with _DATABASE_INITIALIZE_LOCK:
        if database_key in _INITIALIZED_DATABASES and db_path.exists():
            return db_path
        return initialize_database(db_path)


def _ensure_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


def _current_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    return int(row["version"] or 0)


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


def _migration_031_disable_auto_article_analysis(connection: sqlite3.Connection) -> None:
    """Ingestion prepares OCR locally; AI analysis must remain opt-in."""
    connection.execute("UPDATE wechat_subscriptions SET auto_process=0 WHERE auto_process!=0")


def _migration_032_ocr_call_history(connection: sqlite3.Connection) -> None:
    """Track hosted OCR requests separately from token-bearing LLM calls."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS ocr_calls (
            id TEXT PRIMARY KEY,
            content_item_id TEXT REFERENCES content_items(id) ON DELETE SET NULL,
            image_url TEXT NOT NULL,
            image_bytes INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL,
            status TEXT NOT NULL,
            cloud_submitted INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            elapsed_seconds REAL NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ocr_calls_created_at
        ON ocr_calls(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ocr_calls_content_created_at
        ON ocr_calls(content_item_id, created_at DESC);
        """
    )


def _migration_033_qa_conversation_archives(connection: sqlite3.Connection) -> None:
    """Let one content item retain archived Q&A conversations beside one active one."""
    _add_column_if_missing(connection, "qa_threads", "status", "TEXT NOT NULL DEFAULT 'active'")
    connection.execute("UPDATE qa_threads SET status = 'active' WHERE status IS NULL OR status = ''")
    connection.execute("DROP INDEX IF EXISTS idx_qa_threads_content_scope")
    connection.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_threads_active_content_scope
        ON qa_threads(scope, content_item_id)
        WHERE scope = 'content' AND content_item_id IS NOT NULL AND status = 'active';

        CREATE INDEX IF NOT EXISTS idx_qa_threads_content_status_updated
        ON qa_threads(content_item_id, status, updated_at DESC);
        """
    )


def _migration_034_library_source_folder_bindings(connection: sqlite3.Connection) -> None:
    """Keep automatic sources attached to stable library folder IDs.

    Names and tree positions are user-facing presentation data.  They must not
    be used as the identity of a subscribed source when later content arrives.
    """
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS library_source_folder_bindings (
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            folder_id TEXT REFERENCES library_folders(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(source_type, source_key)
        );
        CREATE INDEX IF NOT EXISTS idx_library_source_folder_bindings_folder
        ON library_source_folder_bindings(folder_id);
        """
    )


def _migration_035_creator_sources(connection: sqlite3.Connection) -> None:
    """Persist creator sources without coupling them to a transient task batch."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS creator_sources (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            source_url TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            creator_key TEXT NOT NULL,
            creator_name TEXT NOT NULL DEFAULT '',
            library_folder_id TEXT REFERENCES library_folders(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider, source_url)
        );
        CREATE INDEX IF NOT EXISTS idx_creator_sources_provider_creator
        ON creator_sources(provider, creator_key);
        """
    )


def _migration_036_knowledge_retrieval(connection: sqlite3.Connection) -> None:
    """Store traceable retrieval chunks outside the user-facing library tree."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE,
            description TEXT NOT NULL DEFAULT '',
            sort_order REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(name)
        );
        CREATE TABLE IF NOT EXISTS knowledge_group_memberships (
            group_id TEXT NOT NULL REFERENCES knowledge_groups(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            membership_source TEXT NOT NULL DEFAULT 'manual',
            confidence REAL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(group_id, content_item_id)
        );
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL,
            chunk_type TEXT NOT NULL DEFAULT 'section',
            heading_path TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(content_item_id, ordinal, source_hash)
        );
        CREATE TABLE IF NOT EXISTS knowledge_chunk_embeddings (
            chunk_id TEXT PRIMARY KEY REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
            embedding_model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            vector_json TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunk_search
        USING fts5(chunk_id UNINDEXED, searchable, tokenize='unicode61');
        CREATE INDEX IF NOT EXISTS idx_knowledge_group_memberships_content
        ON knowledge_group_memberships(content_item_id, group_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_content
        ON knowledge_chunks(content_item_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_model
        ON knowledge_chunk_embeddings(embedding_model, dimensions);
        """
    )


def _migration_037_creator_subscriptions(connection: sqlite3.Connection) -> None:
    """Turn creator imports into durable, incrementally synced subscriptions."""
    _add_column_if_missing(connection, "creator_sources", "source_identity", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "creator_sources", "enabled", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(connection, "creator_sources", "auto_process", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(connection, "creator_sources", "sync_interval_minutes", "INTEGER NOT NULL DEFAULT 360")
    _add_column_if_missing(connection, "creator_sources", "sync_limit", "INTEGER NOT NULL DEFAULT 100")
    _add_column_if_missing(connection, "creator_sources", "last_sync_at", "TEXT")
    _add_column_if_missing(connection, "creator_sources", "next_sync_at", "TEXT")
    _add_column_if_missing(connection, "creator_sources", "last_seen_published_at", "TEXT")
    _add_column_if_missing(connection, "creator_sources", "last_error", "TEXT")
    _add_column_if_missing(connection, "creator_sources", "last_discovered_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "creator_sources", "last_created_count", "INTEGER NOT NULL DEFAULT 0")
    connection.execute(
        """UPDATE creator_sources
           SET source_identity = provider || ':' || source_kind || ':' || creator_key
           WHERE source_identity = ''"""
    )
    # Source rows do not own user content. Keeping the most recently updated
    # row is safe, and prevents legacy tracking-query variants from creating
    # duplicate subscriptions for the same creator.
    connection.execute(
        """DELETE FROM creator_sources
           WHERE id NOT IN (
             SELECT id FROM (
               SELECT id,
                      ROW_NUMBER() OVER (
                        PARTITION BY source_identity
                        ORDER BY updated_at DESC, id DESC
                      ) AS row_number
               FROM creator_sources
             )
             WHERE row_number = 1
           )"""
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_creator_sources_identity ON creator_sources(source_identity)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_creator_sources_due ON creator_sources(enabled, next_sync_at)"
    )


def _migration_051_wechat_publishing(connection: sqlite3.Connection) -> None:
    """Persist a separate official-account publishing identity and draft history.

    Collection sessions are deliberately not reusable for publishing: they are
    public-platform browser sessions, while the official draft API requires an
    AppID/AppSecret access token.  Secrets stay in Keychain; SQLite stores only
    the Keychain reference and non-sensitive publishing metadata.
    """
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_publishing_accounts (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            display_name TEXT NOT NULL DEFAULT '',
            app_id TEXT NOT NULL DEFAULT '',
            keychain_ref TEXT NOT NULL DEFAULT 'wechat-publishing:default',
            status TEXT NOT NULL DEFAULT 'unconfigured',
            last_verified_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wechat_publications (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            account_id INTEGER NOT NULL DEFAULT 1 REFERENCES wechat_publishing_accounts(id) ON DELETE CASCADE,
            report_title TEXT NOT NULL DEFAULT '',
            digest TEXT NOT NULL DEFAULT '',
            author TEXT NOT NULL DEFAULT '',
            source_markdown_hash TEXT NOT NULL DEFAULT '',
            draft_media_id TEXT,
            thumb_media_id TEXT,
            status TEXT NOT NULL DEFAULT 'draft_created',
            error_message TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_publications_content
        ON wechat_publications(content_item_id, created_at DESC);
        """
    )
def _migration_038_creator_processing_policies(connection: sqlite3.Connection) -> None:
    """Persist per-creator processing policies separately from scan breadth."""
    _add_column_if_missing(connection, "creator_sources", "processing_mode", "TEXT NOT NULL DEFAULT 'full'")
    _add_column_if_missing(connection, "creator_sources", "queue_limit", "INTEGER NOT NULL DEFAULT 10")
    connection.execute(
        """UPDATE creator_sources
           SET processing_mode = CASE WHEN auto_process = 0 THEN 'metadata' ELSE 'full' END
           WHERE processing_mode IS NULL OR processing_mode = ''"""
    )
    connection.execute(
        """UPDATE creator_sources
           SET queue_limit = 10
           WHERE queue_limit IS NULL OR queue_limit < 1"""
    )


def _migration_039_knowledge_chunk_curation(connection: sqlite3.Connection) -> None:
    """Keep a user-curated knowledge copy without altering source documents."""
    _add_column_if_missing(connection, "knowledge_chunks", "original_text", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "knowledge_chunks", "status", "TEXT NOT NULL DEFAULT 'active'")
    _add_column_if_missing(connection, "knowledge_chunks", "excluded_reason", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "knowledge_chunks", "excluded_at", "TEXT")
    _add_column_if_missing(connection, "knowledge_chunks", "edited_at", "TEXT")
    connection.execute("UPDATE knowledge_chunks SET original_text=text WHERE original_text='' ")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_status ON knowledge_chunks(status, content_item_id, ordinal)"
    )


def _migration_040_creator_sync_health(connection: sqlite3.Connection) -> None:
    """Track retry state and a compact history for creator subscriptions."""
    _add_column_if_missing(connection, "creator_sources", "consecutive_failure_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "creator_sources", "last_error_category", "TEXT")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS creator_sync_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES creator_sources(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            error_category TEXT,
            message TEXT NOT NULL DEFAULT '',
            discovered_count INTEGER NOT NULL DEFAULT 0,
            created_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_creator_sync_runs_source_time
        ON creator_sync_runs(source_id, created_at DESC);
        """
    )


def _migration_041_knowledge_conversation_archives(connection: sqlite3.Connection) -> None:
    """Persist cross-library Q&A separately from source-document Q&A."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            scope_json TEXT NOT NULL DEFAULT '{}',
            markdown_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS knowledge_conversation_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES knowledge_conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL DEFAULT '',
            citations_json TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_conversations_updated
        ON knowledge_conversations(deleted_at, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_conversation_messages_order
        ON knowledge_conversation_messages(conversation_id, created_at, id);
        """
    )


def _migration_042_rss_subscriptions(connection: sqlite3.Connection) -> None:
    """Persist RSS sources, their incremental state, and item provenance."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS rss_sources (
            id TEXT PRIMARY KEY,
            feed_url TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            site_url TEXT NOT NULL DEFAULT '',
            library_folder_id TEXT REFERENCES library_folders(id) ON DELETE SET NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            sync_interval_minutes INTEGER NOT NULL DEFAULT 180,
            sync_limit INTEGER NOT NULL DEFAULT 20,
            last_sync_at TEXT,
            next_sync_at TEXT,
            last_error TEXT,
            consecutive_failure_count INTEGER NOT NULL DEFAULT 0,
            last_discovered_count INTEGER NOT NULL DEFAULT 0,
            last_created_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rss_sources_due
        ON rss_sources(enabled, next_sync_at);

        CREATE TABLE IF NOT EXISTS rss_source_items (
            source_id TEXT NOT NULL REFERENCES rss_sources(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL UNIQUE REFERENCES content_items(id) ON DELETE CASCADE,
            entry_identity TEXT NOT NULL,
            source_summary TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_id, entry_identity)
        );
        CREATE INDEX IF NOT EXISTS idx_rss_source_items_source
        ON rss_source_items(source_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS rss_sync_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES rss_sources(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            discovered_count INTEGER NOT NULL DEFAULT 0,
            created_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rss_sync_runs_source_time
        ON rss_sync_runs(source_id, created_at DESC);
        """
    )


def _migration_043_rss_source_groups(connection: sqlite3.Connection) -> None:
    """Attach RSS sources to the existing report-group system."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS rss_source_group_memberships (
            source_id TEXT NOT NULL REFERENCES rss_sources(id) ON DELETE CASCADE,
            group_id TEXT NOT NULL REFERENCES wechat_subscription_groups(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_id, group_id)
        );
        CREATE INDEX IF NOT EXISTS idx_rss_group_memberships_group
        ON rss_source_group_memberships(group_id, source_id);
        """
    )


def _migration_044_rss_auto_analysis(connection: sqlite3.Connection) -> None:
    """Allow each RSS subscription to opt into summaries for new entries."""
    columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(rss_sources)").fetchall()}
    if "auto_analyze" not in columns:
        connection.execute("ALTER TABLE rss_sources ADD COLUMN auto_analyze INTEGER NOT NULL DEFAULT 0")


def _migration_045_creator_work_metadata(connection: sqlite3.Connection) -> None:
    """Keep creator/platform data that does not fit the generic content item."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS creator_work_metadata (
            content_item_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            creator_key TEXT NOT NULL,
            creator_name TEXT NOT NULL DEFAULT '',
            creator_avatar_url TEXT NOT NULL DEFAULT '',
            creator_description TEXT NOT NULL DEFAULT '',
            collection_id TEXT NOT NULL DEFAULT '',
            collection_name TEXT NOT NULL DEFAULT '',
            work_description TEXT NOT NULL DEFAULT '',
            author_name TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            stats_json TEXT NOT NULL DEFAULT '{}',
            captured_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_creator_work_metadata_creator
        ON creator_work_metadata(provider, creator_key);
        """
    )


def _migration_046_hide_internal_forum_posts(connection: sqlite3.Connection) -> None:
    """Keep per-post visual capture rows out of the user-facing library.

    A mini-program capture run is the durable document users read.  Individual
    posts remain in SQLite as dedupe and evidence records, but should not each
    become a parallel library document.
    """
    _add_column_if_missing(
        connection,
        "content_items",
        "library_visible",
        "INTEGER NOT NULL DEFAULT 1",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_content_items_library_visible ON content_items(library_visible, deleted_at)"
    )


def _migration_047_personal_favorites(connection: sqlite3.Connection) -> None:
    """Track a user's own Douyin and Bilibili favorites independently of creators."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS favorite_sources (
            id TEXT PRIMARY KEY,
            provider TEXT NOT NULL CHECK(provider IN ('douyin', 'bilibili', 'xiaohongshu')),
            source_url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            library_folder_id TEXT REFERENCES library_folders(id) ON DELETE SET NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            auto_analyze INTEGER NOT NULL DEFAULT 0,
            sync_interval_minutes INTEGER NOT NULL DEFAULT 360,
            sync_limit INTEGER NOT NULL DEFAULT 5,
            last_sync_at TEXT,
            next_sync_at TEXT,
            last_error TEXT,
            consecutive_failure_count INTEGER NOT NULL DEFAULT 0,
            last_discovered_count INTEGER NOT NULL DEFAULT 0,
            last_created_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(provider, source_url)
        );
        CREATE INDEX IF NOT EXISTS idx_favorite_sources_due
        ON favorite_sources(enabled, next_sync_at);

        CREATE TABLE IF NOT EXISTS favorite_source_items (
            source_id TEXT NOT NULL REFERENCES favorite_sources(id) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            remote_video_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_id, remote_video_id)
        );
        CREATE INDEX IF NOT EXISTS idx_favorite_source_items_source
        ON favorite_source_items(source_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS favorite_sync_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES favorite_sources(id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            discovered_count INTEGER NOT NULL DEFAULT 0,
            created_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_favorite_sync_runs_source_time
        ON favorite_sync_runs(source_id, created_at DESC);
        """
    )


def _migration_048_source_read_limits(connection: sqlite3.Connection) -> None:
    """Persist the newest-window size for every WeChat subscription."""
    _add_column_if_missing(
        connection,
        "wechat_subscriptions",
        "sync_limit",
        "INTEGER NOT NULL DEFAULT 10",
    )


def _migration_050_openclaw_conversation_bindings(connection: sqlite3.Connection) -> None:
    """Keep OpenClaw conversation/task state local without retaining chat data by default."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS openclaw_conversations (
            session_hash TEXT PRIMARY KEY,
            channel TEXT NOT NULL DEFAULT 'unknown',
            display_name TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS openclaw_task_bindings (
            id TEXT PRIMARY KEY,
            session_hash TEXT NOT NULL REFERENCES openclaw_conversations(session_hash) ON DELETE CASCADE,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            notified_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(session_hash, task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_openclaw_task_bindings_session
        ON openclaw_task_bindings(session_hash, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_openclaw_task_bindings_task
        ON openclaw_task_bindings(task_id);

        CREATE TABLE IF NOT EXISTS openclaw_conversation_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            transcript_mirror_enabled INTEGER NOT NULL DEFAULT 0,
            transcript_retention_days INTEGER NOT NULL DEFAULT 30,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS openclaw_conversation_messages (
            id TEXT PRIMARY KEY,
            session_hash TEXT NOT NULL REFERENCES openclaw_conversations(session_hash) ON DELETE CASCADE,
            turn_id TEXT,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(session_hash, turn_id)
        );
        CREATE INDEX IF NOT EXISTS idx_openclaw_conversation_messages_session
        ON openclaw_conversation_messages(session_hash, created_at ASC);
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO openclaw_conversation_settings(
            id, transcript_mirror_enabled, transcript_retention_days, updated_at
        ) VALUES (1, 0, 30, ?)
        """,
        (utc_now_iso(),),
    )


def _migration_052_library_page_indexes(connection: sqlite3.Connection) -> None:
    """Keep the first library page fast on archives with many subscriptions."""
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wechat_subscription_items_content_published
        ON wechat_subscription_items(content_item_id, published_at DESC)
        """
    )


def _migration_053_wechat_publishing_cover_settings(connection: sqlite3.Connection) -> None:
    """Keep public Qwen cover settings next to the publishing account.

    The API key itself is stored in Keychain by ``wechat_publishing``.  SQLite
    only keeps the non-secret endpoint and model so the settings screen can be
    restored without ever returning a credential to the browser.
    """
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "cover_provider",
        "TEXT NOT NULL DEFAULT 'qwen'",
    )
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "cover_endpoint",
        "TEXT NOT NULL DEFAULT 'https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation'",
    )
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "cover_model",
        "TEXT NOT NULL DEFAULT 'qwen-image-2.0'",
    )
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "cover_keychain_ref",
        "TEXT NOT NULL DEFAULT 'wechat-publishing:qwen-cover'",
    )


def _migration_054_group_report_fact_block_citations(connection: sqlite3.Connection) -> None:
    """Trigger safe maintenance of the editable group-report writer prompt."""
    del connection


def _migration_055_group_report_heading_contract(connection: sqlite3.Connection) -> None:
    """Trigger safe maintenance of the editable report-heading prompts."""
    del connection


def _migration_056_align_report_tree_titles_with_filenames(connection: sqlite3.Connection) -> None:
    """Make existing report tree labels match their canonical Markdown names."""
    rows = connection.execute(
        """SELECT content.id, content.title, document.markdown_path
           FROM content_items AS content
           JOIN content_documents AS document ON document.content_item_id = content.id
           WHERE content.source_provider = 'wechat_report'
             AND content.content_type = 'report'"""
    ).fetchall()
    for row in rows:
        item_id = str(row["id"])
        stem = Path(str(row["markdown_path"] or "")).stem.strip()
        # Historical reports used the full UUID; new reports retain only its
        # first 12 characters.  In both cases, the identity suffix belongs on
        # disk only and is not part of the tree label.
        for suffix in (f"--{item_id}", f"--{item_id[:12]}"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)].rstrip()
                break
        if stem and stem != str(row["title"] or ""):
            connection.execute("UPDATE content_items SET title=? WHERE id=?", (stem, item_id))


def _migration_057_group_report_coverage_repair(connection: sqlite3.Connection) -> None:
    """Trigger safe maintenance of the report writer's hierarchy prompt."""
    del connection


def _migration_058_group_report_editorial_v3(connection: sqlite3.Connection) -> None:
    """Upgrade only untouched group-report guidance to the all-source contract."""
    from services.prompt_file_store import write_report_prompt_file
    from services.wechat_reports import (
        DEFAULT_REPORT_PROMPT_VERSION,
        REPORT_PROMPT_TYPE,
        _default_report_prompt,
    )

    now = utc_now_iso()
    rows = connection.execute(
        """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                  COALESCE(NULLIF(p.display_name, ''), '区间报告') AS display_name,
                  p.updated_at, g.name AS group_name
           FROM wechat_report_prompts p
           JOIN wechat_subscription_groups g ON g.id=p.group_id
           WHERE p.report_type=?
             AND p.template_version IN ('', 'group-report-editorial-v1', 'group-report-editorial-v2')""",
        (REPORT_PROMPT_TYPE,),
    ).fetchall()
    for row in rows:
        connection.execute(
            """UPDATE wechat_report_prompts
               SET template=?, template_version=?, updated_at=? WHERE id=?""",
            (_default_report_prompt(), DEFAULT_REPORT_PROMPT_VERSION, now, row["id"]),
        )
        upgraded = dict(row)
        upgraded["template"] = _default_report_prompt()
        upgraded["template_version"] = DEFAULT_REPORT_PROMPT_VERSION
        upgraded["updated_at"] = now
        # Report guidance is mirrored as Markdown and imported before a report
        # is generated.  Without this write, an old mirror would immediately
        # restore the retired built-in text as a custom prompt.
        write_report_prompt_file(upgraded)


def _migration_059_prompt_code_sync_state(connection: sqlite3.Connection) -> None:
    """Track which built-in prompt source revision reached the live workspace."""
    connection.execute(
        """CREATE TABLE IF NOT EXISTS prompt_code_sync_state (
            default_key TEXT PRIMARY KEY,
            template_hash TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def _migration_067_prompt_code_revision(connection: sqlite3.Connection) -> None:
    """Make built-in prompt publication monotonic across overlapping processes."""
    _add_column_if_missing(
        connection,
        "prompt_code_sync_state",
        "code_revision",
        "INTEGER NOT NULL DEFAULT 0",
    )
    # Hash-only states predate explicit revisions. Treat their current code
    # snapshot as revision 1 so a definition must opt into a newer revision
    # before replacing an editable workspace prompt.
    connection.execute(
        "UPDATE prompt_code_sync_state SET code_revision=1 WHERE code_revision < 1"
    )


def _migration_068_public_report_publication_state(connection: sqlite3.Connection) -> None:
    """Track the public reading URL separately from the WeChat draft lifecycle."""
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "public_site_base_url",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(connection, "wechat_publications", "public_report_slug", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "wechat_publications", "public_report_url", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "wechat_publications", "wechat_article_url", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(connection, "wechat_publications", "published_at", "TEXT")
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_wechat_publications_status_published
           ON wechat_publications(status, published_at DESC)"""
    )


def _migration_069_github_pages_publication(connection: sqlite3.Connection) -> None:
    """Remember only the non-secret GitHub Pages repository identifier."""
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "public_site_provider",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "public_site_repository",
        "TEXT NOT NULL DEFAULT ''",
    )


def _migration_070_wechat_publishing_public_ip(connection: sqlite3.Connection) -> None:
    """Remember only the last successful direct IPv4 used for WeChat APIs.

    The value is non-secret and lets the desktop app warn before it spends time
    exporting and deploying a report from a newly assigned home-network IP.
    """
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "last_verified_public_ip",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        connection,
        "wechat_publishing_accounts",
        "last_verified_public_ip_at",
        "TEXT",
    )


def _migration_071_wechat_report_cover_history(connection: sqlite3.Connection) -> None:
    """Retain every generated report cover while keeping one active version."""
    import hashlib
    import uuid

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_report_covers (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL
                REFERENCES content_items(id) ON DELETE CASCADE,
            cover_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            visual_brief_json TEXT NOT NULL DEFAULT '{}',
            prompt_metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE(content_item_id, cover_path)
        );
        CREATE INDEX IF NOT EXISTS idx_wechat_report_covers_content_created
        ON wechat_report_covers(content_item_id, created_at);
        """
    )


    rows = connection.execute(
        """
        SELECT content_item_id, cover_path, cover_plan_json,
               cover_prompt_metadata_json, cover_generated_at
        FROM wechat_reports
        WHERE cover_path IS NOT NULL AND cover_path != ''
        """
    ).fetchall()
    cover_root = (settings.data_dir / "report_covers").expanduser().resolve()
    for row in rows:
        path = Path(str(row["cover_path"] or "")).expanduser().resolve()
        try:
            path.relative_to(cover_root)
        except ValueError:
            continue
        if not path.is_file():
            continue
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        connection.execute(
            """
            INSERT OR IGNORE INTO wechat_report_covers (
                id, content_item_id, cover_path, content_hash,
                visual_brief_json, prompt_metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                str(row["content_item_id"]),
                str(path),
                content_hash,
                str(row["cover_plan_json"] or "{}"),
                str(row["cover_prompt_metadata_json"] or "{}"),
                str(row["cover_generated_at"] or utc_now_iso()),
            ),
        )


def _migration_072_paddle_ocr_jobs(connection: sqlite3.Connection) -> None:
    """Persist remote OCR job IDs so slow provider work is never resubmitted."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS paddle_ocr_jobs (
            content_digest TEXT PRIMARY KEY,
            provider_job_id TEXT,
            status TEXT NOT NULL,
            result_url TEXT,
            result_kind TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_paddle_ocr_jobs_pending
        ON paddle_ocr_jobs(status, updated_at);

        CREATE TABLE IF NOT EXISTS paddle_ocr_job_consumers (
            content_digest TEXT NOT NULL REFERENCES paddle_ocr_jobs(content_digest) ON DELETE CASCADE,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            source_url TEXT NOT NULL DEFAULT '',
            cached_path TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(content_digest, content_item_id)
        );
        """
    )


def _migration_073_republish_wechat_cover_style_prompts(
    connection: sqlite3.Connection,
) -> None:
    """Give the six-style cover prompts a safe pre-publication baseline.

    Some workspaces first created prompt sync state while the old two-style
    template was still live. That bootstrap records the current code revision
    without replacing editable text, so revision 5 could be marked published
    even though its style blocks never reached SQLite. Seed revision 5 here;
    the normal monotonic publisher will then apply revision 6 exactly once.
    """
    now = utc_now_iso()
    default_keys = (
        "builtin:wechat_cover_planner:v1:公众号封面 · 主题策划",
        "builtin:wechat_cover_image:v1:公众号封面 · 图像生成",
    )
    for default_key in default_keys:
        connection.execute(
            """INSERT INTO prompt_code_sync_state
               (default_key, template_hash, code_revision, updated_at)
               VALUES (?, '', 5, ?)
               ON CONFLICT(default_key) DO NOTHING""",
            (default_key, now),
        )


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


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")


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


def _migration_080_structural_knowledge_index(connection: sqlite3.Connection) -> None:
    """Add the V2 source snapshot and parent/child retrieval index.

    The old index is intentionally left untouched here.  Its cache rows were
    cleared before this migration, while keeping the tables briefly avoids
    breaking an in-flight desktop process during the V2 rollout.  V2 does not
    read or write those legacy tables.
    """
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_source_snapshots (
            content_item_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            source_hash TEXT NOT NULL,
            chunker_version TEXT NOT NULL,
            markdown_path TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('ready', 'failed')),
            error_message TEXT NOT NULL DEFAULT '',
            indexed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS knowledge_v2_chunks (
            id TEXT PRIMARY KEY,
            content_item_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
            parent_chunk_id TEXT REFERENCES knowledge_v2_chunks(id) ON DELETE CASCADE,
            chunk_kind TEXT NOT NULL CHECK(chunk_kind IN ('parent', 'child')),
            ordinal INTEGER NOT NULL,
            heading_path TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL,
            token_count INTEGER NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(content_item_id, chunk_kind, ordinal, source_hash)
        );

        CREATE TABLE IF NOT EXISTS knowledge_v2_embeddings (
            chunk_id TEXT PRIMARY KEY REFERENCES knowledge_v2_chunks(id) ON DELETE CASCADE,
            embedding_model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            vector_json TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_v2_search
        USING fts5(chunk_id UNINDEXED, searchable, tokenize='unicode61');

        CREATE INDEX IF NOT EXISTS idx_knowledge_v2_snapshots_state
        ON knowledge_source_snapshots(state, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_v2_chunks_content
        ON knowledge_v2_chunks(content_item_id, chunk_kind, ordinal);
        CREATE INDEX IF NOT EXISTS idx_knowledge_v2_children_parent
        ON knowledge_v2_chunks(parent_chunk_id, ordinal);
        CREATE INDEX IF NOT EXISTS idx_knowledge_v2_embeddings_model
        ON knowledge_v2_embeddings(embedding_model, dimensions);
        """
    )


def _migration_081_drop_retired_knowledge_index(connection: sqlite3.Connection) -> None:
    """Remove the retired whole-document knowledge cache and its group editor."""
    connection.executescript(
        """
        DROP TABLE IF EXISTS knowledge_chunk_search;
        DROP TABLE IF EXISTS knowledge_chunk_embeddings;
        DROP TABLE IF EXISTS knowledge_chunks;
        DROP TABLE IF EXISTS knowledge_group_memberships;
        DROP TABLE IF EXISTS knowledge_groups;
        """
    )


def _migration_082_knowledge_prompt_templates(connection: sqlite3.Connection) -> None:
    """Publish the editable prompt records used by the V2 knowledge pipeline."""
    from services.prompt_templates import seed_default_prompt_templates

    seed_default_prompt_templates(connection)


def _migration_083_source_context_records(connection: sqlite3.Connection) -> None:
    """Persist bounded platform metadata and comment evidence as a first-class asset."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS content_source_contexts (
            content_item_id TEXT PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'running', 'ready', 'failed')),
            context_json TEXT NOT NULL DEFAULT '{}',
            comment_sample_count INTEGER NOT NULL DEFAULT 0,
            comment_total INTEGER,
            comments_complete INTEGER NOT NULL DEFAULT 0,
            last_attempt_at TEXT,
            last_success_at TEXT,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_content_source_contexts_status
        ON content_source_contexts(status, updated_at DESC);
        """
    )


def _migration_084_source_context_analysis_prompt(connection: sqlite3.Connection) -> None:
    """Publish the editable comment-analysis rules for existing workspaces."""
    from services.prompt_templates import seed_default_prompt_templates

    seed_default_prompt_templates(connection)


def _migration_085_repair_source_context_assets(connection: sqlite3.Connection) -> None:
    """Repair workspaces where earlier local builds already consumed 83/84."""
    _migration_083_source_context_records(connection)
    _migration_084_source_context_analysis_prompt(connection)


def _migration_086_wechat_collection_guardrails(connection: sqlite3.Connection) -> None:
    """Persist account-level rate limits and move bursty hourly checks to a safe baseline."""
    _add_column_if_missing(connection, "wechat_accounts", "rate_limited_until", "TEXT")
    _add_column_if_missing(connection, "wechat_accounts", "rate_limit_reason", "TEXT")
    _add_column_if_missing(connection, "wechat_accounts", "last_rate_limited_at", "TEXT")
    _add_column_if_missing(connection, "wechat_accounts", "request_window_started_at", "TEXT")
    _add_column_if_missing(
        connection,
        "wechat_accounts",
        "request_count",
        "INTEGER NOT NULL DEFAULT 0",
    )

    now = datetime.now(timezone.utc)
    # Earlier builds allowed every subscription to run hourly. Spread those
    # existing aggressive schedules across a day so upgrading cannot trigger a
    # second immediate burst against the same authenticated account.
    account_rows = connection.execute("SELECT id FROM wechat_accounts ORDER BY created_at").fetchall()
    for account_row in account_rows:
        subscriptions = connection.execute(
            """
            SELECT id
            FROM wechat_subscriptions
            WHERE account_id = ? AND enabled = 1 AND sync_interval_minutes < 1440
            ORDER BY COALESCE(last_sync_at, created_at), id
            """,
            (account_row["id"],),
        ).fetchall()
        total = len(subscriptions)
        for index, subscription in enumerate(subscriptions, start=1):
            offset_minutes = max(1, int(index * 1440 / max(1, total)))
            connection.execute(
                """
                UPDATE wechat_subscriptions
                SET sync_interval_minutes = 1440, next_sync_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    (now + timedelta(minutes=offset_minutes)).isoformat(),
                    now.isoformat(),
                    subscription["id"],
                ),
            )

    stale_before = (now - timedelta(hours=2)).isoformat()
    connection.execute(
        """
        UPDATE wechat_sync_runs
        SET status = 'failed', finished_at = ?, error_category = 'interrupted',
            error_message = '应用退出或任务中断，已停止过期的公众号检查'
        WHERE status = 'running' AND started_at < ?
        """,
        (now.isoformat(), stale_before),
    )


def _migration_087_wechat_public_discovery(connection: sqlite3.Connection) -> None:
    """Persist public WeChat discovery separately from authenticated subscriptions."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS wechat_public_sources (
            id TEXT PRIMARY KEY,
            source_key TEXT NOT NULL UNIQUE,
            source_kind TEXT NOT NULL
                CHECK(source_kind IN ('manual', 'album')),
            title TEXT NOT NULL DEFAULT '',
            source_url TEXT,
            biz TEXT,
            album_id TEXT,
            coverage_label TEXT NOT NULL DEFAULT '',
            last_discovery_at TEXT,
            last_error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wechat_discovery_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES wechat_public_sources(id) ON DELETE CASCADE,
            task_id TEXT,
            mode TEXT NOT NULL CHECK(mode IN ('manual', 'album')),
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK(status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
            request_json TEXT NOT NULL DEFAULT '{}',
            cursor_json TEXT NOT NULL DEFAULT '{}',
            candidate_count INTEGER NOT NULL DEFAULT 0,
            verified_count INTEGER NOT NULL DEFAULT 0,
            imported_count INTEGER NOT NULL DEFAULT 0,
            duplicate_count INTEGER NOT NULL DEFAULT 0,
            failed_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT NOT NULL DEFAULT '',
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wechat_discovery_candidates (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES wechat_discovery_runs(id) ON DELETE CASCADE,
            normalized_url TEXT NOT NULL,
            canonical_source_id TEXT,
            discovered_via TEXT NOT NULL,
            observed_title TEXT NOT NULL DEFAULT '',
            observed_biz TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            verification_state TEXT NOT NULL DEFAULT 'pending'
                CHECK(verification_state IN ('pending', 'verified', 'rejected')),
            import_state TEXT NOT NULL DEFAULT 'pending'
                CHECK(import_state IN ('pending', 'imported', 'duplicate', 'failed')),
            content_item_id TEXT REFERENCES content_items(id) ON DELETE SET NULL,
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, normalized_url)
        );

        CREATE INDEX IF NOT EXISTS idx_wechat_discovery_runs_created
        ON wechat_discovery_runs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_wechat_discovery_candidates_run
        ON wechat_discovery_candidates(run_id, created_at);
        """
    )
    from services.wechat_urls import canonical_wechat_article_id, is_wechat_article_url

    # Earlier builds used the entire URL as the content identity, so tracking
    # parameters could create duplicates. Promote existing public articles
    # without deleting or merging any user record when two legacy rows already
    # collide.
    legacy_rows = connection.execute(
        """
        SELECT id, source_url, canonical_source_id
        FROM content_items
        WHERE source_provider = 'wechat' AND source_url IS NOT NULL
        """
    ).fetchall()
    for row in legacy_rows:
        source_url = str(row["source_url"] or "")
        if not is_wechat_article_url(source_url):
            continue
        canonical_id = canonical_wechat_article_id(source_url)
        if not canonical_id or canonical_id == str(row["canonical_source_id"] or ""):
            continue
        try:
            connection.execute(
                "UPDATE content_items SET canonical_source_id = ? WHERE id = ?",
                (canonical_id, row["id"]),
            )
        except sqlite3.IntegrityError:
            continue


def _migration_088_wechat_seed_discovery_review(connection: sqlite3.Connection) -> None:
    """Add reviewable public-search discovery without changing phase-one modes."""
    _add_column_if_missing(
        connection,
        "wechat_public_sources",
        "discovery_strategy",
        "TEXT NOT NULL DEFAULT 'direct'",
    )
    _add_column_if_missing(
        connection,
        "wechat_discovery_runs",
        "discovery_strategy",
        "TEXT NOT NULL DEFAULT 'direct'",
    )
    _add_column_if_missing(
        connection,
        "wechat_discovery_runs",
        "review_required",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(connection, "wechat_discovery_runs", "reviewed_at", "TEXT")
    _add_column_if_missing(
        connection,
        "wechat_discovery_runs",
        "review_import_status",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        connection,
        "wechat_discovery_candidates",
        "observed_source_name",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        connection,
        "wechat_discovery_candidates",
        "search_provider",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        connection,
        "wechat_discovery_candidates",
        "search_query",
        "TEXT NOT NULL DEFAULT ''",
    )
    _add_column_if_missing(
        connection,
        "wechat_discovery_candidates",
        "search_rank",
        "INTEGER",
    )


def _migration_089_wechat_album_subscriptions(connection: sqlite3.Connection) -> None:
    """Make persisted public albums eligible for low-frequency incremental checks."""
    _add_column_if_missing(
        connection,
        "wechat_public_sources",
        "enabled",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection,
        "wechat_public_sources",
        "auto_analyze",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection,
        "wechat_public_sources",
        "sync_interval_minutes",
        "INTEGER NOT NULL DEFAULT 720",
    )
    _add_column_if_missing(connection, "wechat_public_sources", "next_sync_at", "TEXT")
    _add_column_if_missing(
        connection,
        "wechat_public_sources",
        "consecutive_failure_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    _add_column_if_missing(
        connection,
        "wechat_public_sources",
        "last_new_count",
        "INTEGER NOT NULL DEFAULT 0",
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wechat_public_sources_due
        ON wechat_public_sources(source_kind, enabled, next_sync_at)
        """
    )


_MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_001_initial_schema),
    (2, _migration_002_library_tree),
    (3, _migration_003_wechat_subscriptions),
    (4, _migration_004_show_wechat_subscription_items_in_library),
    (5, _migration_005_qa_history_indexes),
    (6, _migration_006_wechat_sync_backoff),
    (7, _migration_007_content_analyses),
    (8, _migration_008_remove_content_tags),
    (9, _migration_009_remove_retired_external_wechat_accounts),
    (10, _migration_010_wechat_content_filter_rules),
    (11, _migration_011_wechat_groups_and_reports),
    (12, _migration_012_wechat_report_prompts),
    (13, _migration_013_wechat_subscription_group_memberships),
    (14, _migration_014_wechat_subscription_descriptions),
    (15, _migration_015_library_trash),
    (16, _migration_016_wechat_report_source_digests),
    (17, _migration_017_content_source_metadata),
    (18, _migration_018_wechat_report_source_coverage),
    (19, _migration_019_miniprogram_forum_capture),
    (20, _migration_020_campus_digest_generation),
    (21, _migration_021_version_wechat_report_prompts),
    (22, _migration_022_link_miniprogram_run_documents),
    (23, _migration_023_support_range_reports),
    (24, _migration_024_prompt_workspace),
    (25, _migration_025_ai_call_summary_indexes),
    (26, _migration_026_content_documents),
    (27, _migration_027_prompt_default_keys),
    (28, _migration_028_ai_call_cache_usage),
    (29, _migration_029_group_report_prompt_type),
    (30, _migration_030_group_report_source_summaries),
    (31, _migration_031_disable_auto_article_analysis),
    (32, _migration_032_ocr_call_history),
    (33, _migration_033_qa_conversation_archives),
    (34, _migration_034_library_source_folder_bindings),
    (35, _migration_035_creator_sources),
    (36, _migration_036_knowledge_retrieval),
    (37, _migration_037_creator_subscriptions),
    (38, _migration_038_creator_processing_policies),
    (39, _migration_039_knowledge_chunk_curation),
    (40, _migration_040_creator_sync_health),
    (41, _migration_041_knowledge_conversation_archives),
    (42, _migration_042_rss_subscriptions),
    (43, _migration_043_rss_source_groups),
    (44, _migration_044_rss_auto_analysis),
    (45, _migration_045_creator_work_metadata),
    (46, _migration_046_hide_internal_forum_posts),
    (47, _migration_047_personal_favorites),
    (48, _migration_048_source_read_limits),
    (50, _migration_050_openclaw_conversation_bindings),
    (51, _migration_051_wechat_publishing),
    (52, _migration_052_library_page_indexes),
    (53, _migration_053_wechat_publishing_cover_settings),
    (54, _migration_054_group_report_fact_block_citations),
    (55, _migration_055_group_report_heading_contract),
    (56, _migration_056_align_report_tree_titles_with_filenames),
    (57, _migration_057_group_report_coverage_repair),
    (58, _migration_058_group_report_editorial_v3),
    (59, _migration_059_prompt_code_sync_state),
    (60, _migration_060_group_report_stage_adapters),
    (61, _migration_061_openclaw_notification_delivery),
    (62, _migration_062_group_report_event_ledger),
    (63, _migration_063_report_prompt_history_and_generation_metadata),
    (64, _migration_064_ai_call_finish_reason),
    (65, _migration_065_wechat_cover_planning_and_local_assets),
    (66, _migration_066_image_generation_usage),
    (67, _migration_067_prompt_code_revision),
    (68, _migration_068_public_report_publication_state),
    (69, _migration_069_github_pages_publication),
    (70, _migration_070_wechat_publishing_public_ip),
    (71, _migration_071_wechat_report_cover_history),
    (72, _migration_072_paddle_ocr_jobs),
    (73, _migration_073_republish_wechat_cover_style_prompts),
    (74, _migration_074_completion_notifications),
    (75, _migration_075_library_folder_pinning),
    (76, _migration_076_report_group_schedules),
    (77, _migration_077_xiaohongshu_favorites),
    (79, _migration_079_backfill_wechat_source_names),
    (80, _migration_080_structural_knowledge_index),
    (81, _migration_081_drop_retired_knowledge_index),
    (82, _migration_082_knowledge_prompt_templates),
    (83, _migration_083_source_context_records),
    (84, _migration_084_source_context_analysis_prompt),
    (85, _migration_085_repair_source_context_assets),
    (86, _migration_086_wechat_collection_guardrails),
    (87, _migration_087_wechat_public_discovery),
    (88, _migration_088_wechat_seed_discovery_review),
    (89, _migration_089_wechat_album_subscriptions),
    (90, _migration_090_unify_video_source_subscriptions),
    (91, _migration_091_unify_xiaohongshu_favorite_subscription),
    (92, _migration_092_repair_placeholder_content_items),
]
