"""Archived SQLite migrations: second schema segment. Append-only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from config import settings
from services.database_migrations.common import _add_column_if_missing, utc_now_iso

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
