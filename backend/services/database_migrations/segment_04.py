"""Archived SQLite migrations: fourth schema segment. Append-only."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from services.database_migrations.common import _add_column_if_missing

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
