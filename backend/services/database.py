from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from config import ensure_private_data_directory, ensure_private_data_file, settings
from services.database_migrations import MIGRATIONS, SCHEMA_VERSION, migration_named  # noqa: F401


_DATABASE_INITIALIZE_LOCK = RLock()
_INITIALIZED_DATABASES: set[Path] = set()
DATABASE_BUSY_TIMEOUT_MS = 30_000
_WAL_ENABLE_RETRY_INTERVAL_SECONDS = 0.1


def __getattr__(name: str):
    """Preserve access to named repair migrations without owning their code."""
    return migration_named(name)


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
            for version, migration in MIGRATIONS:
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
